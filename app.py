import os
import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
import requests
from urllib.parse import urlparse
import os 
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

if not FIREWORKS_API_KEY or not GITHUB_TOKEN:
    logger.error("Missing required environment variables: FIREWORKS_API_KEY or GITHUB_TOKEN")
    raise ValueError("Missing required environment variables")

def verify_signature(payload, signature):
    """Verify GitHub webhook signature."""
    if not GITHUB_WEBHOOK_SECRET:
        logger.info("No webhook secret set, skipping signature verification")
        return True
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), msg=payload, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()
    is_valid = hmac.compare_digest(expected_signature, signature)
    logger.debug(f"Signature verification: expected={expected_signature}, received={signature}, valid={is_valid}")
    return is_valid

def fetch_pr_diff(owner, repo, pull_number):
    """Fetch the diff of a GitHub PR."""
    logger.info(f"Fetching diff for {owner}/{repo}/pull/{pull_number}")
    headers = {
        'Accept': 'application/vnd.github.v3.diff',
        'Authorization': f'token {GITHUB_TOKEN}',
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    logger.debug(f"Diff fetched, length={len(response.text)}")
    return response.text

def summarize_diff_with_dobby(diff_text):
    """Use Dobby-70 via Fireworks AI to summarize the diff."""
    logger.info("Sending diff to Fireworks API for summarization")
    url = "https://api.fireworks.ai/inference/v1/chat/completions"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
    }
    if len(diff_text) > 100000:
        logger.warning("Diff too large, truncating to 100,000 characters")
        diff_text = diff_text[:100000] + "\n... (truncated)"
    
    prompt = f"Summarize this code diff: {diff_text}\nHighlight key changes, potential risks, and improvements."
    
    data = {
        "model": "accounts/sentientfoundation/models/dobby-unhinged-llama-3-3-70b-new",
        "max_tokens": 1024,
        "top_p": 1,
        "top_k": 40,
        "presence_penalty": 0,
        "frequency_penalty": 0,
        "temperature": 0.6,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    summary = response.json()['choices'][0]['message']['content']
    logger.info("Summary generated successfully")
    return summary

def post_comment_to_pr(owner, repo, pull_number, comment):
    """Post a comment to the GitHub PR."""
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
        comment = f"**PR Summary by Dobby-70:**\n\n{summary}"
        post_comment_to_pr(owner, repo, pull_number, comment)
        logger.info("Webhook processed successfully")
        return jsonify({'message': 'Summary posted'}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)