import os
import hmac
import hashlib
import logging
from flask import Flask, request, jsonify
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv


load_dotenv()


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")


def verify_signature(payload, signature):
    if not GITHUB_WEBHOOK_SECRET:
        logger.info("No webhook secret set, skipping signature verification")
        return True
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()
    is_valid = hmac.compare_digest(expected_signature, signature)
    logger.debug(f"Signature verification: expected={expected_signature}, received={signature}, valid={is_valid}")
    return is_valid

def fetch_pr_diff(owner, repo, pull_number):
    logger.info(f"Fetching diff for {owner}/{repo}/pull/{pull_number}")
    headers = {
        'Accept': 'application/vnd.github.v3.diff',
        'Authorization': f'token {GITHUB_TOKEN}',
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    diff_text = response.text
    logger.debug(f"Diff fetched, length={len(diff_text)}")
    return diff_text

def chunk_diff(diff_text, max_chunk_size=50000):
    logger.info(f"Chunking diff of length {len(diff_text)}")
    chunks = []
    current_chunk = ""
    lines = diff_text.splitlines()
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)
    logger.debug(f"Created {len(chunks)} chunks")
    return chunks

def summarize_diff_with_dobby(diff_text):
    url = "https://api.fireworks.ai/inference/v1/chat/completions"
    headers = {"Authorization": f"Bearer {FIREWORKS_API_KEY}", "Content-Type": "application/json"}
    prompt = f"""**Role:** You are an expert software engineer and code reviewer.
**Context:** Your task is to provide a comprehensive and concise summary of a GitHub Pull Request. The changes are presented as a unified diff.
**Goal:** Your summary should help another developer quickly understand the purpose, scope, and impact of the changes.

**Summary Requirements:**
1.  **Title:** A one-sentence, high-level summary of the PR's purpose.
2.  **Key Changes:** A bulleted list detailing the most important code modifications. Focus on new features, bug fixes, refactoring, or performance improvements.
3.  **Potential Risks/Side Effects:** A bulleted list of any potential issues, such as breaking changes, security vulnerabilities, or performance regressions. If none exist, state "None identified."
4.  **Testing/Verification:** A short paragraph or bulleted list explaining how to test or verify that the changes work as intended.
5.  **Files Changed:** A concise summary of the most impacted files and their purpose within this PR.

**Instructions:**
-   Analyze the provided diff carefully.
-   Be concise and use clear, professional language.
-   Organize your response using the headings provided in the "Summary Requirements" section.
-   Output your final summary in markdown format.

---
**DIFF:**
{diff_text}"""
---  data = {
        "model": "accounts/sentientfoundation/models/dobby-unhinged-llama-3-3-70b-new",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['choices'][0]['message']['content']


def post_comment_to_pr(owner, repo, pull_number, comment):
    logger.info(f"Posting comment to {owner}/{repo}/pull/{pull_number}")
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pull_number}/comments"
    data = {'body': comment}
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    logger.debug("Comment posted successfully")

@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("Received webhook request")
    signature = request.headers.get('X-Hub-Signature-256')
    if not verify_signature(request.data, signature):
        logger.error("Signature verification failed")
        return jsonify({'error': 'Signature mismatch'}), 403
    
    event = request.headers.get('X-GitHub-Event')
    logger.debug(f"Event type: {event}")
    if event != 'pull_request':
        logger.info("Ignored non-pull_request event")
        return jsonify({'message': 'Ignored event'}), 200
    
    payload = request.json
    action = payload.get('action')
    logger.debug(f"Action: {action}")
    if action not in ['opened', 'synchronize', 'reopened']:
        logger.info(f"Ignored action: {action}")
        return jsonify({'message': 'Ignored action'}), 200
    
    pr = payload.get('pull_request')
    owner = pr['base']['repo']['owner']['login']
    repo = pr['base']['repo']['name']
    pull_number = pr['number']
    logger.info(f"Processing PR {owner}/{repo}/{pull_number}")
    
    try:
        diff_text = fetch_pr_diff(owner, repo, pull_number)
        summary = summarize_diff_with_dobby(diff_text)
        comment = f"**PR Summary by Dobby-70**:\n\n{summary}"
        post_comment_to_pr(owner, repo, pull_number, comment)
        logger.info("Webhook processed successfully")
        return jsonify({'message': 'Summary posted'}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000)) 
    app.run(host='0.0.0.0', port=port)
