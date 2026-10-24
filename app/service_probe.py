"""Small explicit live checks, not ingestion clearance or the production LLM client."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from time import perf_counter

import httpx
import psycopg

from app.config import Settings


API_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL_NAME = re.compile(r"models/[a-zA-Z0-9._-]+\Z")
PREFERRED_MODELS = ("gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash")


def probe_gemini(settings: Settings, client: httpx.Client) -> dict:
    if not settings.gemini_api_key:
        return {"status": "missing_configuration", "name": "GEMINI_API_KEY"}
    result = {"status": "failed", "generation_calls": 0}
    headers = {"x-goog-api-key": settings.gemini_api_key}
    started = perf_counter()
    try:
        models = set()
        token = None
        for _ in range(10):
            params = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            response = client.get(f"{API_BASE}/models", headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            for model in payload.get("models", []):
                name = model.get("name", "")
                if MODEL_NAME.fullmatch(name) and "generateContent" in model.get("supportedGenerationMethods", []):
                    models.add(name)
            token = payload.get("nextPageToken")
            if not token:
                break
        else:
            return {**result, "error": "model_listing_page_limit"}
        result["available_generation_models"] = sorted(models)
        selected = settings.gemini_model.removeprefix("models/")
        if not selected:
            selected = next((name for name in PREFERRED_MODELS if f"models/{name}" in models), "")
        if not selected or f"models/{selected}" not in models:
            return {**result, "error": "select_available_model"}
        result["selected_model"] = selected
        result["generation_calls"] = 1
        response = client.post(
            f"{API_BASE}/models/{selected}:generateContent", headers=headers,
            json={"contents": [{"parts": [{"text": "Reply with the single word OK."}]}],
                  "generationConfig": {"maxOutputTokens": 64}},
        )
        response.raise_for_status()
        payload = response.json()
        text = "".join(part.get("text", "")
                       for candidate in payload.get("candidates", [])
                       for part in candidate.get("content", {}).get("parts", [])
                       if not part.get("thought"))
        result["nonempty_text_response"] = bool(text.strip())
        # Report only numeric usage, never model text, server error bodies, or headers.
        result["usage"] = {key: val for key, val in payload.get("usageMetadata", {}).items()
                           if key.endswith("TokenCount") and isinstance(val, int)}
        result["status"] = "passed" if text.strip() else "failed"
        if not text.strip():
            result["error"] = "no_text_response"
    except httpx.HTTPStatusError as exc:
        result["http_status"] = exc.response.status_code
        result["error"] = "http_error"
    except httpx.TimeoutException:
        result["error"] = "timeout"
    except httpx.RequestError:
        result["error"] = "network_error"
    except (ValueError, TypeError, AttributeError):
        result["error"] = "invalid_response"
    result["elapsed_seconds"] = round(perf_counter() - started, 3)
    return result


def probe_database(settings: Settings, *, enable_vector: bool = False, connect=None) -> dict:
    if not settings.database_url:
        return {"status": "missing_configuration", "name": "DATABASE_URL"}
    result = {"status": "failed", "capacity_verified": False}
    started = perf_counter()
    try:
        with (connect or psycopg.connect)(
            settings.database_url, connect_timeout=10, sslmode="require", autocommit=True,
        ) as conn:
            conn.execute("SET statement_timeout = '10000'")
            result["connection"] = conn.execute("SELECT 1").fetchone()[0] == 1
            available = conn.execute(
                "SELECT default_version, installed_version FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
            result["vector_available"] = available is not None
            if enable_vector and available and not available[1]:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
                result["vector_enabled_by_probe"] = True
            installed = conn.execute(
                "SELECT e.extversion, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
            ).fetchone()
            result["vector_installed"] = installed is not None
            if installed:
                # The schema identifier comes from Postgres and must still be quoted.
                query = psycopg.sql.SQL("SELECT '[1,0,0]'::{schema}.vector <=> '[1,0,0]'::{schema}.vector").format(
                    schema=psycopg.sql.Identifier(installed[1]))
                # Supabase normally includes extensions in search_path; set it explicitly.
                conn.execute(psycopg.sql.SQL("SET search_path TO pg_catalog, public, {}").format(
                    psycopg.sql.Identifier(installed[1])))
                result["vector_version"] = installed[0]
                result["cosine_smoke_passed"] = conn.execute(query).fetchone()[0] == 0
            result["database_size_bytes"] = conn.execute(
                "SELECT pg_database_size(current_database())"
            ).fetchone()[0]
            result["status"] = "passed" if result["connection"] and result.get("cosine_smoke_passed") else "incomplete"
    except psycopg.Error as exc:
        # Raw libpq messages can contain DSNs, user names and passwords.
        result["error"] = "database_error"
        result["sqlstate"] = exc.sqlstate
        message = str(exc).lower()
        # Match diagnostic categories locally; never serialize the original message.
        result["reason"] = next((category for category, fragments in (
            ("authentication_failed", ("password authentication failed", "authentication failed")),
            ("tenant_or_user_not_found", ("tenant or user not found",)),
            ("dns_failure", ("could not translate host", "name or service not known", "getaddrinfo failed", "failed to resolve")),
            ("connection_timeout", ("timeout expired", "connection timeout")),
            ("connection_refused", ("connection refused", "actively refused")),
            ("network_permission_denied", ("permission denied", "forbidden by its access permissions")),
            ("invalid_connection_string", ("invalid dsn", "invalid uri", "invalid percent-encoded", "missing '='")),
        ) if any(fragment in message for fragment in fragments)), "unclassified_database_error")
    result["elapsed_seconds"] = round(perf_counter() - started, 3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-vector", action="store_true", help="Enable vector extension if available but not installed.")
    parser.add_argument("--output", type=Path, help="Save sanitized evidence JSON.")
    parser.add_argument("--only", choices=("gemini", "database"), help="Probe one service without calling the other.")
    args = parser.parse_args()
    settings = Settings.load()
    gemini = {"status": "skipped"}
    database = {"status": "skipped"}
    if args.only != "database":
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            gemini = probe_gemini(settings, client)
    if args.only != "gemini":
        database = probe_database(settings, enable_vector=args.enable_vector)
    report = {
        "milestone": "phase-0.3-service-probes",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "gemini": gemini, "supabase": database,
        "full_scale_ingestion_allowed": False,
        "limitations": ["No quota capacity proof from one successful generation.",
                        "Database connection and current size do not verify 50k capacity.",
                        "Dataset uniqueness, evaluation coverage and Render memory remain unverified."],
    }
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if all(service["status"] in ("passed", "skipped")
                    for service in (gemini, database)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
