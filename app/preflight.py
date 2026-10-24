"""Phase 0 readiness inventory. Configuration alone never passes a live gate."""

import json

from app.config import Settings


def readiness_report(settings: Settings) -> dict:
    missing = settings.missing_names()
    return {
        "milestone": "phase-0.2-assignment-review",
        "full_scale_ingestion_allowed": False,
        "configuration": {
            "status": "missing" if missing else "configured_unverified",
            "missing_names": missing,
        },
        "gates": {
            "assignment": {"status": "reviewed", "evidence":
                "Project requirements reviewed. Design coverage only; implementation acceptance remains pending."},
            "dataset_uniqueness": {"status": "not_verified", "required_evidence":
                "Dataset provenance, title/text uniqueness, duplicate and variant counts; final SQL document count."},
            "evaluation_evidence_coverage": {"status": "not_verified", "required_evidence":
                "Disjoint dev/final cases; supporting titles AND supporting sentences present in selected corpus."},
            "gemini_availability": {"status": "not_verified", "required_evidence":
                "Live model listing and successful generation with selected model; quota constraints recorded."},
            "supabase_capacity": {"status": "not_verified", "required_evidence":
                "Live connection, vector extension, measured table/index sizes at staged loads and 50k projection."},
            "render_memory": {"status": "not_verified", "required_evidence":
                "Actual Render service RSS and latency with fastembed/bge-small loaded and query embedding executed."},
        },
        "citation_limit": "An exact quote match proves text presence, not factual entailment.",
    }


def main() -> int:
    report = readiness_report(Settings.load())
    print(json.dumps(report, indent=2))
    return 0 if report["full_scale_ingestion_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
