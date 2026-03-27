from flask import Blueprint, redirect, request, jsonify
import requests
import base64
import os

github_bp = Blueprint("github", __name__)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

@github_bp.route("/auth/github")
def github_login():
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&scope=repo,read:user"
    )
    return redirect(github_auth_url)

@github_bp.route("/auth/github/callback")
def github_callback():
    code = request.args.get("code")

    if not code:
        return redirect(f"{FRONTEND_URL}?error=no_code")

    token_response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
        }
    )

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(f"{FRONTEND_URL}?error=no_token")

    user_response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json"
        }
    )
    user_data = user_response.json()
    login = user_data.get("login", "")
    avatar = user_data.get("avatar_url", "")

    return redirect(
        f"{FRONTEND_URL}?github=connected"
        f"&token={access_token}"
        f"&login={login}"
        f"&avatar={avatar}"
    )

@github_bp.route("/github/repos")
def get_repos():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if not token:
        return jsonify({"error": "Not authenticated"}), 401

    repos_response = requests.get(
        "https://api.github.com/user/repos?sort=updated&per_page=30",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        }
    )

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
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    owner = request.args.get("owner")
    repo = request.args.get("repo")

    if not token:
        return jsonify({"error": "Not authenticated"}), 401

    tree_response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        }
    )

    return jsonify(tree_response.json())

@github_bp.route("/github/file")
def get_file():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
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
        }
    )

    data = file_response.json()

    if "content" in data:
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        data["decoded_content"] = content

    return jsonify(data)