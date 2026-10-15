import app


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

