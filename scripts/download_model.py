"""Download and verify the FastEmbed model during the Render build."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.embedding_smoke import EXPECTED_DIMENSIONS, MODEL_NAME, SMOKE_QUERY
from app.model_cache import (
    MODEL_CACHE_DIR,
    create_embedding_model,
    verify_cache_manifest,
    write_cache_manifest,
)


def main() -> int:
    model = create_embedding_model(MODEL_NAME, threads=1, require_prebuilt_cache=False)
    vectors = list(model.query_embed([SMOKE_QUERY]))
    if len(vectors) != 1 or len(vectors[0]) != EXPECTED_DIMENSIONS:
        raise RuntimeError("Downloaded FastEmbed model failed its dimension check")
    manifest = write_cache_manifest(MODEL_CACHE_DIR, MODEL_NAME, EXPECTED_DIMENSIONS)
    verified = verify_cache_manifest(MODEL_CACHE_DIR, MODEL_NAME, EXPECTED_DIMENSIONS)
    print(json.dumps({
        "event": "fastembed_build_cache",
        "status": "passed",
        "model": MODEL_NAME,
        "dimensions": EXPECTED_DIMENSIONS,
        "cache_path": str(MODEL_CACHE_DIR),
        "artifact_count": verified["artifact_count"],
        "cache_bytes": verified["total_bytes"],
        "manifest_bytes": manifest["total_bytes"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
