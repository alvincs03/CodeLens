from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from github_routes import github_bp, get_bearer_token
from anthropic import Anthropic, APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from database import engine, get_db
from models import Submission, FileAnalysis, Base
from dotenv import load_dotenv
from functools import wraps
import requests
import base64
import re
import os
import time
import hashlib
import logging

load_dotenv()

# ── GitHub token validation cache ─────────────────────────────────────────────
_token_cache = {}
TOKEN_CACHE_TTL = 300

_result_cache = {}
RESULT_CACHE_TTL = 3600
CACHE_MAX_ENTRIES = 500
CACHE_KEY_VERSION = "v1"
_cache_metrics = {"hits": 0, "misses": 0, "sets": 0, "evictions": 0}
logger = logging.getLogger(__name__)
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
ANTHROPIC_TIMEOUT_SECONDS = float(os.getenv("ANTHROPIC_TIMEOUT_SECONDS", "120"))
ANTHROPIC_MAX_RETRIES = int(os.getenv("ANTHROPIC_MAX_RETRIES", "2"))
SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "java", "cpp", "go", "rust"}
MAX_CODE_CHARACTERS = 5000
MAX_FILE_CHARACTERS = 100000

def _make_cache_key(operation, *parts):
    content = "\0".join([operation, CACHE_KEY_VERSION, *parts])
    return hashlib.sha256(content.encode()).hexdigest()

def _log_cache_metrics(event):
    logger.info(
        "cache_event=%s hits=%s misses=%s sets=%s evictions=%s entries=%s",
        event,
        _cache_metrics["hits"],
        _cache_metrics["misses"],
        _cache_metrics["sets"],
        _cache_metrics["evictions"],
        len(_result_cache),
    )

def _result_cache_get(key):
    entry = _result_cache.get(key)
    if entry and (time.time() - entry[1]) < RESULT_CACHE_TTL:
        _cache_metrics["hits"] += 1
        _log_cache_metrics("hit")
        return entry[0]
    if entry:
        del _result_cache[key]
    _cache_metrics["misses"] += 1
    _log_cache_metrics("miss")
    return None

def _result_cache_set(key, value):
    if key not in _result_cache and len(_result_cache) >= CACHE_MAX_ENTRIES:
        oldest_key = min(_result_cache, key=lambda cache_key: _result_cache[cache_key][1])
        del _result_cache[oldest_key]
        _cache_metrics["evictions"] += 1
    _result_cache[key] = (value, time.time())
    _cache_metrics["sets"] += 1
    _log_cache_metrics("set")

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
        token = get_bearer_token()
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
        return Anthropic(
            api_key=user_key,
            timeout=ANTHROPIC_TIMEOUT_SECONDS,
            max_retries=ANTHROPIC_MAX_RETRIES,
        ), None
    except Exception:
        return None, (jsonify({"error": "Invalid Anthropic API key."}), 402)

@app.errorhandler(AuthenticationError)
def handle_anthropic_authentication_error(error):
    logger.warning("anthropic_authentication_failed error_type=%s", type(error).__name__)
    return jsonify({"error": "Invalid or revoked Anthropic API key. Please enter a valid key."}), 401

@app.errorhandler(RateLimitError)
def handle_anthropic_rate_limit(error):
    logger.warning("anthropic_rate_limited error_type=%s", type(error).__name__)
    return jsonify({"error": "Anthropic is rate limiting this key. Please retry shortly."}), 429

@app.errorhandler(APITimeoutError)
def handle_anthropic_timeout(error):
    logger.warning("anthropic_timeout error_type=%s", type(error).__name__)
    return jsonify({"error": "Anthropic did not respond before the timeout."}), 504

@app.errorhandler(APIConnectionError)
def handle_anthropic_connection_error(error):
    logger.warning("anthropic_connection_failed error_type=%s", type(error).__name__)
    return jsonify({"error": "Could not connect to Anthropic."}), 502

@app.errorhandler(APIStatusError)
def handle_anthropic_status_error(error):
    logger.warning("anthropic_request_failed status=%s", error.status_code)
    return jsonify({"error": "Anthropic could not complete the review."}), 502

@app.errorhandler(Exception)
def handle_exception(error):
    logger.exception("unhandled_server_error error_type=%s", type(error).__name__)
    return jsonify({"error": "An unexpected error occurred on the server."}), 500

def sanitize_ai_section(text):
    if not text:
        return ""
    cleaned = text.strip()
    cleaned = re.sub(r"(?im)^\s*(i\s+am\s+thinking|nevermind|never\s+mind|oops|sorry)\b.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    return cleaned.strip()

def parse_ai_sections(response_text, headers):
    sections = {}
    current_section = None
    current_content = []

    for line in response_text.splitlines():
        normalized_line = re.sub(r'^[\s*#_`]+', '', line).strip()
        matched_header = False

        for header, key in headers:
            if normalized_line.upper().startswith(header):
                current_section = key
                inline_content = normalized_line[len(header):].strip()
                inline_content = re.sub(r'^[\s*#_`]+', '', inline_content).strip()
                current_content = [inline_content] if inline_content else []
                sections[current_section] = "\n".join(current_content).strip()
                matched_header = True
                break

        if not matched_header and current_section:
            current_content.append(line)
            sections[current_section] = "\n".join(current_content).strip()

    return {key: sanitize_ai_section(value) for key, value in sections.items()}

@app.route("/review", methods=["POST"])
@limiter.limit("10 per hour")
@require_github_auth
def review_code():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    code = data.get("code")
    language = data.get("language", "unknown")

    if not isinstance(code, str) or not code.strip():
        return jsonify({"error": "No code provided"}), 400

    if len(code) > MAX_CODE_CHARACTERS:
        return jsonify({"error": f"Code exceeds {MAX_CODE_CHARACTERS} character limit."}), 400

    if language not in SUPPORTED_LANGUAGES:
        return jsonify({"error": "Unsupported programming language."}), 400

    client, err = get_anthropic_client()
    if err:
        return err

    code_hash = _make_cache_key("review", language, code)

    cached = _result_cache_get(code_hash)
    if cached:
        return jsonify({**cached, "cached": True})

    db = next(get_db())

    existing = db.query(Submission).filter(Submission.code == code).first()
    if existing and existing.score is not None:
        result = {
            "id": existing.id,
            "explanation": existing.explanation,
            "bugs": existing.bugs,
            "suggestions": existing.suggestions,
            "complexity": existing.complexity,
            "security": existing.security,
            "score": existing.score,
            "score_reasoning": existing.score_reasoning,
            "language": existing.language,
        }
        _result_cache_set(code_hash, result)
        return jsonify({**result, "cached": True})

    submission = Submission(code=code, language=language)
    db.add(submission)
    db.commit()
    db.refresh(submission)

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=4096,
        system="""You are a senior software engineer with 15+ years of experience across systems design,
security, performance optimization, and clean code principles. You have conducted thousands of code reviews
at top-tier tech companies. Your job is not just to find bugs — it is to teach the developer why something
is wrong, what the consequences are if left unfixed, and exactly how to fix it. You are direct, precise,
and educational. You do not sugarcoat issues. You treat the developer as someone capable of understanding
the truth about their code.

CRITICAL FORMATTING RULES — YOU MUST FOLLOW THESE EXACTLY:
1. Each section header must appear on its own line, in plain uppercase text, followed immediately by a colon. Example: EXPLANATION:
2. Do not use any markdown formatting on section headers. No bold (**EXPLANATION:**), no italic, no hashes (## EXPLANATION), no underscores. The header must be the raw word followed by a colon and nothing else on that line.
3. Do not add any text, preamble, or commentary before the first section header.
4. Do not skip any section. All seven sections are required in every response.
5. The section order must be exactly: EXPLANATION, BUGS, SUGGESTIONS, COMPLEXITY, SECURITY, SCORE, SCORE_REASONING.""",
        messages=[
            {
                "role": "user",
                "content": f"""Review the following {language} code with the thoroughness of a senior engineer preparing it for a production deployment at a high-scale company.

Your response must use this exact structure. Each header must be a plain uppercase word followed by a colon on its own line — no bold, no markdown, no hashes, no extra formatting of any kind on the header line itself.

EXPLANATION:
Write a thorough plain-English explanation of what this code does, how it works step by step, and what problem it is trying to solve. Explain it as if the developer who wrote it needs to be able to defend every line in a technical interview. Cover the inputs, outputs, control flow, and any important state changes.

BUGS:
Write a numbered list of every bug, logic error, edge case failure, and security vulnerability you find. For each one, describe exactly what the bug is, explain what will happen at runtime if it is not fixed, and show the corrected code snippet. If no bugs are found, write: None found.

SUGGESTIONS:
Write a numbered list of concrete improvements covering code readability and maintainability, performance optimizations, better design patterns or architectural choices, error handling gaps, and any violation of language-specific best practices. For each suggestion explain why it matters and show an example of the improvement.

COMPLEXITY:
Rate the time and space complexity of the code using Big O notation. Explain your reasoning in detail. If multiple functions exist, break down each one individually.

SECURITY:
Write a dedicated analysis of any security vulnerabilities beyond the basic bugs already listed. Cover injection risks, authentication or authorization flaws, data exposure risks, and any OWASP Top 10 violations. If none exist, write: No security issues found.

SCORE:
Write a single integer from 0 to 100 representing overall production readiness. Use this scale: 0-40 means not ready with fundamental issues, 41-60 means needs significant work, 61-80 means good foundation with improvements needed, 81-95 means near production ready, 96-100 means exceptional code.

SCORE_REASONING:
Write a detailed breakdown of exactly why the code received this score. Reference specific issues found in the previous sections. Weight your reasoning across these dimensions: Correctness which counts for 30 percent, Security which counts for 25 percent, Performance which counts for 20 percent, Readability which counts for 15 percent, and Best practices which counts for 10 percent. Be specific enough that the developer knows exactly what to fix to raise their score.

Here is the code to review:
```{language}
{code}
```"""
            }
        ]
    )

    response_text = message.content[0].text
    sections = parse_ai_sections(response_text, [
        ("EXPLANATION:", "explanation"), ("BUGS:", "bugs"),
        ("SUGGESTIONS:", "suggestions"), ("COMPLEXITY:", "complexity"),
        ("SECURITY:", "security"), ("SCORE_REASONING:", "score_reasoning"),
        ("SCORE:", "score"),
    ])

    explanation = sections.get("explanation", "")
    bugs = sections.get("bugs", "")
    suggestions = sections.get("suggestions", "")
    complexity = sections.get("complexity", "")
    security = sections.get("security", "")
    score_text = sections.get("score", "0")
    score_reasoning = sections.get("score_reasoning", "")
    score_match = re.search(r'\b(\d{1,3})\b', score_text)
    score = min(100, int(score_match.group(1))) if score_match else 0

    submission.explanation = explanation
    submission.bugs = bugs
    submission.suggestions = suggestions
    submission.complexity = complexity
    submission.security = security
    submission.score = score
    submission.score_reasoning = score_reasoning
    db.commit()

    result = {
        "id": submission.id,
        "explanation": explanation,
        "bugs": bugs,
        "suggestions": suggestions,
        "complexity": complexity,
        "security": security,
        "score": score,
        "score_reasoning": score_reasoning,
        "language": language,
    }
    _result_cache_set(code_hash, result)
    return jsonify(result)

@app.route("/github/explain-repo", methods=["POST"])
@require_github_auth
def explain_repo():
    token = get_bearer_token()

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    owner = data.get("owner")
    repo = data.get("repo")
    if not isinstance(owner, str) or not isinstance(repo, str) or not owner.strip() or not repo.strip():
        return jsonify({"error": "owner and repo are required"}), 400

    if len(owner) > 100 or len(repo) > 100:
        return jsonify({"error": "owner and repo must be 100 characters or fewer"}), 400

    SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".next", "vendor"}
    SOURCE_EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".rb"}

    tree_response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    if not tree_response.ok:
        return jsonify({"error": "GitHub could not load the repository tree"}), tree_response.status_code
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
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if not file_res.ok:
            continue
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
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""You are a senior software architect with 15+ years of experience designing and shipping large-scale systems. Analyze these source files from the GitHub repository {owner}/{repo} and produce a thorough architecture summary.

CRITICAL FORMATTING RULES — YOU MUST FOLLOW THESE EXACTLY:
1. Each section header must appear on its own line, in plain uppercase text, followed immediately by a colon. Example: SUMMARY:
2. Do not use any markdown formatting on section headers. No bold (**SUMMARY:**), no hashes (## SUMMARY), no italic, no underscores. The header must be the raw uppercase word followed by a colon and nothing else on that line.
3. Do not add any preamble, introduction, or commentary before the first section header.
4. All four sections are required. Do not skip any.
5. The section order must be exactly: SUMMARY, ARCHITECTURE, TECH_STACK, ENTRY_POINTS.

SUMMARY:
Write a thorough plain-English description of what this codebase does, what problem it solves, and who it is built for. Explain the overall goal of the project as if briefing a new engineer joining the team.

ARCHITECTURE:
Write a detailed breakdown of the key components, how they interact with each other, the data flow between them, and the overall architectural pattern used. Identify whether it follows patterns such as MVC, layered architecture, microservices, event-driven, etc. and explain how those patterns are expressed in the code.

TECH_STACK:
List every language, framework, library, and tool detected across the files. For each one explain specifically what role it plays in this project — not just what the technology is in general, but what it is doing here specifically.

ENTRY_POINTS:
List the main entry points and key files a new developer should read first to understand the system. For each file explain why it is important and what understanding it unlocks.

Here are the source files:

{combined}"""
        }]
    )

    response_text = message.content[0].text
    sections = parse_ai_sections(response_text, [
        ("SUMMARY:", "summary"), ("ARCHITECTURE:", "architecture"),
        ("TECH_STACK:", "tech_stack"), ("ENTRY_POINTS:", "entry_points"),
    ])

    return jsonify({
        "summary": sections.get("summary", ""),
        "architecture": sections.get("architecture", ""),
        "tech_stack": sections.get("tech_stack", ""),
        "entry_points": sections.get("entry_points", ""),
    })


@app.route("/github/explain-file", methods=["POST"])
@require_github_auth
def explain_file():
    client, err = get_anthropic_client()
    if err:
        return err

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    content = data.get("content", "")
    filename = data.get("filename", "unknown")

    if not isinstance(content, str) or not content:
        return jsonify({"error": "No content provided"}), 400

    if len(content) > MAX_FILE_CHARACTERS:
        return jsonify({"error": f"File exceeds {MAX_FILE_CHARACTERS} character limit."}), 400

    if not isinstance(filename, str) or not filename or len(filename) > 500:
        return jsonify({"error": "Filename must be between 1 and 500 characters."}), 400

    content_hash = _make_cache_key("file-analysis", filename, content)
    content_was_truncated = len(content) > 4000

    mem = _result_cache_get(content_hash)
    if mem:
        return jsonify({**mem, "cached": True})

    db = next(get_db())
    cached = db.query(FileAnalysis).filter(FileAnalysis.content_hash == content_hash).first()
    if cached:
        hit = {
            "summary": cached.summary,
            "tech": cached.tech,
            "concepts": cached.concepts,
            "purpose": cached.purpose,
            "truncated": content_was_truncated,
        }
        _result_cache_set(content_hash, hit)
        return jsonify({**hit, "cached": True})

    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""You are a senior software engineer with 15+ years of experience across systems design, architecture, and multiple programming languages. Analyze this file thoroughly and produce a detailed breakdown.

CRITICAL FORMATTING RULES — YOU MUST FOLLOW THESE EXACTLY:
1. Each section header must appear on its own line, in plain uppercase text, followed immediately by a colon. Example: SUMMARY:
2. Do not use any markdown formatting on section headers. No bold (**SUMMARY:**), no hashes (## SUMMARY), no italic, no underscores. The header must be the raw uppercase word followed by a colon and nothing else on that line.
3. Do not add any preamble, introduction, or commentary before the first section header.
4. All four sections are required. Do not skip any.
5. The section order must be exactly: SUMMARY, TECH, CONCEPTS, PURPOSE.

SUMMARY:
Write a direct and technical explanation of what this file does and why it exists. Explain it the way you would during a code walkthrough with another senior engineer. Cover what this file is responsible for, what it owns, what calls it, what it calls, and what would break in the system if this file were removed or corrupted.

TECH:
List every language, framework, library, and external dependency imported or referenced in this file. For each one state exactly what it is used for in this specific file. Be precise and specific — do not just name the technology, explain its role here. For example do not write "React" — write "React hooks useState and useEffect are used to manage component-level state for the API key input and to trigger side effects when the GitHub token changes."

CONCEPTS:
List every key programming concept, design pattern, and architectural decision at work in this file. Examples include dependency injection, event-driven design, memoization, middleware pattern, singleton, decorator pattern, caching strategy, rate limiting, OAuth flow, etc. For each concept explain concretely and specifically where and how it appears in this file, referencing the actual functions or lines involved.

PURPOSE:
Write your perspective as a senior engineer on the design decisions made in this file. Explain what problem it is solving and why it was built this way. Identify any tradeoffs that were made. Explain how this file fits into the broader system architecture. Flag anything a junior engineer reading this file for the first time might misunderstand, misuse, or overlook. Be direct and specific.

Filename: {filename}

```
{content[:4000]}
```"""
        }]
    )

    response_text = message.content[0].text
    sections = parse_ai_sections(response_text, [
        ("SUMMARY:", "summary"), ("TECH:", "tech"),
        ("CONCEPTS:", "concepts"), ("PURPOSE:", "purpose"),
    ])

    result = {
        "summary": sections.get("summary", ""),
        "tech": sections.get("tech", ""),
        "concepts": sections.get("concepts", ""),
        "purpose": sections.get("purpose", ""),
        "truncated": content_was_truncated,
    }

    db.add(FileAnalysis(
        content_hash=content_hash,
        filename=filename,
        summary=result["summary"],
        tech=result["tech"],
        concepts=result["concepts"],
        purpose=result["purpose"],
    ))
    db.commit()
    _result_cache_set(content_hash, result)

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
