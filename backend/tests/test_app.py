import app
from sqlalchemy.exc import SQLAlchemyError


def setup_function():
    app._result_cache.clear()
    for metric_name in app._cache_metrics:
        app._cache_metrics[metric_name] = 0


def test_result_cache_returns_unexpired_value(monkeypatch):
    monkeypatch.setattr(app.time, "time", lambda: 100)
    app._result_cache_set("review:key", {"score": 90})

    monkeypatch.setattr(app.time, "time", lambda: 101)

    assert app._result_cache_get("review:key") == {"score": 90}


def test_result_cache_rejects_expired_value(monkeypatch):
    monkeypatch.setattr(app.time, "time", lambda: 100)
    app._result_cache_set("review:key", {"score": 90})

    monkeypatch.setattr(app.time, "time", lambda: 100 + app.RESULT_CACHE_TTL)

    assert app._result_cache_get("review:key") is None
    assert "review:key" not in app._result_cache
    assert app._cache_metrics["misses"] == 1


def test_cache_keys_separate_operations_and_context():
    code = "print('same content')"

    review_key = app._make_cache_key("review", "python", code)
    javascript_key = app._make_cache_key("review", "javascript", code)
    file_key = app._make_cache_key("file-analysis", "example.py", code)

    assert len({review_key, javascript_key, file_key}) == 3


def test_result_cache_evicts_oldest_entry(monkeypatch):
    monkeypatch.setattr(app, "CACHE_MAX_ENTRIES", 2)
    current_time = iter([100, 200, 300])
    monkeypatch.setattr(app.time, "time", lambda: next(current_time))

    app._result_cache_set("first", {"value": 1})
    app._result_cache_set("second", {"value": 2})
    app._result_cache_set("third", {"value": 3})

    assert "first" not in app._result_cache
    assert app._cache_metrics["evictions"] == 1


def test_sanitize_ai_section_removes_self_talk():
    text = "Useful result\nOops, I should change that\n\n\nFinal detail"

    assert app.sanitize_ai_section(text) == "Useful result\n\nFinal detail"


def test_parse_ai_sections_handles_markdown_and_inline_content():
    response = "**SUMMARY:** Inline summary\nMore detail\n## TECH:\nPython"

    sections = app.parse_ai_sections(response, [
        ("SUMMARY:", "summary"),
        ("TECH:", "tech"),
    ])

    assert sections == {
        "summary": "Inline summary\nMore detail",
        "tech": "Python",
    }


def test_parse_ai_sections_ignores_preamble_and_missing_sections():
    response = "Here is the answer\nSUMMARY:\nUseful summary"

    sections = app.parse_ai_sections(response, [
        ("SUMMARY:", "summary"),
        ("TECH:", "tech"),
    ])

    assert sections == {"summary": "Useful summary"}


def test_anthropic_client_uses_explicit_resilience_settings(monkeypatch):
    captured_arguments = {}

    def fake_anthropic(**arguments):
        captured_arguments.update(arguments)
        return object()

    monkeypatch.setattr(app, "Anthropic", fake_anthropic)
    with app.app.test_request_context(headers={"X-Api-Key": "test-key"}):
        client, error = app.get_anthropic_client()

    assert client is not None
    assert error is None
    assert captured_arguments == {
        "api_key": "test-key",
        "timeout": app.ANTHROPIC_TIMEOUT_SECONDS,
        "max_retries": app.ANTHROPIC_MAX_RETRIES,
    }


def test_review_rejects_non_json_body(monkeypatch):
    monkeypatch.setattr(app, "_validate_github_token", lambda token: True)
    client = app.app.test_client()

    response = client.post(
        "/review",
        data="not-json",
        headers={"Authorization": "Bearer test-token", "Content-Type": "text/plain"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Request body must be a JSON object."}


def test_review_rejects_unsupported_language(monkeypatch):
    monkeypatch.setattr(app, "_validate_github_token", lambda token: True)
    client = app.app.test_client()

    response = client.post(
        "/review",
        json={"code": "print('hello')", "language": "brainfuck"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Unsupported programming language."}


def test_explain_file_rejects_oversized_content(monkeypatch):
    monkeypatch.setattr(app, "_validate_github_token", lambda token: True)
    client = app.app.test_client()

    response = client.post(
        "/github/explain-file",
        json={"content": "x" * (app.MAX_FILE_CHARACTERS + 1), "filename": "large.py"},
        headers={"Authorization": "Bearer test-token", "X-Api-Key": "test-key"},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": f"File exceeds {app.MAX_FILE_CHARACTERS} character limit."}


def test_review_succeeds_when_submission_cache_is_unavailable(monkeypatch):
    class BrokenDatabase:
        def query(self, model):
            raise SQLAlchemyError("database unavailable")

        def add(self, submission):
            raise SQLAlchemyError("database unavailable")

        def rollback(self):
            return None

    class FakeMessages:
        def create(self, **arguments):
            content = """EXPLANATION:
Prints a value.
BUGS:
None found.
SUGGESTIONS:
None.
COMPLEXITY:
O(1).
SECURITY:
No security issues found.
SCORE:
90
SCORE_REASONING:
The snippet is simple and correct."""
            return type("Message", (), {"content": [type("Block", (), {"text": content})()]})()

    fake_client = type("Client", (), {"messages": FakeMessages()})()

    def fake_get_db():
        yield BrokenDatabase()

    monkeypatch.setattr(app, "_validate_github_token", lambda token: True)
    monkeypatch.setattr(app, "get_anthropic_client", lambda: (fake_client, None))
    monkeypatch.setattr(app, "get_db", fake_get_db)
    client = app.app.test_client()

    response = client.post(
        "/review",
        json={"code": "print(1)", "language": "python"},
        headers={"Authorization": "Bearer test-token", "X-Api-Key": "test-key"},
    )

    assert response.status_code == 200
    assert response.get_json()["score"] == 90
    assert response.get_json()["id"] is None


def test_database_initialization_failure_does_not_stop_app(monkeypatch):
    def fail_create_all(bind):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(app.Base.metadata, "create_all", fail_create_all)

    assert app.initialize_database() is False

