

![alt text](https://i.ibb.co/3BSTZBJ/IMG-7647.png)

## AI-Powered Pull Request Reviewer 🚀

PullPal combines the capabilities of OpenAI/Meta-LLama 🧠 and Azure DevOps ⚙️ to automate the review process for pull requests.
when triggred by webhook Pullpal fetches active pull requests from Azure DevOps, analyzes the code changes using OpenAI's specified model or Meta-llama,
and posts the review comments directly on the pull request threads.
## Available Branch 
- main - for OpenAI intergration
- Meta-llama - for Meta-llama intergration

How to Use:

## Set up Environment Variables:

Create a .env file in the project root.
## Add the following environment variables:
OPENAI_API_KEY: Your OpenAI API key. (main branch)

META_LLAMA_URL: your meta_llama_url. (meta_llama branch)

AZURE_ORG_URL: Your Azure DevOps organization URL.

AZURE_PAT: Your Azure DevOps Personal Access Token.

PROJECT_NAME: Your Azure DevOps project name.

REPO_ID: Your Azure DevOps repository ID.

IGNORED_AUTHORS: A comma-separated list of authors to ignore.

IGNORED_FILE_TYPES: List of igonred file types to avoid review.

LOG_PATH: Log path.

LOG_LEVEL: Requested log level for logging.

PRINT_TO_CONSOLE: BOOLEAN eithr print or not to the console.

## Run the Script 🏃‍♂️

# To run the PullPal bot using Docker 🐋:

1. **Build the Docker Image 🛠️:**
```sh
   docker build -t pullpal-bot .
   ```
2.**Run the Docker Container 🐋:**
```sh
docker run -d --env-file .env pullpal-bot
```
# To run Pullpal locally 💻:

1.Create a a virtual env,
```sh
python3 -m venv venv
```
2.Activate the virtual environment:

Linux:
```sh
source venv/bin/activate
```
Windows:
```sh
call venv\Scripts\activate
```
3. Install Dependencies:
```sh
pip install -r requirements.txt
```
4.Run Pullpal
```sh
python pullpal.py
```

# Customization:

check .env file for customization,prompt is hardcoded but fill free to adjust



 ## Feel free to fork the repository, make changes, and submit a pull request - issues are available !

MIT License
