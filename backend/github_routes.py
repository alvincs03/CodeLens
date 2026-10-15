from flask import Blueprint, redirect, request, jsonify, session
import requests
import base64
import hmac
import os
import secrets
from urllib.parse import urlencode

github_bp = Blueprint("github", __name__)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
GITHUB_REQUEST_TIMEOUT = 10

def get_bearer_token():
    authorization_header = request.headers.get("Authorization", "")
    scheme, separator, token = authorization_header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token.strip()

@github_bp.route("/auth/github")
def github_login():
    oauth_state = secrets.token_urlsafe(32)
    session["github_oauth_state"] = oauth_state
    query = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "scope": "repo read:user",
        "state": oauth_state,
    })
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?{query}"
    )
    return redirect(github_auth_url)

@github_bp.route("/auth/github/callback")
def github_callback():
    code = request.args.get("code")
    returned_state = request.args.get("state", "")
    expected_state = session.pop("github_oauth_state", "")

    if not code:
        return redirect(f"{FRONTEND_URL}?error=no_code")

    if not expected_state or not hmac.compare_digest(returned_state, expected_state):
        return redirect(f"{FRONTEND_URL}?error=invalid_state")

    token_response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        },
        timeout=GITHUB_REQUEST_TIMEOUT,
    )
    token_response.raise_for_status()

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(f"{FRONTEND_URL}?error=no_token")

    user_response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=GITHUB_REQUEST_TIMEOUT,
    )
    user_response.raise_for_status()
    user_data = user_response.json()
    login = user_data.get("login", "")
    avatar = user_data.get("avatar_url", "")

    query = urlencode({
        "github": "connected",
        "token": access_token,
        "login": login,
        "avatar": avatar,
    })
    return redirect(f"{FRONTEND_URL}?{query}")

@github_bp.route("/github/repos")
def get_repos():
    token = get_bearer_token()

    if not token:
        return jsonify({"error": "Not authenticated"}), 401

    repos_response = requests.get(
        "https://api.github.com/user/repos?sort=updated&per_page=30",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=GITHUB_REQUEST_TIMEOUT,
    )
    if not repos_response.ok:
        return jsonify({"error": "GitHub could not load repositories"}), repos_response.status_code

    repos = repos_response.json()

    simplified = [
        {
            "id": r["id"],
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description", ""),
            "language": r.get("language", ""),
            "updated_at": r["updated_at"],
            "private": r["private"],
            "url": r["html_url"],
        }
        for r in repos
        if isinstance(r, dict)
    ]

    return jsonify(simplified)

@github_bp.route("/github/tree")
def get_repo_tree():
    token = get_bearer_token()
    owner = request.args.get("owner")
    repo = request.args.get("repo")

    if not token:
        return jsonify({"error": "Not authenticated"}), 401

    tree_response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=GITHUB_REQUEST_TIMEOUT,
    )
    if not tree_response.ok:
        return jsonify({"error": "GitHub could not load the repository tree"}), tree_response.status_code

    return jsonify(tree_response.json())

@github_bp.route("/github/file")
def get_file():
    token = get_bearer_token()
    owner = request.args.get("owner")
    repo = request.args.get("repo")
    path = request.args.get("path")

    if not token:
        return jsonify({"error": "Not authenticated"}), 401

    file_response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=GITHUB_REQUEST_TIMEOUT,
    )
    if not file_response.ok:
        return jsonify({"error": "GitHub could not load the file"}), file_response.status_code

    data = file_response.json()

    if "content" in data:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        data["decoded_content"] = content

    return jsonify(data)
