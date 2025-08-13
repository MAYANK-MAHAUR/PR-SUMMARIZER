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
    logger.info("Summarizing diff with Dobby")
    url = "https://api.fireworks.ai/inference/v1/chat/completions"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {FIREWORKS_API_KEY}",
    }
    
    chunks = chunk_diff(diff_text, max_chunk_size=50000)
    summaries = []
    for i, chunk in enumerate(chunks, 1):
        logger.info(f"Processing chunk {i}/{len(chunks)}")
        prompt = f"""Summarize this code diff chunk ({i}/{len(chunks)}): {chunk}
        You are a PR review agent for flows.network v1.0.
        Your job is to review all commits in a Pull Request and provide a professional, factual, and risk-aware summary.
        
        Rules:
        
        Format exactly as in the example — no extra commentary or slang.
        
        For each commit:
        
        Show commit hash (12 chars) after “Commit”.
        
        Add Summary of Key Changes:.
        
        Use bold section titles (Feature Updates, Bug Fixes, Documentation, Refactoring, Dependencies, etc.).
        
        Clearly explain what changed and why it matters.
        
        Risk Analysis Before Final Verdict:
        
        If code removes files, functions, or dependencies without replacement or refactor → High risk.
        
        If code changes core logic without tests → Medium risk.
        
        If code only updates docs, formatting, or non-critical features → Low risk.
        
        Final Verdict:
        
        ✅ Final Verdict: This PR works as intended and is a good merge candidate. (Low risk, tested changes)
        
        ⚠️ Final Verdict: This PR may need further testing or revisions before merging. (Medium risk)
        
        ❌ Final Verdict: This PR may break existing code and should be revised before merging. (High risk)
        
        Maintain a formal, objective tone — no jokes, casual phrases, or guesses without evidence.

        Example Output:
        Hello, I am a PR summary agent on flows.network v1.0. Here are my reviews of code commits in this PR.  
        
        Commit 6f56c42d5926  
        Summary of Key Changes:  
        **Documentation:**  
        - Deleted `USE_CASES.md`, removing user guidance on use cases. No replacement provided.  
        
        **Code Maintenance:**  
        - Removed `requests` import from `gui_extractor.py`. This could break functionality if the library is still referenced elsewhere.  
        
        ⚠️ Final Verdict: This PR may need further testing or revisions before merging. 
                """
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
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            summary = response.json()['choices'][0]['message']['content']
            summaries.append(f"**Chunk {i} Summary**:\n{summary}")
        except Exception as e:
            logger.error(f"Error summarizing chunk {i}: {str(e)}")
            summaries.append(f"**Chunk {i} Summary**: Error processing chunk")
    combined_summary = "\n\n".join(summaries)
    logger.info("Combined summary generated")
    return combined_summary

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
