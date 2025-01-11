import openai
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from azure.devops.v7_0.git.models import Comment, CommentThread,GitTargetVersionDescriptor,GitBaseVersionDescriptor
from flask import Flask, request
import difflib
from logger import setup_logger

logger = setup_logger()
load_dotenv()

OpenAI_api_key = os.getenv("OPENAI_API_KEY")
organization_url = os.getenv("AZURE_ORG_URL")
personal_access_token = os.getenv("AZURE_PAT")
project_name = os.getenv("PROJECT_NAME")
repository_id = os.getenv("REPO_ID")
max_tokens = os.getenv("MAX_TOKENS")
model_version = os.getenv("MODEL_VERSION")
flask_port = os.getenv("FLASK_PORT")
IGNORED_AUTHORS = os.getenv("IGNORED_AUTHORS", "NONE").split(",")
IGNORED_FILE_TYPES = os.getenv("IGNORED_FILE_TYPES", "NONE").split(",")

app = Flask(__name__)

processed_prs = set()


def validate_env_variables():
    required_vars = [
        "AZURE_ORG_URL", "AZURE_PAT", "PROJECT_NAME", 
        "REPO_ID", "FLASK_PORT", "OPENAI_API_KEY", "MODEL_VERSION"
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        raise EnvironmentError(f"Missing environment variables: {', '.join(missing_vars)}")
    logger.info("Environment variables validated")


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        pr_id = data.get("resource",{}).get("pullRequestId")
        review_pull_requests(pr_id)
        return "Pull requests reviewed", 200
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        return "Internal Server Error", 500


# Authenticate to Azure DevOps
def get_azure_devops_connection():
    try:
        credentials = BasicAuthentication('', personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)
        logger.info("Connected to Azure DevOps successfully.")
        return connection
    except Exception as e:
        logger.error(f"Error connecting to Azure DevOps: {str(e)}")
        return None


# Get pull requests from Azure DevOps
def get_pull_requests(pr_id):
    try:
        connection = get_azure_devops_connection()
        if connection is None:
            return []

        git_client = connection.clients.get_git_client()
        pull_requests = git_client.get_pull_request_by_id(
            project=project_name,
            pull_request_id=pr_id
        )
        return pull_requests
    except Exception as e:
        logger.error(f"Error fetching pull requests: {str(e)}")
        return []


# Check if PR author is ignored
def is_author_ignored(author):
    return author.lower() in [ignored_author.lower() for ignored_author in IGNORED_AUTHORS]


# Analyze the PR diff using OpenAI
def analyze_pr_diff(diff):
    try:
        prompt = (
        "Review the following pull request and provide a short 1 paragraph feedback for all modified files. "
        "Be short and summarized for every file; no more than 1 paragraph is allowed. "
        "Give attention to time complexity and clean code principles. Check for possible errors:\n\n"
        )
        for item in diff:
            file_name = item.get("file", "Unknown File")
            changes = item.get("changes", "No changes provided")
            prompt += f"File: {file_name}\n{changes}\n\n"
        response = openai.chat.completions.create(
        model=model_version,
        messages=[
        {
            "role": "user",
            "content": prompt,
        }
    ],
)
        return response.choices[0].text.strip()
    except Exception as e:
        logger.error(f"Error analyzing PR: {str(e)}")
        return ""


# Comment on the pull request
def comment_on_pr(pr_id, comment):
    try:
        connection = get_azure_devops_connection()
        if connection is None:
            return

        git_client = connection.clients.get_git_client()

        thread = CommentThread(
            comments=[Comment(content=comment)],
            status="active"
        )

        git_client.create_thread(
            repository_id=repository_id,
            project=project_name,
            pull_request_id=pr_id,
            comment_thread=thread
        )
        logger.info(f"Comment posted on PR #{pr_id}")
    except Exception as e:
        logger.error(f"Error commenting on PR {pr_id}: {str(e)}")


# Fetch the diff content of a pull request
def fetch_pr_diff(pr_id):
    connection = get_azure_devops_connection()
    git_client = connection.clients.get_git_client()

    pr = git_client.get_pull_request_by_id(pr_id)

    logger.debug(f"PR ID: {pr.pull_request_id}")
    logger.debug(f"Source: {pr.source_ref_name}")
    logger.debug(f"Target: {pr.target_ref_name}")
    
    iterations = git_client.get_pull_request_iterations(
        project=project_name,
        repository_id=repository_id,
        pull_request_id=pr_id
    )
    
    latest_iteration = iterations[-1].id
    logger.debug(f"Latest iteration ID: {latest_iteration}")
    
    changes = git_client.get_pull_request_iteration_changes(
        project=project_name,
        repository_id=repository_id,
        pull_request_id=pr_id,
        iteration_id=latest_iteration
    )
    
    logger.debug(f"\nNumber of changes found: {len(changes.change_entries)}")
    
    changed_content = []
    for change in changes.change_entries:
        file_path = change.additional_properties['item']['path']
        logger.debug(f"\nProcessing {file_path}")
        file_extension = os.path.splitext(file_path)[1]
        if file_extension in IGNORED_FILE_TYPES:
            logger.info(f"Skipping file {file_path} due to ignored file type.")
            continue
        try:
            pr_content = git_client.get_item_content(
                repository_id=repository_id,
                project=project_name,
                path=file_path,
                download=True,  
                version_descriptor=GitBaseVersionDescriptor(
                    version=pr.source_ref_name.replace('refs/heads/', ''),
                    version_type="branch"
                )
            )
            
            target_content = git_client.get_item_content(
                repository_id=repository_id,
                project=project_name,
                path=file_path,
                download=True, 
                version_descriptor=GitTargetVersionDescriptor(
                    version=pr.target_ref_name.replace('refs/heads/', ''),
                    version_type="branch"
                )
            )
            
            pr_text = ''.join(chunk.decode('utf-8') for chunk in pr_content)
            target_text = ''.join(chunk.decode('utf-8') for chunk in target_content)
            
            differ = difflib.Differ()
            diff = differ.compare(pr_text.splitlines(), target_text.splitlines()) 
            actual_changes = [line.lstrip('-+ ')  for line in diff if line.startswith(('- ', '+ '))]
            if actual_changes:
                file_changes = {
                    "file": file_path,
                    "changes": '\n'.join([line if line else '' for line in actual_changes])
                }
                changed_content.append(file_changes)
            else:
                file_changes = None
        except Exception as e:
            logger.error(f"Error processing {file_path}: {str(e)}")
    return changed_content


# Main function to fetch PRs and review them
def review_pull_requests(pr_id):
    try:
        pr = get_pull_requests(pr_id)
        if not pr:
            return None
        author_name = pr.created_by.display_name

        if author_name in IGNORED_AUTHORS:
            logger.info(f"Ignoring PR #{pr.pull_request_id} by {author_name}")
            logger.info(f"Reviewing PR #{pr.pull_request_id} - {pr.title} by {author_name}")
            return

        diff = fetch_pr_diff(pr.pull_request_id)
        if diff:
            logger.info(f"Fetched diff content for PR #{pr.pull_request_id}")

            review_comment = analyze_pr_diff(diff)
            comment_on_pr(pr.pull_request_id, review_comment)
            logger.info(f"Posted review comment on PR #{pr.pull_request_id}")
        else:
            logger.info(f"No diff content found for PR #{pr.pull_request_id}")
    except Exception as e:
        logger.error(f"Error reviewing pull requests: {str(e)}")


if __name__ == "__main__":
    try:
        validate_env_variables()   
        flask_port = int(flask_port)
        app.run(port=flask_port)
    except Exception as e:
        logger.error(f"An error occurred while reviewing pull requests: {str(e)}")
