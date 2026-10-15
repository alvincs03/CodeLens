from urllib.parse import parse_qs, urlparse

import app


def test_github_login_stores_state_and_sends_it_to_github():
    client = app.app.test_client()

    response = client.get("/auth/github")

    query = parse_qs(urlparse(response.location).query)
    with client.session_transaction() as browser_session:
        stored_state = browser_session["github_oauth_state"]

    assert response.status_code == 302
    assert query["state"] == [stored_state]
    assert len(stored_state) >= 32


def test_github_callback_rejects_mismatched_state():
    client = app.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["github_oauth_state"] = "expected-state"

    response = client.get("/auth/github/callback?code=test-code&state=wrong-state")

    assert response.status_code == 302
    assert response.location.endswith("?error=invalid_state")


def test_github_proxy_rejects_malformed_bearer_header():
    client = app.app.test_client()

    response = client.get("/github/repos", headers={"Authorization": "Token abc"})

    assert response.status_code == 401
