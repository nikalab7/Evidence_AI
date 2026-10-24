"""Download and verify the FastEmbed model during the Render build."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from fastembed import TextEmbedding

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.embedding_smoke import EXPECTED_DIMENSIONS, MODEL_NAME, SMOKE_QUERY
from app.model_cache import MODEL_CACHE_DIR, load_model


def main() -> int:
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    downloader = TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
        threads=1,
        local_files_only=False,
    )
    downloaded_vectors = list(downloader.query_embed([SMOKE_QUERY]))
    if len(downloaded_vectors) != 1 or len(downloaded_vectors[0]) != EXPECTED_DIMENSIONS:
        raise RuntimeError("Downloaded FastEmbed model failed its dimension check")

    offline_model = load_model(MODEL_NAME)
    offline_vectors = list(offline_model.query_embed([SMOKE_QUERY]))
    if len(offline_vectors) != 1 or len(offline_vectors[0]) != EXPECTED_DIMENSIONS:
        raise RuntimeError("Cached FastEmbed model failed its offline dimension check")

    print(json.dumps({
        "event": "fastembed_build_cache",
        "status": "passed",
        "model": MODEL_NAME,
        "dimensions": EXPECTED_DIMENSIONS,
        "cache_path": str(MODEL_CACHE_DIR),
        "offline_load_passed": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
