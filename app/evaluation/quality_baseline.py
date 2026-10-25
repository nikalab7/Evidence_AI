"""Load the frozen, reviewed baseline into private evaluation namespaces only."""

from pathlib import Path
import subprocess
from typing import Any

from app.reasoning.citations import validate_final_response

BASELINE_COMMIT = "ee9c9c11f90d3083917bea9bf92720ddab23939b"
ROOT = Path(__file__).resolve().parents[2]


def baseline_source(path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{path}"], cwd=ROOT,
        capture_output=True, check=True,
    )
    return result.stdout.decode("utf-8").replace("\r\n", "\n")


def _namespace(path: str) -> dict[str, Any]:
    # Source is pinned to the operator-approved commit, never supplied by a model.
    namespace = {"__name__": "evidenceai_frozen_quality_baseline"}
    exec(compile(baseline_source(path), path, "exec"), namespace)
    return namespace


def baseline_validator():
    return _namespace("app/reasoning/citations.py")["validate_final_response"]


def baseline_agent():
    """Use original prompts/loop/validator; refuse changed tool or schema dependencies."""
    for path in ("app/llm/tools.py", "app/llm/schemas.py", "app/llm/gemini_client.py",
                 "app/reasoning/contradictions.py"):
        if (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n") != baseline_source(path):
            raise RuntimeError(f"baseline dependency changed: {path}")
    support = _namespace("app/llm/agent_support.py")
    agent = _namespace("app/llm/agent.py")
    for key in ("SYSTEM_PROMPT", "add_usage", "finish", "record_requests", "trace_arguments"):
        agent[key] = support[key]
    validator = baseline_validator()

    def run(*args, **kwargs):
        captured = {}

        def capture(draft, retrieved):
            details = {}
            validate_final_response(draft, retrieved, diagnostics=details)
            captured.update({"evaluation_final_draft": draft,
                             "evaluation_validation_details": details})
            return validator(draft, retrieved)

        agent["validate_final_response"] = capture
        result = agent["investigate"](*args, **kwargs)
        if kwargs.get("capture_evaluation_details"):
            result.trace.update(captured)
        return result

    return run
