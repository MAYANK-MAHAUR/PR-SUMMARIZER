# GitHub PR Summarizer ✨

A slick tool that auto-summarizes GitHub pull requests using **@SentientAGI’s Dobby-70 AI** 🤖. It features a Flask webhook for automatic PR comments and Sentient Dobby model for on-demand summaries. Built to streamline code reviews with smart insights! 🚀

---

## Features

* **Webhook**: Automatically posts PR summaries as GitHub comments via a Flask server on Render. 💬

* **Structured Summaries**: Highlights what was **added**, **deleted**, **modified**, plus potential **risks** and **improvements** in markdown format. ✅

* **Powered by Dobby-70**: Leverages Sentient’s AI for concise, insightful summaries. 🧠

---

## Example

GO Check out https://github.com/MAYANK-MAHAUR/GAIA-AI-DATA-EXTRACTOR/pull/6#issuecomment-3182939694 in `MAYANK-MAHAUR/GAIA-AI-DATA-EXTRACTOR`, the summary looks like:


**PR Summary by Dobby-70**:

Hello, I am the PR Summary Agent!

* **Summary**
* **Key Changes**
* **Potential risks**
* **Verification**
* **Files Changed**

---

## How It Works

### Webhook (`app.py`):

* Listens for GitHub PR events at `https://pr-summarizer.onrender.com/webhook`.

* Fetches PR diffs via GitHub API.

* Summarizes diffs using Dobby-70.

* Posts markdown summaries as PR comments.

## Tech Stack

* **Frameworks**: Flask, gunicorn, `requests`, `python-dotenv`, `sentient-agent-framework` (v0.3.0).

* **APIs**: GitHub API for diffs, Fireworks API for Dobby-70.

* **Deployment**: Render.

---

## Setup

### Prerequisites

* Python 3.10+

* GitHub account with a personal access token (`repo` scope)

* Fireworks AI API key

* Render account (for webhook deployment)

* **Optional**: Sentient Chat access (`chat.sentient.xyz`)

### Installation

Clone the repo:
```bash
git clone https://github.com/MAYANK-MAHAUR/pr-summarizer.git
cd pr-summarizer
```
Install dependencies:
```bash
pip install -r requirements.txt
```
Create `.env` file:
```plaintext
FIREWORKS_API_KEY=your_fireworks_key
GITHUB_TOKEN=your_token_with_repo_scope
GITHUB_WEBHOOK_SECRET=your_secret
```

### Webhook Deployment (Render)

1. Create a new Web Service on Render (Free tier, Python 3).

2. Set up the following configuration:

   * **Repository**: `MAYANK-MAHAUR/pr-summarizer`

   * **Build Command**: `pip install -r requirements.txt`

   * **Start Command**: `gunicorn app:app`

3. Add the following **Environment Variables**:
   ```plaintext
   FIREWORKS_API_KEY=your_key
   GITHUB_TOKEN=your_token_with_repo_scope
   GITHUB_WEBHOOK_SECRET=your_secret
   PYTHON_VERSION=3.10.7
   ```

4. Configure the **Webhook URL** in your GitHub repository:

   * Go to your repo's **Settings > Webhooks > Add webhook**.

   * **Payload URL**: `https://pr-summarizer.onrender.com/webhook`

   * **Content Type**: `application/json`

   * **Secret**: Match the value of `GITHUB_WEBHOOK_SECRET` in your Render environment variables.

   * **Events**: Select **"Pull requests"**.

---

## Testing

### Webhook

* Create a PR in your configured GitHub repository (e.g., `MAYANK-MAHAUR/GAIA-AI-DATA-EXTRACTOR`) and check for a "PR Summary by Dobby-70" comment.


---

## Credits
-   Built with **Sentient’s Dobby-70** and **Sentient Agent Framework** (v0.3.0).
-   Powered by **Fireworks AI** and **GitHub API**.
-   Deployed on **Render**.

---

## Contributing
-   Fork, star, or submit PRs to `MAYANK-MAHAUR/pr-summarizer`. Let’s make code reviews smarter! 🤝
