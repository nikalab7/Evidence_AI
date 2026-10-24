from app import model_cache


def test_load_model_uses_project_cache_without_network(monkeypatch, tmp_path):
    calls = []
    expected_model = object()

    def fake_text_embedding(**kwargs):
        calls.append(kwargs)
        return expected_model

    monkeypatch.setattr(model_cache, "MODEL_CACHE_DIR", tmp_path / ".model_cache")
    monkeypatch.setattr(model_cache, "TextEmbedding", fake_text_embedding)

    loaded = model_cache.load_model("test-model")

    assert loaded is expected_model
    assert calls == [{
        "model_name": "test-model",
        "cache_dir": str(tmp_path / ".model_cache"),
        "threads": 1,
        "local_files_only": True,
    }]
