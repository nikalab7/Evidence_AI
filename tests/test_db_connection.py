import pytest

from app.config import Settings
from app.db import connection


PROJECT_REF = "csenhlrsttuukzwglttf"


@pytest.mark.parametrize(
    "url",
    [
        f"postgresql://postgres.{PROJECT_REF}:secret@aws-0-eu-north-1.pooler.supabase.com:6543/postgres",
        f"postgresql://postgres:secret@db.{PROJECT_REF}.supabase.co:5432/postgres",
    ],
)
def test_project_identity_is_derived_only_from_supabase_database_endpoints(url):
    assert connection.project_ref_from_database_url(url) == PROJECT_REF


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:secret@aws-0-eu-north-1.pooler.supabase.com:6543/postgres",
        "postgresql://postgres.umbayvfikvxjzhxojofn:secret@aws-0-eu-north-1.pooler.supabase.com/postgres",
        "postgresql://postgres:secret@db.other-project.supabase.co:5432/postgres",
        "not-a-url",
    ],
)
def test_unknown_or_wrong_project_identity_fails_before_connect(url, monkeypatch):
    monkeypatch.setattr(connection.Settings, "load", lambda: Settings(database_url=url))

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("psycopg.connect must not run for an unverified project")

    monkeypatch.setattr(connection.psycopg, "connect", fail_if_called)
    with pytest.raises(RuntimeError, match="refusing connection") as error:
        connection.connect_database()
    assert "secret" not in str(error.value)


def test_verified_project_identity_is_passed_to_psycopg_without_logging(monkeypatch):
    url = f"postgresql://postgres.{PROJECT_REF}:private-value@aws-0-eu-north-1.pooler.supabase.com:6543/postgres"
    monkeypatch.setattr(connection.Settings, "load", lambda: Settings(database_url=url))
    calls = []
    marker = object()
    monkeypatch.setattr(connection.psycopg, "connect", lambda *args, **kwargs: calls.append((args, kwargs)) or marker)

    assert connection.connect_database(autocommit=True) is marker
    assert calls[0][0] == (url,)
    assert calls[0][1]["autocommit"] is True
