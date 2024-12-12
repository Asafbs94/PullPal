from llama_stack_client import LlamaStackClient
from llama_stack_client.types import UserMessage
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from azure.devops.v7_1.git.models import GitPullRequestSearchCriteria,Comment, CommentThread
from datetime import timedelta
from flask import Flask, request, jsonify
import time
# Load environment variables from .env file
load_dotenv()

# Set up llama API key from environment variables
meta_llama_url = os.getenv("META_LLAMA_URL")
# Azure DevOps Organization and Project details from environment variables
organization_url = os.getenv("AZURE_ORG_URL")
personal_access_token = os.getenv("AZURE_PAT")
project_name = os.getenv("PROJECT_NAME")
repository_id = os.getenv("REPO_ID")
max_tokens = os.getenv("MAX_TOKENS")
model_version = os.getenv("MODEL_VERSION")
run_interval_hours = os.getenv("INTERVAL_HOURS")
flask_port = os.getenv("FLASK_PORT")
# List of authors to ignore
IGNORED_AUTHORS = os.getenv("IGNORED_AUTHORS", "NONE").split(",")



app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    get_pull_requests()
    
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
    prompt +=diff
    client = LlamaStackClient(
    base_url=meta_llama_url,)
    response = client.inference.chat_completion(
    messages=[
        UserMessage(
            content=prompt,
            role="user",
        ),
    ],
    model=model_version,
    stream=False,
)
    return   response.choices[0].message['content']



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

# Fetch the diff content of a pull request
def fetch_pr_diff(pr_id):
    try:
        # Establish connection and get the Git client
        connection = get_azure_devops_connection()
        git_client = connection.clients.get_git_client()
        
        # Retrieve pull request iterations
        iterations = git_client.get_pull_request_iterations(
            repository_id=repository_id,
            project=project_name,
            pull_request_id=pr_id
        )
        
        # Get the latest iteration
        latest_iteration = max(iterations, key=lambda x: x.id)
        
        # Fetch changes for the latest iteration
        iteration_changes = git_client.get_pull_request_iteration_changes(
            repository_id=repository_id,
            project=project_name,
            pull_request_id=pr_id,
            iteration_id=latest_iteration.id
        )
        
        # Initialize the diff content
        diff_content = ""
        
        # Loop through the changes to extract diffs for each file
        for change in iteration_changes.change_entries:
            if change.additional_properties['item'] is not None:  # Only process items with valid file information
                change = change.additional_properties['item']
                file_path = change['path']
                
                # Check the change type (e.g., modified, added, deleted)
                change_type = iteration_changes.change_entries[0].additional_properties['changeType']
                
                # Process modified files
                if change_type in ['edit', 'add']:
                    # Fetch the file content of the latest version
                    file_content = git_client.get_item_content(
                        repository_id=repository_id,
                        project=project_name,
                        path=file_path
                    )
                    file_content_ = ''.join(chunk.decode('utf-8') for chunk in file_content)
                    # Add file details to the diff content
                    diff_content += f"File: {file_path}\n"
                    diff_content += f"Change Type: {change_type}\n"
                    diff_content += f"Content:\n{file_content_}\n\n"
                elif change_type == 'delete':
                    # If the file is deleted, just log the deletion
                    diff_content += f"File: {file_path}\n"
                    diff_content += f"Change Type: {change_type}\n"
                    diff_content += "Content: File deleted.\n\n"

        return diff_content

    except Exception as e:
        print(f"Error fetching PR diff: {e}")
        return None

# Main function to fetch PRs and review them
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
        app.run(port=flask_port)
    
    except Exception as e:
        print(f"An error occurred while reviewing pull requests: {str(e)}")
