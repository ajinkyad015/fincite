"""Server bind/concurrency resolution and pool wiring.

Regression coverage for:
* the bind port coming from settings (a hardcoded port ignores the
  platform-assigned PORT on PaaS hosts),
* the worker-count resolution (WEB_CONCURRENCY > BACKEND_WORKERS, default 1),
* reload being explicit instead of derived from LOG_LEVEL=DEBUG (a verbose
  production deploy used to silently run the StatReload watcher),
* the settings -> engine pool wiring in app.db.session.
"""
from app.core.config import settings
from app.db import session as session_module
from app.main import _server_options


def test_defaults_are_small_instance_safe():
    opts = _server_options()
    assert opts["port"] == 8000
    assert opts["workers"] == 1
    assert opts["host"] == "0.0.0.0"
    assert opts["reload"] is False


def test_port_setting_is_honoured(monkeypatch):
    # PaaS platforms inject PORT; the server must bind exactly that port.
    monkeypatch.setattr(settings, "PORT", 10000)
    assert _server_options()["port"] == 10000


def test_web_concurrency_overrides_backend_workers(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_WORKERS", 3)
    monkeypatch.setattr(settings, "WEB_CONCURRENCY", 2)
    assert _server_options()["workers"] == 2
    monkeypatch.setattr(settings, "WEB_CONCURRENCY", None)
    assert _server_options()["workers"] == 3


def test_reload_is_explicit_not_derived_from_log_level(monkeypatch):
    # Regression: reload used to follow LOG_LEVEL=DEBUG, so any verbose
    # production deploy ran the reloader (and uvicorn ignores workers under
    # reload). It must now require the explicit RELOAD setting.
    monkeypatch.setattr(settings, "LOG_LEVEL", "DEBUG")
    assert _server_options()["reload"] is False
    monkeypatch.setattr(settings, "RELOAD", True)
    assert _server_options()["reload"] is True


def test_db_pool_defaults_fit_hosted_free_tiers():
    assert settings.DB_POOL_SIZE == 2
    assert settings.DB_MAX_OVERFLOW == 2
    assert settings.DB_POOL_RECYCLE_S > 0
    assert settings.DB_POOL_TIMEOUT_S > 0


def test_create_app_engine_uses_configured_pool(monkeypatch):
    """The engine must be built from settings, not hardcoded pool numbers."""
    captured = {}

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(session_module, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(settings, "DB_POOL_SIZE", 5)
    monkeypatch.setattr(settings, "DB_MAX_OVERFLOW", 1)
    monkeypatch.setattr(settings, "DB_POOL_RECYCLE_S", 900)
    monkeypatch.setattr(settings, "DB_POOL_TIMEOUT_S", 10)

    session_module.create_app_engine()

    assert captured["pool_size"] == 5
    assert captured["max_overflow"] == 1
    assert captured["pool_recycle"] == 900
    assert captured["pool_timeout"] == 10
    assert captured["pool_pre_ping"] is True
