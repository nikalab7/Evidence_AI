"""Shared FastEmbed cache path and integrity checks for build and runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_CACHE_DIR = PROJECT_ROOT / ".model_cache"
MANIFEST_NAME = "evidenceai-model-manifest.json"
MANIFEST_VERSION = 1


def cache_is_required(environ: dict[str, str] | None = None) -> bool:
    """Return whether runtime must reject a missing build-time cache."""
    values = os.environ if environ is None else environ
    return values.get("FASTEMBED_REQUIRE_PREBUILT_CACHE", "false").lower() == "true"


def write_cache_manifest(
    cache_dir: Path, model_name: str, dimensions: int,
) -> dict[str, Any]:
    """Record the downloaded model files using relative paths and byte sizes."""
    cache_dir = cache_dir.resolve()
    files_by_target: dict[Path, dict[str, Any]] = {}
    for path in sorted(cache_dir.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME or path.suffix == ".lock":
            continue
        target = path.resolve()
        if not target.is_relative_to(cache_dir):
            raise RuntimeError("FastEmbed cache artifact resolves outside the project cache")
        size = target.stat().st_size
        if size <= 0:
            raise RuntimeError("FastEmbed cache contains an empty artifact")
        files_by_target.setdefault(target, {
            "path": target.relative_to(cache_dir).as_posix(), "size_bytes": size,
        })
    files = list(files_by_target.values())
    if not files:
        raise RuntimeError("FastEmbed cache has no complete model files")
    manifest = {
        "format_version": MANIFEST_VERSION,
        "model": model_name,
        "dimensions": dimensions,
        "files": files,
        "total_bytes": sum(file["size_bytes"] for file in files),
    }
    (cache_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return manifest


def verify_cache_manifest(
    cache_dir: Path, expected_model: str, expected_dimensions: int,
) -> dict[str, Any]:
    """Check the manifest and every listed artifact in the current filesystem."""
    cache_dir = cache_dir.resolve()
    manifest_path = cache_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("FastEmbed build cache manifest is missing or invalid") from exc
    if (manifest.get("format_version") != MANIFEST_VERSION
            or manifest.get("model") != expected_model
            or manifest.get("dimensions") != expected_dimensions
            or not isinstance(manifest.get("files"), list)):
        raise RuntimeError("FastEmbed build cache manifest does not match runtime settings")
    total_bytes = 0
    for item in manifest["files"]:
        relative = item.get("path")
        if not isinstance(relative, str):
            raise RuntimeError("FastEmbed build cache manifest has an invalid file path")
        path = (cache_dir / relative).resolve()
        if not path.is_relative_to(cache_dir) or not path.is_file():
            raise RuntimeError("A FastEmbed build artifact is missing")
        size = path.stat().st_size
        if size <= 0 or size != item.get("size_bytes"):
            raise RuntimeError("A FastEmbed build artifact is incomplete")
        total_bytes += size
    if not manifest["files"] or total_bytes != manifest.get("total_bytes"):
        raise RuntimeError("FastEmbed build cache manifest failed integrity checks")
    return {"artifact_count": len(manifest["files"]), "total_bytes": total_bytes}


def prebuilt_cache_evidence(model_name: str, dimensions: int) -> dict[str, int] | None:
    """Return artifact measurements only when runtime requires the prebuilt cache."""
    if not cache_is_required():
        return None
    return verify_cache_manifest(MODEL_CACHE_DIR, model_name, dimensions)


def create_embedding_model(
    model_name: str,
    threads: int,
    model_factory: Any | None = None,
    *,
    require_prebuilt_cache: bool | None = None,
) -> Any:
    """Construct TextEmbedding with the same absolute cache path everywhere."""
    require_cache = cache_is_required() if require_prebuilt_cache is None else require_prebuilt_cache
    if require_cache:
        verify_cache_manifest(MODEL_CACHE_DIR, model_name, 384)
    if model_factory is None:
        from fastembed import TextEmbedding

        model_factory = TextEmbedding
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return model_factory(
        model_name=model_name, cache_dir=str(MODEL_CACHE_DIR), threads=threads,
    )
