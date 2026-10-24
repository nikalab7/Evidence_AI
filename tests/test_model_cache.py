import json

import pytest

from app.model_cache import (
    MANIFEST_NAME,
    create_embedding_model,
    verify_cache_manifest,
    write_cache_manifest,
)


def test_model_manifest_records_and_verifies_artifacts(tmp_path, monkeypatch):
    import app.model_cache as model_cache

    cache = tmp_path / ".model_cache"
    cache.mkdir()
    artifact = cache / "model.onnx"
    artifact.write_bytes(b"model-data")
    manifest = write_cache_manifest(cache, "test-model", 384)
    assert manifest["total_bytes"] == len(b"model-data")
    assert verify_cache_manifest(cache, "test-model", 384)["artifact_count"] == 1

    artifact.unlink()
    with pytest.raises(RuntimeError, match="artifact is missing"):
        verify_cache_manifest(cache, "test-model", 384)


def test_runtime_requires_a_matching_manifest(monkeypatch, tmp_path):
    import app.model_cache as model_cache

    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", tmp_path.resolve())
    monkeypatch.setenv("FASTEMBED_REQUIRE_PREBUILT_CACHE", "true")
    with pytest.raises(RuntimeError, match="manifest is missing"):
        create_embedding_model("test-model", 1, lambda **kwargs: object())


def test_manifest_rejects_paths_outside_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside.onnx"
    outside.write_bytes(b"model")
    (cache / MANIFEST_NAME).write_text(json.dumps({
        "format_version": 1, "model": "test-model", "dimensions": 384,
        "files": [{"path": "../outside.onnx", "size_bytes": 5}], "total_bytes": 5,
    }), encoding="utf-8")
    with pytest.raises(RuntimeError, match="artifact is missing"):
        verify_cache_manifest(cache, "test-model", 384)


def test_smoke_check_reports_a_verified_prebuilt_cache(tmp_path, monkeypatch):
    from app.embedding_smoke import run_embedding_smoke_test
    import app.model_cache as model_cache

    class FakeModel:
        def query_embed(self, queries):
            return [[0.0] * 384]

    cache = tmp_path.resolve()
    (cache / "model.onnx").write_bytes(b"test-model")
    write_cache_manifest(cache, "BAAI/bge-small-en-v1.5", 384)
    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", cache)
    monkeypatch.setenv("FASTEMBED_REQUIRE_PREBUILT_CACHE", "true")
    _, report = run_embedding_smoke_test(
        model_factory=lambda **kwargs: FakeModel(),
        rss_reader=lambda: 100, peak_rss_reader=lambda: 120,
    )
    assert report["model_cache"]["verified"] is True
    assert report["model_cache"]["artifact_count"] == 1
    assert report["model_cache"]["total_bytes"] == len(b"test-model")
