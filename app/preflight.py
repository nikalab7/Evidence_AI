"""Phase 0 readiness inventory. Configuration alone never passes a live gate."""

import json

from app.config import Settings


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
            "render_memory": {"status": "startup_passed_restart_pending", "evidence":
                "Owner-provided Render log: 384 dimensions, 0.1003s query latency, 300,912,640 bytes peak RSS. A separate restart check remains pending. See reports/render_preflight.md."},
        },
        "citation_limit": "An exact quote match proves text presence, not factual entailment.",
    }


def main() -> int:
    report = readiness_report(Settings.load())
    print(json.dumps(report, indent=2))
    return 0 if report["full_scale_ingestion_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
