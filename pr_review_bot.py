from openai import OpenAI
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from azure.devops.v7_1.git.models import GitPullRequestSearchCriteria,Comment, CommentThread,GitVersionDescriptor,GitBaseVersionDescriptor,GitTargetVersionDescriptor
import difflib

# Load environment variables from .env file
load_dotenv()

# Set up OpenAI API key from environment variables
OpenAI_api_key = os.getenv("OPENAI_API_KEY")

# Azure DevOps Organization and Project details from environment variables
organization_url = os.getenv("AZURE_ORG_URL")
personal_access_token = os.getenv("AZURE_PAT")
project_name = os.getenv("PROJECT_NAME")
repository_id = os.getenv("REPO_ID")
max_tokens = os.getenv("MAX_TOKENS")
model_version = os.getenv("MODEL_VERSION")

# List of authors to ignore
IGNORED_AUTHORS = os.getenv("IGNORED_AUTHORS", "NONE").split(",")

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
def get_pull_requests():
    try:
        connection = get_azure_devops_connection()
        if connection is None:
            return []

        criteria = GitPullRequestSearchCriteria(status='active')
        git_client = connection.clients.get_git_client()
        pull_requests = git_client.get_pull_requests(
            project=project_name,
            repository_id=repository_id,
            search_criteria=criteria
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
    pr_date = datetime.strptime(creation_date, "%Y-%m-%dT%H:%M:%SZ")  # Azure DevOps uses ISO 8601 format
    return now - pr_date <= timedelta(days=1)

# Analyze the PR diff using OpenAI
def analyze_pr_diff(pr_id, diff):
    prompt="Review the following pull request and provide a short 1 paragrpah feedback for all modified files.be short and summeraized for every file no more than 1 paragraph is allowed, Give attention to time complexity and clean code principles check for possible errors:"
    client = OpenAI(api_key=OpenAI_api_key)  # This is the default and can be omitted

    reponse = client.chat.completions.create(
        model=model_version,  # Correct model name
        messages=[{
            "role": "user",
            "content": prompt,
        }]
    )
    
    return  response.choices[0].text.strip()


# Comment on the pull request
def comment_on_pr(pr_id, comment):
    try:
        connection = get_azure_devops_connection()
        if connection is None:
            return

        git_client = connection.clients.get_git_client()

        # Create a comment thread
        thread = CommentThread(
            comments=[Comment(content=comment)],
            status="active"
        )

        # Add the comment thread to the pull request
        git_client.create_thread(
            repository_id=repository_id,
            project=project_name,
            pull_request_id=pr_id,
            comment_thread=thread
        )
        print(f"Comment posted on PR #{pr_id}")
    except Exception as e:
        print(f"Error commenting on PR {pr_id}: {str(e)}")


def fetch_pr_diff(pr_id):
    try:
        connection = get_azure_devops_connection()
        git_client = connection.clients.get_git_client()
        commits = git_client.get_pull_request_commits(project=project_name, repository_id=repository_id, pull_request_id=pr_id)
        target_commit_id = commits[0].commit_id
        base_commit_id = commits[-1].commit_id

        base_version_descriptor = GitBaseVersionDescriptor(base_version=base_commit_id, base_version_type="commit")
        target_version_descriptor = GitTargetVersionDescriptor(target_version=target_commit_id, target_version_type ="commit")

        commit_diffs = git_client.get_commit_diffs(repository_id=repository_id, project=project_name, base_version_descriptor=base_version_descriptor, target_version_descriptor=target_version_descriptor)

        # Get the list of changed files
        for change in commit_diffs.changes:
            print(change['item']['path'])
                # Process diffs and print added/modified lines
            for diff in commit_diffs.changes:
                    if diff['changeType'] in ['add', 'edit']:
                        file_path = diff['item']['path']
                        file_content = git_client.get_item_text(
                            repository_id=repository_id,
                            path=file_path,
                            project=project_name,
                            version_descriptor=GitVersionDescriptor(
                                version=target_commit_id,
                                version_type="commit"
                            )
                        )
                        file_content2 = git_client.get_item_text(
                            repository_id=repository_id,
                            path=file_path,
                            project=project_name,
                            version_descriptor=GitVersionDescriptor(
                                version=base_commit_id,
                                version_type="commit"
                            )
                        )
                        changed_content = ''
                        file_content_ = ''.join(chunk.decode('utf-8') for chunk in file_content)
                        file_content2_ = ''.join(chunk.decode('utf-8') for chunk in file_content2)
                        differ = difflib.Differ()
                        diff = differ.compare(file_content_.splitlines(), file_content2_.splitlines())
                        for line in diff:
                                if line.startswith('- ') or line.startswith('+ '):
                                    changed_content += line
                        
                        print(changed_content)
                        return changed_content
        

    except Exception as e:
        print(e)
        return None


def review_pull_requests():
    try:
        pull_requests = get_pull_requests()
        for pr in pull_requests:
            author_name = pr.created_by.display_name

            # Ignore PRs by specified authors
            if author_name in IGNORED_AUTHORS:
                print(f"Ignoring PR #{pr.pull_request_id} by {author_name}")
                continue

            print(f"Reviewing PR #{pr.pull_request_id} - {pr.title} by {author_name}")

            # Fetch the diff content for the pull request
            diff = fetch_pr_diff(pr.pull_request_id)
            if diff:
                print(f"Fetched diff content for PR #{pr.pull_request_id}")

                # Analyze the diff content using OpenAI
                review_comment = analyze_pr_diff(pr.pull_request_id, diff)
                print(f"Generated Review for PR #{pr.pull_request_id}: {review_comment}")

                # Comment on the pull request with the generated feedback
                comment_on_pr(pr.pull_request_id, review_comment)
                print(f"Posted review comment on PR #{pr.pull_request_id}")
            else:
                print(f"No diff content found for PR #{pr.pull_request_id}")
    except Exception as e:
        print(f"Error reviewing pull requests: {str(e)}")

# Run the script
if __name__ == "__main__":
    try:
        review_pull_requests()
    except Exception as e:
        print(f"An error occurred while reviewing pull requests: {str(e)}")
