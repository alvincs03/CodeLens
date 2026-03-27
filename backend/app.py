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
])

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
        model="claude-opus-4-5",
        max_tokens=4096,
        system="""You are a senior software engineer with 15+ years of experience across systems design, 
security, performance optimization, and clean code principles. You have conducted thousands of code reviews 
at top-tier tech companies. Your job is not just to find bugs. It is to teach the developer why something 
is wrong, what the consequences are if left unfixed, and exactly how to fix it. You are direct, precise, 
and educational. You do not sugarcoat issues. You treat the developer as someone who is capable of 
understanding the truth about their code.""",
        messages=[
            {
                "role": "user",
                "content": f"""Review the following {language} code with the thoroughness of a senior engineer 
preparing it for a production deployment at a high-scale company.

Respond in exactly this format with no deviations:

EXPLANATION:
A thorough plain-English explanation of what this code does, how it works step by step, 
and what problem it is trying to solve. Explain it as if the developer who wrote it 
needs to be able to defend every line in a technical interview.

BUGS:
A numbered list of every bug, logic error, edge case failure, and security vulnerability 
you find. For each one:
- Describe exactly what the bug is
- Explain what will happen at runtime if it is not fixed
- Show the corrected code snippet

If no bugs are found, write: None found.

SUGGESTIONS:
A numbered list of concrete improvements covering:
- Code readability and maintainability
- Performance optimizations
- Better design patterns or architectural choices
- Error handling gaps
- Any violation of language-specific best practices
For each suggestion, explain why it matters and show an example of the improvement.

COMPLEXITY:
Rate the time and space complexity of the code using Big O notation. 
Explain your reasoning. If multiple functions exist, break down each one.

SECURITY:
A dedicated section for any security vulnerabilities beyond basic bugs. Cover:
- Injection risks
- Authentication or authorization flaws
- Data exposure risks
- Any OWASP Top 10 violations
If none, write: No security issues found.

SCORE:
A single integer from 0 to 100 representing overall production readiness.
Use this scale:
0-40: Not ready, fundamental issues
41-60: Needs significant work
61-80: Good foundation, improvements needed
81-95: Near production ready
96-100: Exceptional code

SCORE_REASONING:
A detailed breakdown of exactly why the code received this score. Reference specific 
issues you found in the previous sections. Weight your reasoning across these dimensions:
- Correctness (does it actually work): 30%
- Security (is it safe to deploy): 25%
- Performance (is it efficient): 20%
- Readability (can another engineer maintain it): 15%
- Best practices (does it follow language conventions): 10%

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
        model="claude-opus-4-5",
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)