import json
import os
from pathlib import Path

from app.config import Settings
from app.preflight import main, readiness_report


def test_deployment_environment_wins_without_mutating_process(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('GEMINI_API_KEY="local-secret"\nGEMINI_MODEL=local-model\n', encoding="utf-8")
    before = dict(os.environ)
    settings = Settings.load(env_file, {"GEMINI_API_KEY": "deployment-secret"})
    assert settings.gemini_api_key == "deployment-secret"
    assert settings.gemini_model == "local-model"
    assert dict(os.environ) == before


def test_explicit_empty_deployment_secret_does_not_fall_back(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=local-secret\n", encoding="utf-8")
    assert Settings.load(env_file, {"GEMINI_API_KEY": ""}).gemini_api_key == ""


def test_missing_or_blank_values_report_names_only(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY\nADMIN_TOKEN='  '\n", encoding="utf-8")
    assert Settings.load(env_file, {}).missing_names() == [
        "GEMINI_API_KEY", "GEMINI_MODEL", "DATABASE_URL", "ADMIN_TOKEN",
    ]
    assert Settings.load(tmp_path / "absent", {}) == Settings()


def test_dotenv_does_not_expand_secret_characters(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ADMIN_TOKEN='literal-${DATABASE_URL}'\nDATABASE_URL=private\n", encoding="utf-8")
    assert Settings.load(env_file, {}).admin_token == "literal-${DATABASE_URL}"


def test_default_env_path_is_independent_of_working_directory(tmp_path, monkeypatch):
    import app.config as config

    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("GEMINI_MODEL=project-model\n", encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.chdir(tmp_path)
    assert Settings.load(environ={}).gemini_model == "project-model"


def test_credentials_do_not_leak_in_repr_or_readiness_report():
    secrets = ["key-sensitive", "postgresql://user:password@host/db", "admin-sensitive"]
    settings = Settings(secrets[0], "candidate-model", secrets[1], secrets[2])
    output = repr(settings) + json.dumps(readiness_report(settings))
    assert all(secret not in output for secret in secrets)


def test_complete_configuration_cannot_pass_unmeasured_gates():
    report = readiness_report(Settings("key", "candidate-model", "db", "token"))
    assert report["configuration"]["status"] == "configured_unverified"
    assert report["full_scale_ingestion_allowed"] is False
    assert len(report["gates"]) == 6
    assert report["gates"]["assignment"]["status"] == "reviewed"
    assert all(gate["status"] == "not_verified"
               for name, gate in report["gates"].items() if name != "assignment")


def test_cli_returns_nonzero_and_machine_readable_report(monkeypatch, capsys):
    monkeypatch.setattr(Settings, "load", lambda: Settings())
    assert main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["configuration"]["status"] == "missing"
    assert not report["full_scale_ingestion_allowed"]


def test_secret_and_raw_dataset_paths_are_ignored_by_git_rules(tmp_path):
    # Verify actual Git rules in a disposable repository without tracking secrets.
    import subprocess

    root = Path(__file__).resolve().parent.parent
    (tmp_path / ".gitignore").write_bytes((root / ".gitignore").read_bytes())
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=tmp_path,
        input=(b".env\0.env.production\0data/raw/hotpot.json\0.env.example\0"
               b"AGENTS.md\0AGENTS.local.md\0CLAUDE.md\0docs/IMPLEMENTATION_PLAN_V1.0.txt\0"
               b"docs/UPGAMING_ASSIGNMENT.md\0docs/REQUIREMENTS_MAP.md\0reports/PHASE_0.md\0"
               b"README.md\0reports/AI_USAGE_REPORT.md\0app/config.py\0"),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split(b"\0") == [
        b".env", b".env.production", b"data/raw/hotpot.json", b"AGENTS.local.md", b"CLAUDE.md",
        b"docs/IMPLEMENTATION_PLAN_V1.0.txt", b"docs/UPGAMING_ASSIGNMENT.md",
        b"docs/REQUIREMENTS_MAP.md", b"reports/PHASE_0.md", b"",
    ]
