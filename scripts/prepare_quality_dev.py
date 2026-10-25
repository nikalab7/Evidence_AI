"""Select new development questions without reading final cases or gold answers."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = "evidenceai-phase7.4-v1"
DEV = ROOT / "eval/retrieval_dev.jsonl"
QUESTIONS = ROOT / "eval/quality_dev_questions.jsonl"
FIXTURES = ROOT / "eval/quality_dev_fixtures.json"
MANIFEST = ROOT / "eval/quality_dev_manifest.json"


def select_questions(rows: list[dict]) -> list[dict]:
    selected = []
    for kind in ("bridge", "comparison"):
        for level, count in (("easy", 4), ("medium", 3), ("hard", 3)):
            candidates = [r for r in rows if r["type"] == kind and r["level"] == level]
            candidates.sort(key=lambda r: hashlib.sha256(
                (SEED + r["question_id"]).encode()).hexdigest())
            if len(candidates) < count:
                raise ValueError("insufficient development strata")
            selected.extend(candidates[:count])
    if len({r["question_id"] for r in selected}) != 20:
        raise ValueError("expected 20 distinct development questions")
    return selected


def main() -> None:
    rows = [json.loads(line) for line in DEV.read_text(encoding="utf-8").splitlines() if line]
    selected = select_questions(rows)
    QUESTIONS.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                  for r in selected), encoding="utf-8")
    manifest = {
        "seed": SEED, "source": "eval/retrieval_dev.jsonl",
        "source_sha256": hashlib.sha256(DEV.read_bytes()).hexdigest(),
        "questions_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(),
        "fixtures_sha256": hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
        "selected_ids": [r["question_id"] for r in selected],
        "strata_per_type": {"easy": 4, "medium": 3, "hard": 3},
        "fixture_count": len(json.loads(FIXTURES.read_text(encoding="utf-8"))),
        "scope": "development only; original final cases are never read by this selector",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
