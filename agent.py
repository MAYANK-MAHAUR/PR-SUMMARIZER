import os
import logging
import requests
from urllib.parse import urlparse
from dotenv import load_dotenv
from sentient_agent_framework import AbstractAgent, DefaultServer, ResponseHandler, Session, Query
from typing import AsyncIterator


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


load_dotenv()
FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

if not FIREWORKS_API_KEY or not GITHUB_TOKEN:
    logger.error("Missing FIREWORKS_API_KEY or GITHUB_TOKEN")
    raise ValueError("Missing environment variables")

def parse_pr_url(pr_url):
    parsed = urlparse(pr_url)
    if parsed.hostname != 'github.com':
        raise ValueError("Invalid GitHub URL")
    path_parts = parsed.path.strip('/').split('/')
    if len(path_parts) != 4 or path_parts[2] != 'pull':
        raise ValueError("URL must be a GitHub Pull Request URL")
    owner, repo, _, pull_number = path_parts
    return owner, repo, pull_number

def fetch_pr_diff(owner, repo, pull_number):
    logger.info(f"Fetching diff for {owner}/{repo}/pull/{pull_number}")
    headers = {'Accept': 'application/vnd.github.v3.diff', 'Authorization': f'token {GITHUB_TOKEN}'}
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

async def summarize_diff_with_dobby(diff_text):
    logger.info("Summarizing diff with Fireworks API")
    url = "https://api.fireworks.ai/inference/v1/chat/completions"
    headers = {"Accept": "application/json", "Content-Type": "application/json", "Authorization": f"Bearer {FIREWORKS_API_KEY}"}
    chunks = chunk_diff(diff_text, max_chunk_size=50000)
    async def stream_summaries():
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing chunk {i}/{len(chunks)}")
            prompt = f"Summarize this code diff chunk ({i}/{len(chunks)}): {chunk}\nHighlight key changes, potential risks, and improvements."
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
                yield f"**Chunk {i} Summary**:\n{summary}\n\n"
            except Exception as e:
                logger.error(f"Error summarizing chunk {i}: {str(e)}")
                yield f"**Chunk {i} Summary**: Error processing chunk\n\n"
    return stream_summaries()

class PRSummarizerAgent(AbstractAgent):
    def __init__(self, name: str):
        super().__init__(name)

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler):
        logger.info(f"Received query: {query.prompt}")
        try:
            await response_handler.emit_text_block("START", "Processing PR URL...")
            owner, repo, pull_number = parse_pr_url(query.prompt)
            await response_handler.emit_text_block("FETCH", f"Fetching diff for {owner}/{repo}/pull/{pull_number}")
            diff_text = fetch_pr_diff(owner, repo, pull_number)
            await response_handler.emit_text_block("SUMMARIZE", "Generating summary...")
            final_response_stream = response_handler.create_text_stream("SUMMARY")
            async for chunk in await summarize_diff_with_dobby(diff_text):
                await final_response_stream.emit_chunk(chunk)
            await final_response_stream.complete()
            await response_handler.complete()
        except Exception as e:
            logger.error(f"Error in assist: {str(e)}")
            await response_handler.emit_error("ERROR", {"message": str(e)})
            await response_handler.complete()

if __name__ == "__main__":
    agent = PRSummarizerAgent(name="PR Summarizer")
    server = DefaultServer(agent)
    server.run()
