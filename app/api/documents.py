"""Authenticated API for owner-managed uploads; source corpus rows stay protected."""

from __future__ import annotations

import hmac
import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.config import Settings
from app.db.managed_uploads import (
    SharedDocumentError,
    UploadConflictError,
    UploadNotFoundError,
)
from app.ingestion.managed_documents import (
    UploadInputError,
    create_upload,
    inspect_upload,
    list_uploads,
    remove_upload,
    replace_upload,
)
from app.ingestion.parsers import (
    MAX_UPLOAD_BYTES,
    DocumentParseError,
    UnsupportedScannedPdfError,
)


logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/documents", tags=["documents"])
ChunkingStrategy = Literal["paragraph", "fixed_overlap"]


def _settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else Settings.load()


async def require_admin(request: Request) -> None:
    """Require a configured bearer secret and compare it without timing leaks."""
    expected = _settings(request).admin_token
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="Document management is unavailable until a strong administrator token is configured.",
        )
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if (not separator or scheme.lower() != "bearer" or not supplied
            or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))):
        raise HTTPException(
            status_code=401,
            detail="Administrator authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


Admin = Annotated[None, Depends(require_admin)]


@router.get("")
async def list_documents(
    _admin: Admin,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> dict[str, object]:
    try:
        rows = await run_in_threadpool(list_uploads, limit=limit, offset=offset)
        return {"documents": rows, "limit": limit, "offset": offset}
    except Exception as exc:
        logger.error("document_list_failed error_type=%s", type(exc).__name__)
        raise _storage_unavailable() from None


@router.post("", status_code=201)
async def upload_document(
    request: Request,
    _admin: Admin,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form(max_length=300)] = None,
    chunking_strategy: Annotated[ChunkingStrategy, Form()] = "paragraph",
) -> dict[str, object]:
    content = await _read_upload(file)
    try:
        result = await run_in_threadpool(
            create_upload,
            filename=file.filename,
            content=content,
            title=title,
            chunking_strategy=chunking_strategy,
            model=getattr(request.app.state, "embedding_model", None),
        )
        return {"document": result, "message": "Document uploaded and indexed."}
    except (DocumentParseError, UploadInputError, UploadConflictError) as exc:
        raise _parse_or_conflict_error(exc) from None
    except Exception as exc:
        logger.error("document_upload_failed error_type=%s", type(exc).__name__)
        raise _storage_unavailable() from None
    finally:
        await file.close()


@router.get("/{upload_id}")
async def inspect_document(upload_id: UUID, _admin: Admin) -> dict[str, object]:
    try:
        document = await run_in_threadpool(inspect_upload, upload_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Managed document not found.")
        return {"document": document}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("document_inspect_failed error_type=%s", type(exc).__name__)
        raise _storage_unavailable() from None


@router.put("/{upload_id}")
async def update_document(
    upload_id: UUID,
    request: Request,
    _admin: Admin,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str | None, Form(max_length=300)] = None,
    chunking_strategy: Annotated[ChunkingStrategy, Form()] = "paragraph",
) -> dict[str, object]:
    content = await _read_upload(file)
    try:
        result = await run_in_threadpool(
            replace_upload,
            upload_id=upload_id,
            filename=file.filename,
            content=content,
            title=title,
            chunking_strategy=chunking_strategy,
            model=getattr(request.app.state, "embedding_model", None),
        )
        return {"document": result, "message": "Managed document replaced."}
    except UploadNotFoundError:
        raise HTTPException(status_code=404, detail="Managed document not found.") from None
    except (DocumentParseError, UploadInputError, UploadConflictError) as exc:
        raise _parse_or_conflict_error(exc) from None
    except Exception as exc:
        logger.error("document_update_failed error_type=%s", type(exc).__name__)
        raise _storage_unavailable() from None
    finally:
        await file.close()


@router.delete("/{upload_id}", status_code=204)
async def delete_document(upload_id: UUID, _admin: Admin) -> Response:
    try:
        deleted = await run_in_threadpool(remove_upload, upload_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Managed document not found.")
        return Response(status_code=204)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("document_delete_failed error_type=%s", type(exc).__name__)
        raise _storage_unavailable() from None


async def _read_upload(file: UploadFile) -> bytes:
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
    except Exception:
        await file.close()
        raise HTTPException(status_code=400, detail="The uploaded file could not be read.") from None
    if len(content) > MAX_UPLOAD_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="The file exceeds the 5 MiB upload limit.")
    return content


def _parse_or_conflict_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UnsupportedScannedPdfError):
        return HTTPException(status_code=415, detail=str(exc))
    if isinstance(exc, DocumentParseError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, SharedDocumentError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UploadConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UploadInputError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail="The uploaded document could not be processed.")


def _storage_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Document storage is temporarily unavailable. No partial changes were saved.",
    )
