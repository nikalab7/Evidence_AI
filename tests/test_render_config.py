from pathlib import Path


BLUEPRINT = Path("render.frankfurt.yaml").read_text(encoding="utf-8")


def _env_var_setting(name: str) -> str:
    lines = BLUEPRINT.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.strip() == f"- key: {name}":
            return lines[index + 1].strip()
    raise AssertionError(f"{name} is not declared in the Frankfurt Blueprint")


def test_frankfurt_blueprint_preserves_operator_managed_secrets_and_budget():
    for name in ("DATABASE_URL", "GEMINI_API_KEY", "ADMIN_TOKEN", "INVESTIGATION_DAILY_BUDGET"):
        assert _env_var_setting(name) == "sync: false"


def test_frankfurt_blueprint_keeps_document_library_runtime_commands():
    assert "region: frankfurt" in BLUEPRINT
    assert "buildCommand: pip install -r requirements.txt && python scripts/download_model.py" in BLUEPRINT
    assert "startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers" in BLUEPRINT
    assert 'autoDeployTrigger: "off"' in BLUEPRINT
