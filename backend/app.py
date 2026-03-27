from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from github_routes import github_bp
from anthropic import Anthropic
from database import engine, get_db
from models import Submission, Base
from dotenv import load_dotenv
from functools import wraps
import requests
import base64
import re
import os
import time

load_dotenv()

# ── GitHub token validation cache ─────────────────────────────────────────────
_token_cache = {}  # token -> (is_valid, timestamp)
TOKEN_CACHE_TTL = 300  # 5 minutes

def _validate_github_token(token):
    now = time.time()
    if token in _token_cache:
        valid, ts = _token_cache[token]
        if now - ts < TOKEN_CACHE_TTL:
            return valid
    resp = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=5,
    )
    valid = resp.status_code == 200
    _token_cache[token] = (valid, now)
    return valid

def require_github_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        if not token or not _validate_github_token(token):
            return jsonify({"error": "GitHub authentication required. Please sign in with GitHub."}), 401
        return f(*args, **kwargs)
    return decorated

app = Flask(__name__)
CORS(app, supports_credentials=True, origins=[
    "http://localhost:3000",
    os.getenv("FRONTEND_URL", "")
], allow_headers=["Content-Type", "Authorization", "X-Api-Key"])

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["10 per hour"]
)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.register_blueprint(github_bp)
Base.metadata.create_all(bind=engine)

def get_anthropic_client():
    user_key = request.headers.get("X-Api-Key", "").strip()
    if not user_key:
        return None, (jsonify({"error": "No Anthropic API key provided. Add your key in the settings panel."}), 402)
    try:
        return Anthropic(api_key=user_key), None
    except Exception:
        return None, (jsonify({"error": "Invalid Anthropic API key."}), 402)

@app.errorhandler(Exception)
def handle_exception(e):
    # Check if it looks like an Anthropic auth error
    msg = str(e)
    if "401" in msg or "auth" in msg.lower() or "api_key" in msg.lower() or "authentication" in msg.lower():
        return jsonify({"error": "Invalid or revoked Anthropic API key. Please enter a valid key."}), 402
    return jsonify({"error": "An unexpected error occurred on the server."}), 500

def sanitize_ai_section(text):
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = re.sub(r"(?im)^\s*(i\s+am\s+thinking|nevermind|never\s+mind|oops|sorry)\b.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    return cleaned.strip()

@app.route("/review", methods=["POST"])
@limiter.limit("10 per hour")
@require_github_auth
def review_code():
    data = request.get_json()
    code = data.get("code")
    language = data.get("language", "unknown")

    if not code:
        return jsonify({"error": "No code provided"}), 400

    if len(code) > 5000:
        return jsonify({"error": "Code exceeds 5000 character limit."}), 400

    client, err = get_anthropic_client()
    if err:
        return err

    db = next(get_db())

    # Check cache first
    existing = db.query(Submission).filter(Submission.code == code).first()
    if existing and existing.score is not None:
        return jsonify({
            "id": existing.id,
            "explanation": existing.explanation,
            "bugs": existing.bugs,
            "suggestions": existing.suggestions,
            "complexity": existing.complexity,
            "security": existing.security,
            "score": existing.score,
            "score_reasoning": existing.score_reasoning,
            "language": existing.language,
            "cached": True
        })

    submission = Submission(code=code, language=language)
    db.add(submission)
    db.commit()
    db.refresh(submission)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system="""You are a senior software engineer with 15+ years of experience. You review code with precision and directness. Be concise — every word must earn its place. No padding, no repetition.""",
        messages=[
            {
                "role": "user",
                "content": f"""Review this {language} code. Be concise and direct in every section.

Respond in exactly this format:

EXPLANATION:
2-4 sentences on what this code does and what problem it solves.

BUGS:
Numbered list. For each bug: what it is, what breaks at runtime, and the fix. If none: None found.

SUGGESTIONS:
Numbered list of the top improvements only. Each suggestion: one sentence on why it matters, one code example.

COMPLEXITY:
Big O time and space. One sentence per function if multiple exist.

SECURITY:
Key vulnerabilities only. If none: No security issues found.

SCORE:
Single integer 0-100.

SCORE_REASONING:
3-5 sentences covering correctness, security, performance, readability, and best practices.

Be specific. A developer should be able to read this and know exactly what they need to 
fix to raise their score.

Here is the code to review:
````{language}
{code}
```"""
            }
        ]
    )

    response_text = message.content[0].text
    sections = {}
    current_section = None
    current_content = []

    for line in response_text.split("\n"):
        matched = False
        for header, key in [
            ("EXPLANATION:", "explanation"), ("BUGS:", "bugs"),
            ("SUGGESTIONS:", "suggestions"), ("COMPLEXITY:", "complexity"),
            ("SECURITY:", "security"), ("SCORE_REASONING:", "score_reasoning"),
            ("SCORE:", "score"),
        ]:
            if line.startswith(header):
                current_section = key
                inline = line[len(header):].strip()
                current_content = [inline] if inline else []
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                matched = True
                break
        if not matched and current_section:
            current_content.append(line)
            sections[current_section] = "\n".join(current_content).strip()

    explanation = sanitize_ai_section(sections.get("explanation", ""))
    bugs = sanitize_ai_section(sections.get("bugs", ""))
    suggestions = sanitize_ai_section(sections.get("suggestions", ""))
    complexity = sanitize_ai_section(sections.get("complexity", ""))
    security = sanitize_ai_section(sections.get("security", ""))
    score_text = sanitize_ai_section(sections.get("score", "0"))
    score_reasoning = sanitize_ai_section(sections.get("score_reasoning", ""))
    score_match = re.search(r'\b(\d{1,3})\b', score_text)
    score = int(score_match.group(1)) if score_match else 0

    submission.explanation = explanation
    submission.bugs = bugs
    submission.suggestions = suggestions
    submission.complexity = complexity
    submission.security = security
    submission.score = score
    submission.score_reasoning = score_reasoning
    db.commit()

    return jsonify({
        "id": submission.id,
        "explanation": explanation,
        "bugs": bugs,
        "suggestions": suggestions,
        "complexity": complexity,
        "security": security,
        "score": score,
        "score_reasoning": score_reasoning,
        "language": language
    })

@app.route("/github/explain-repo", methods=["POST"])
@require_github_auth
def explain_repo():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    data = request.get_json()
    owner = data.get("owner")
    repo = data.get("repo")
    if not owner or not repo:
        return jsonify({"error": "owner and repo are required"}), 400

    SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".next", "vendor"}
    SOURCE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".rb"}

    tree_response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    )
    tree_data = tree_response.json()
    tree = tree_data.get("tree", [])

    candidate_files = [
        item for item in tree
        if item["type"] == "blob"
        and not any(part in SKIP_DIRS for part in item["path"].split("/"))
        and any(item["path"].endswith(ext) for ext in SOURCE_EXTS)
        and item.get("size", 0) < 50000
    ]
    candidate_files.sort(key=lambda x: (x["path"].count("/"), x["path"]))
    candidate_files = candidate_files[:8]

    file_sections = []
    for f in candidate_files:
        file_res = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{f['path']}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        )
        fdata = file_res.json()
        if "content" in fdata:
            content = base64.b64decode(fdata["content"]).decode("utf-8", errors="replace")
            file_sections.append(f"### {f['path']}\n```\n{content[:2000]}\n```")

    if not file_sections:
        return jsonify({"error": "No readable source files found"}), 400

    combined = "\n\n".join(file_sections)

    client, err = get_anthropic_client()
    if err:
        return err

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""You are a senior software architect. Analyze these source files from the GitHub repo {owner}/{repo} and provide an architecture summary.

Respond in exactly this format:

SUMMARY:
A 2-4 sentence plain-English description of what this codebase does and its primary purpose.

ARCHITECTURE:
A breakdown of the key components, how they fit together, and the overall design pattern used.

TECH_STACK:
A list of the primary languages, frameworks, and libraries detected.

ENTRY_POINTS:
The main entry points or key files a new developer should read first.

Here are the files:

{combined}"""
        }]
    )

    response_text = message.content[0].text
    sections = {}
    current_section = None
    current_content = []

    for line in response_text.split("\n"):
        matched = False
        for header, key in [
            ("SUMMARY:", "summary"), ("ARCHITECTURE:", "architecture"),
            ("TECH_STACK:", "tech_stack"), ("ENTRY_POINTS:", "entry_points"),
        ]:
            if line.startswith(header):
                current_section = key
                inline = line[len(header):].strip()
                current_content = [inline] if inline else []
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                matched = True
                break
        if not matched and current_section:
            current_content.append(line)
            sections[current_section] = "\n".join(current_content).strip()

    return jsonify({
        "summary": sanitize_ai_section(sections.get("summary", "")),
        "architecture": sanitize_ai_section(sections.get("architecture", "")),
        "tech_stack": sanitize_ai_section(sections.get("tech_stack", "")),
        "entry_points": sanitize_ai_section(sections.get("entry_points", "")),
    })


@app.route("/github/explain-file", methods=["POST"])
@require_github_auth
def explain_file():
    client, err = get_anthropic_client()
    if err:
        return err

    data = request.get_json()
    content = data.get("content", "")
    filename = data.get("filename", "unknown")

    if not content:
        return jsonify({"error": "No content provided"}), 400

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""You are a senior software engineer with 15+ years of experience across systems design, architecture, and multiple languages. Analyze this file thoroughly.

Respond in exactly this format with no deviations:

SUMMARY:
A direct, technical explanation of what this file does and why it exists. Explain it the way you would during a code walkthrough with another engineer — what is its responsibility, what does it own, and what would break if it were removed.

TECH:
Every language, framework, library, and external dependency imported or referenced in this file. For each one, state exactly what it is used for in this specific file. Be specific — not just "React" but "React hooks (useState, useEffect) for managing component-level state and side effects."

CONCEPTS:
The key programming concepts, design patterns, and architectural decisions at work in this file. Examples: dependency injection, event-driven design, memoization, middleware pattern, singleton, etc. For each concept, explain concretely where and how it appears in this file.

PURPOSE:
From your perspective as a senior engineer, explain the design decisions behind this file. What problem is it solving? What tradeoffs were made? How does it fit into the broader system? What would you flag for a junior engineer reading this for the first time?

Filename: {filename}

```
{content[:4000]}
```"""
        }]
    )

    response_text = message.content[0].text
    sections = {}
    current_section = None
    current_content = []

    for line in response_text.split("\n"):
        matched = False
        # Strip leading markdown (**, ##, __, spaces) before header matching
        normalized = re.sub(r'^[\s*#_`]+', '', line).strip()
        for header, key in [
            ("SUMMARY:", "summary"), ("TECH:", "tech"),
            ("CONCEPTS:", "concepts"), ("PURPOSE:", "purpose"),
        ]:
            if normalized.upper().startswith(header):
                current_section = key
                inline = normalized[len(header):].strip()
                current_content = [inline] if inline else []
                if current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                matched = True
                break
        if not matched and current_section:
            current_content.append(line)
            sections[current_section] = "\n".join(current_content).strip()

    return jsonify({
        "summary": sanitize_ai_section(sections.get("summary", "")),
        "tech": sanitize_ai_section(sections.get("tech", "")),
        "concepts": sanitize_ai_section(sections.get("concepts", "")),
        "purpose": sanitize_ai_section(sections.get("purpose", "")),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)