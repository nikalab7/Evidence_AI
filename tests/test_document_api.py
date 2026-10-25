from contextlib import suppress

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import app


@pytest.fixture
def library_client():
    names = ("settings", "embedding_model")
    old = {name: getattr(app.state, name, None) for name in names}
    app.state.settings = Settings(
        "test-gemini-key", "gemini-3.5-flash-lite",
        "postgresql://user:password@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres",
        "phase6b-test-admin-token-9f2a4d7c8b1e",
    )
    app.state.embedding_model = object()
    try:
        yield TestClient(app)
    finally:
        for name, value in old.items():
            if value is None:
                with suppress(AttributeError):
                    delattr(app.state, name)
            else:
                setattr(app.state, name, value)


def _auth():
    return {"Authorization": "Bearer phase6b-test-admin-token-9f2a4d7c8b1e"}


def _document(upload_id="upload-1"):
    return {
        "upload_id": upload_id, "doc_id": "a" * 64, "source_id": "b" * 64,
        "title": "Owner file", "original_filename": "notes.txt", "file_format": "txt",
        "file_size_bytes": 12, "chunking_strategy": "paragraph", "parser_metadata": {},
        "uploaded_at": "2026-10-25T00:00:00Z", "updated_at": "2026-10-25T00:00:00Z",
        "source_url": "upload://owner", "source_revision": "managed-upload-v1",
        "source_split": "managed_upload", "source_sentences": [],
        "text": "Preserved canonical text.", "document_metadata": {}, "chunk_count": 1,
        "text_chars": 25,
    }


def test_library_requires_server_side_bearer_auth_for_every_api_call(library_client, monkeypatch):
    import app.api.documents as api

    monkeypatch.setattr(api, "list_uploads", lambda **_kwargs: pytest.fail("unauthorized DB read"))
    assert library_client.get("/api/documents").status_code == 401
    assert library_client.get("/api/documents/00000000-0000-0000-0000-000000000001").status_code == 401
    assert library_client.delete("/api/documents/00000000-0000-0000-0000-000000000001").status_code == 401
    result = library_client.post(
        "/api/documents", files={"file": ("notes.txt", b"some text")},
    )
    assert result.status_code == 401
    assert "phase6b-test-admin-token-9f2a4d7c8b1e" not in result.text


def test_document_management_fails_closed_for_missing_or_weak_admin_token(library_client, monkeypatch):
    import app.api.documents as api

    monkeypatch.setattr(api, "list_uploads", lambda **_kwargs: pytest.fail("weak token reached DB"))
    library_client.app.state.settings = Settings(
        "test-gemini-key", "gemini-3.5-flash-lite",
        "postgresql://user:password@db.nldnpqhqrfwjgxcqeuru.supabase.co/postgres", "short",
    )
    response = library_client.get("/api/documents", headers={"Authorization": "Bearer short"})
    assert response.status_code == 503
    assert "strong administrator token" in response.json()["detail"]


def test_upload_list_inspect_update_delete_routes_use_the_startup_model(library_client, monkeypatch):
    import app.api.documents as api

    model = library_client.app.state.embedding_model
    calls = []
    monkeypatch.setattr(api, "create_upload", lambda **kwargs: calls.append(kwargs) or _document())
    monkeypatch.setattr(api, "list_uploads", lambda **kwargs: [_document()])
    monkeypatch.setattr(api, "inspect_upload", lambda _upload_id: _document())
    monkeypatch.setattr(api, "replace_upload", lambda **kwargs: calls.append(kwargs) or _document())
    monkeypatch.setattr(api, "remove_upload", lambda _upload_id: True)

    uploaded = library_client.post(
        "/api/documents", headers=_auth(),
        files={"file": ("notes.txt", b"some text")},
        data={"title": "Owner file", "chunking_strategy": "paragraph"},
    )
    assert uploaded.status_code == 201
    assert calls[-1]["model"] is model
    assert calls[-1]["content"] == b"some text"

    listed = library_client.get("/api/documents", headers=_auth())
    assert listed.status_code == 200 and listed.json()["documents"][0]["source_split"] == "managed_upload"
    inspected = library_client.get(
        "/api/documents/00000000-0000-0000-0000-000000000001", headers=_auth(),
    )
    assert inspected.status_code == 200
    assert inspected.json()["document"]["text"] == "Preserved canonical text."
    assert inspected.json()["document"]["source_revision"] == "managed-upload-v1"

    updated = library_client.put(
        "/api/documents/00000000-0000-0000-0000-000000000001", headers=_auth(),
        files={"file": ("replacement.md", b"replacement content")},
        data={"title": "Replacement", "chunking_strategy": "fixed_overlap"},
    )
    assert updated.status_code == 200
    assert calls[-1]["model"] is model
    assert calls[-1]["chunking_strategy"] == "fixed_overlap"
    removed = library_client.delete(
        "/api/documents/00000000-0000-0000-0000-000000000001", headers=_auth(),
    )
    assert removed.status_code == 204


def test_upload_limits_scanned_pdf_errors_and_backend_errors_are_sanitized(library_client, monkeypatch):
    import app.api.documents as api
    from app.db.managed_uploads import UploadConflictError
    from app.ingestion.parsers import UnsupportedScannedPdfError

    monkeypatch.setattr(api, "create_upload", lambda **_kwargs: (_ for _ in ()).throw(
        UnsupportedScannedPdfError("Scanned/image-only PDFs are unsupported."),
    ))
    scanned = library_client.post(
        "/api/documents", headers=_auth(), files={"file": ("scan.pdf", b"%PDF-1.4")},
    )
    assert scanned.status_code == 415
    assert "Scanned/image-only" in scanned.json()["detail"]

    monkeypatch.setattr(api, "create_upload", lambda **_kwargs: (_ for _ in ()).throw(
        UploadConflictError("Identical content already exists; no rows were changed."),
    ))
    duplicate = library_client.post(
        "/api/documents", headers=_auth(), files={"file": ("notes.txt", b"some text")},
    )
    assert duplicate.status_code == 409
    assert "no rows were changed" in duplicate.json()["detail"]

    monkeypatch.setattr(api, "create_upload", lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("private database detail"),
    ))
    failed = library_client.post(
        "/api/documents", headers=_auth(), files={"file": ("notes.txt", b"some text")},
    )
    assert failed.status_code == 503
    assert "private database detail" not in failed.text

    too_large = library_client.post(
        "/api/documents", headers=_auth(),
        files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))},
    )
    assert too_large.status_code == 413


def test_library_page_keeps_token_in_memory_and_avoids_html_injection(library_client):
    page = library_client.get("/library")
    assert page.status_code == 200
    for dom_id in (
        "auth-form", "admin-token", "auth-status", "library", "document-form",
        "document-file", "document-title", "chunking-strategy", "upload-button",
        "replace-button", "clear-selection", "logout-button", "document-list",
        "inspection", "inspection-meta", "inspection-text",
    ):
        assert f'id="{dom_id}"' in page.text
    assert "Document library" in page.text
    assert "localStorage" not in page.text and "sessionStorage" not in page.text
    assert "textContent" in page.text and "innerHTML" not in page.text
    assert 'type="password"' in page.text
    assert 'tokenInput.value = ""' in page.text
    assert 'name="Authorization"' not in page.text
    assert 'id="auth-form"' in page.text
    assert 'id="auth-hint"' in page.text
    assert "authForm.hidden = true" in page.text and "authForm.hidden = false" in page.text
    assert 'authPanel.classList.add("is-unlocked")' in page.text
    assert "Use Lock library to sign out." in page.text
    assert 'prefers-reduced-motion: reduce' in page.text
    assert "select option:checked" in page.text
