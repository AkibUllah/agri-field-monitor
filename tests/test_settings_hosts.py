from __future__ import annotations

from config.settings import database_from_url, with_render_hostname


def test_render_hostname_is_added_to_hosts_and_origins() -> None:
    hosts, origins = with_render_hostname(["localhost"], [], "awd.onrender.com")
    assert hosts == ["localhost", "awd.onrender.com"]
    assert origins == ["https://awd.onrender.com"]


def test_render_hostname_is_not_duplicated() -> None:
    hosts, origins = with_render_hostname(
        ["awd.onrender.com"], ["https://awd.onrender.com"], "awd.onrender.com"
    )
    assert hosts == ["awd.onrender.com"]
    assert origins == ["https://awd.onrender.com"]


def test_without_render_hostname_nothing_changes() -> None:
    assert with_render_hostname(["localhost"], ["https://a.example"], None) == (
        ["localhost"],
        ["https://a.example"],
    )
    assert with_render_hostname([], [], "") == ([], [])


def test_managed_postgres_url_is_parsed() -> None:
    db = database_from_url("postgres://awd:secret@db.render.internal:5432/awd")
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert (db["USER"], db["PASSWORD"], db["HOST"], db["PORT"], db["NAME"]) == (
        "awd",
        "secret",
        "db.render.internal",
        "5432",
        "awd",
    )
