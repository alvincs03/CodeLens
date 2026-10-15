import app


def setup_function():
    app._result_cache.clear()


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


def test_sanitize_ai_section_removes_self_talk():
    text = "Useful result\nOops, I should change that\n\n\nFinal detail"

    assert app.sanitize_ai_section(text) == "Useful result\n\nFinal detail"

