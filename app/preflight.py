"""Phase 0 readiness inventory. Configuration alone never passes a live gate."""

import json
from pathlib import Path

from app.config import Settings


RENDER_PREFLIGHT_PATH = Path(__file__).resolve().parent.parent / "reports" / "render_preflight.json"
RENDER_FREE_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


def render_memory_gate(evidence_path: Path = RENDER_PREFLIGHT_PATH) -> dict:
    """Verify the memory gate from a recorded Render startup measurement."""
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        peak = evidence["peak_rss_bytes"]
        valid = (
            evidence.get("status") == "passed"
            and evidence.get("model") == "BAAI/bge-small-en-v1.5"
            and evidence.get("dimensions") == 384
            and isinstance(peak, int) and 0 < peak <= RENDER_FREE_MEMORY_LIMIT_BYTES
            and isinstance(evidence.get("first_query_embedding_seconds"), (int, float))
            and evidence["first_query_embedding_seconds"] >= 0
        )
    except (OSError, ValueError, KeyError, TypeError):
        evidence = {}
        valid = False
    if not valid:
        return {"status": "not_verified", "evidence": "No valid passing Render memory report is recorded."}
    return {
        "status": "verified",
        "evidence": (
            f"Recorded Render peak RSS {peak} bytes ({peak / 1048576:.1f} MiB), "
            f"query latency {evidence['first_query_embedding_seconds']:.4f}s, "
            "384 dimensions; within the 512 MiB gate. See reports/render_preflight.md."
        ),
        "peak_rss_bytes": peak,
        "memory_limit_bytes": RENDER_FREE_MEMORY_LIMIT_BYTES,
        "restart_check": evidence.get("restart_check", "pending"),
    }


def readiness_report(settings: Settings) -> dict:
    missing = settings.missing_names()
    return {
        "milestone": "phase-0-readiness",
        "full_scale_ingestion_allowed": False,
        "configuration": {
            "status": "missing" if missing else "configured_unverified",
            "missing_names": missing,
        },
        "gates": {
            "assignment": {"status": "reviewed", "evidence":
                "Project requirements reviewed. Design coverage only; implementation acceptance remains pending."},
            "dataset_uniqueness": {"status": "candidate_pool_audited", "evidence":
                "Pinned HotpotQA exact normalized title+paragraph scan: 507,494 unique records across both splits; near duplicates, final subset, and SQL counts remain pending. See reports/hotpotqa_audit.json."},
            "evaluation_evidence_coverage": {"status": "partial", "evidence":
                "Validation evidence was audited; train-only coverage is 73.31% of valid support sentences and 57.36% of valid questions. One support reference is invalid; final subset coverage remains pending. See reports/hotpotqa_audit.json."},
            "gemini_availability": {"status": "not_verified", "required_evidence":
                "Live model listing and successful generation with selected model; quota constraints recorded."},
            "supabase_capacity": {"status": "not_verified", "required_evidence":
                "Live connection, vector extension, measured table/index sizes at staged loads and 50k projection."},
            "render_memory": render_memory_gate(),
        },
        "citation_limit": "An exact quote match proves text presence, not factual entailment.",
    }


def main() -> int:
    report = readiness_report(Settings.load())
    print(json.dumps(report, indent=2))
    return 0 if report["full_scale_ingestion_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
