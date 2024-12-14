from llama_stack_client import LlamaStackClient
from azure.devops.connection import Connection
from llama_stack_client.types import UserMessage
from msrest.authentication import BasicAuthentication
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from azure.devops.v7_0.git.models import GitPullRequestSearchCriteria,Comment, CommentThread,GitTargetVersionDescriptor,GitBaseVersionDescriptor
from flask import Flask, request, jsonify
import difflib

load_dotenv()

meta_llama_url = os.getenv("META_LLAMA_URL")
organization_url = os.getenv("AZURE_ORG_URL")
personal_access_token = os.getenv("AZURE_PAT")
project_name = os.getenv("PROJECT_NAME")
repository_id = os.getenv("REPO_ID")
max_tokens = os.getenv("MAX_TOKENS")
model_version = os.getenv("MODEL_VERSION")
flask_port = os.getenv("FLASK_PORT")
IGNORED_AUTHORS = os.getenv("IGNORED_AUTHORS", "NONE").split(",")

app = Flask(__name__)

processed_prs = set()

def validate_env_variables():
    required_vars = [
        "AZURE_ORG_URL", "AZURE_PAT", "PROJECT_NAME", 
        "REPO_ID", "FLASK_PORT", "META_LLAMA_URL", "MODEL_VERSION"
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise EnvironmentError(f"Missing environment variables: {', '.join(missing_vars)}")


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        pr_id = data.get("resource",{}).get("pullRequestId")
        review_pull_requests(pr_id)
        return "Pull requests reviewed", 200
    except Exception as e:
        print(e)
        return "Internal Server Error", 500

# Authenticate to Azure DevOps
def get_azure_devops_connection():
    try:
        credentials = BasicAuthentication('', personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)
        return connection
    except Exception as e:
        print(f"Error connecting to Azure DevOps: {str(e)}")
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
        print(f"Error fetching pull requests: {str(e)}")
        return []

# Check if PR author is ignored
def is_author_ignored(author):
    return author.lower() in [ignored_author.lower() for ignored_author in IGNORED_AUTHORS]

# Filter PRs created in the last 24 hours
def is_recent_pr(creation_date):
    now = datetime.utcnow()
    pr_date = datetime.strptime(creation_date, "%Y-%m-%dT%H:%M:%SZ") 
    return now - pr_date <= timedelta(days=1)

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
        
        client = LlamaStackClient(base_url=meta_llama_url)
        
        response = client.inference.chat_completion(
            messages=[UserMessage(content=prompt, role="user")],
            model=model_version,
            stream=False,
        )
        
        return response.choices[0].message['content']
    
    except Exception as e:
        print(f"Error analyzing PR : {str(e)}")
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
        print(f"Comment posted on PR #{pr_id}")
    except Exception as e:
        print(f"Error commenting on PR {pr_id}: {str(e)}")

# Fetch the diff content of a pull request
def fetch_pr_diff(pr_id):
    connection = get_azure_devops_connection()
    git_client = connection.clients.get_git_client()

    pr = git_client.get_pull_request_by_id(pr_id)
    
    print(f"\nPR Details:")
    print(f"PR ID: {pr.pull_request_id}")
    print(f"Source: {pr.source_ref_name}")
    print(f"Target: {pr.target_ref_name}")
    
    iterations = git_client.get_pull_request_iterations(
        project=project_name,
        repository_id=repository_id,
        pull_request_id=pr_id
    )
    
    latest_iteration = iterations[-1].id
    
    changes = git_client.get_pull_request_iteration_changes(
        project=project_name,
        repository_id=repository_id,
        pull_request_id=pr_id,
        iteration_id=latest_iteration
    )
    
    print(f"\nNumber of changes found: {len(changes.change_entries)}")
    
    changed_content = []
    for change in changes.change_entries:
        file_path = change.additional_properties['item']['path']
        print(f"\nProcessing {file_path}")
        
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
            print(f"Error processing {file_path}: {str(e)}")
    return changed_content



# Main function to fetch PRs and review them
def review_pull_requests(pr_id):
    try:
        pr = get_pull_requests(pr_id)
        author_name = pr.created_by.display_name

        if author_name in IGNORED_AUTHORS:
            print(f"Ignoring PR #{pr.pull_request_id} by {author_name}")
            print(f"Reviewing PR #{pr.pull_request_id} - {pr.title} by {author_name}")

        diff = fetch_pr_diff(pr.pull_request_id)
        if diff:
            print(f"Fetched diff content for PR #{pr.pull_request_id}")

            review_comment = analyze_pr_diff(diff)
            comment_on_pr(pr.pull_request_id, review_comment)
            print(f"Posted review comment on PR #{pr.pull_request_id}")
        else:
            print(f"No diff content found for PR #{pr.pull_request_id}")
    except Exception as e:
        print(f"Error reviewing pull requests: {str(e)}")

if __name__ == "__main__":
    try:
        validate_env_variables()   
        # Start ngrok tunnel
        flask_port = int(flask_port)
        # Start Flask app
        app.run(port=flask_port)
    except Exception as e:
        print(f"An error occurred while reviewing pull requests: {str(e)}")
