"""Bounded text extraction for supported owner-managed upload formats."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from pathlib import PurePosixPath
from typing import Any
import unicodedata
from zipfile import BadZipFile, ZipFile

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 200_000
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_DOCX_ARCHIVE_ENTRIES = 2_000
MAX_PDF_PAGES = 200
MAX_FILENAME_CHARS = 255
MAX_TITLE_CHARS = 300
_MARKDOWN_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


class DocumentParseError(ValueError):
    """A supported file could not be safely converted to usable text."""


class UnsupportedScannedPdfError(DocumentParseError):
    """The PDF has no extractable text and would require OCR."""


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    title: str
    file_format: str
    file_size_bytes: int
    parser_metadata: dict[str, Any]


def safe_original_filename(filename: str | None) -> str:
    """Keep only a display name; never use an uploaded path on the filesystem."""
    if not isinstance(filename, str) or not filename.strip():
        raise DocumentParseError("Choose a file with a valid filename.")
    basename = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if (not basename or len(basename) > MAX_FILENAME_CHARS
            or any(unicodedata.category(char).startswith("C") for char in basename)):
        raise DocumentParseError("The filename is invalid or too long.")
    return basename


def parse_uploaded_document(
    filename: str | None,
    content: bytes,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> ParsedDocument:
    """Extract UTF-8 text and useful metadata from PDF, DOCX, TXT, or Markdown."""
    original_filename = safe_original_filename(filename)
    if not isinstance(content, bytes):
        raise DocumentParseError("The uploaded file could not be read.")
    if not content:
        raise DocumentParseError("The uploaded file is empty.")
    if len(content) > max_upload_bytes:
        raise DocumentParseError("The file exceeds the 5 MiB upload limit.")

    extension = PurePosixPath(original_filename).suffix.lower()
    file_format = {".txt": "txt", ".md": "md", ".pdf": "pdf", ".docx": "docx"}.get(extension)
    if file_format is None:
        raise DocumentParseError("Supported file types are PDF, DOCX, TXT, and MD.")

    title = PurePosixPath(original_filename).stem.strip() or "Untitled document"
    metadata: dict[str, Any] = {"title_source": "filename"}
    if file_format in {"txt", "md"}:
        text = _decode_utf8(content)
        if file_format == "md":
            heading = _MARKDOWN_HEADING.search(text)
            if heading:
                title = _clean_title(heading.group(1)) or title
                metadata["title_source"] = "markdown_heading"
        metadata["encoding"] = "utf-8"
    elif file_format == "docx":
        text, title, metadata = _parse_docx(content, title)
    else:
        text, title, metadata = _parse_pdf(content, title)

    _validate_extracted_text(text)
    return ParsedDocument(
        text=text,
        title=_clean_title(title) or "Untitled document",
        file_format=file_format,
        file_size_bytes=len(content),
        parser_metadata=metadata,
    )


def _decode_utf8(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentParseError("Text and Markdown files must be UTF-8 encoded.") from None
    if "\x00" in text:
        raise DocumentParseError("The file contains binary data, not plain text.")
    return text


def _parse_docx(content: bytes, filename_title: str) -> tuple[str, str, dict[str, Any]]:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ARCHIVE_ENTRIES:
                raise DocumentParseError("The DOCX package contains too many entries.")
            uncompressed_size = sum(entry.file_size for entry in entries)
            if uncompressed_size > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentParseError("The DOCX package expands beyond the 20 MiB limit.")
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentParseError("The DOCX file is malformed or incomplete.")
        document = Document(BytesIO(content))
    except DocumentParseError:
        raise
    except Exception:
        raise DocumentParseError("The DOCX file is malformed or could not be read.") from None

    try:
        blocks: list[str] = []
        extracted_chars = 0
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                if block.text.strip():
                    blocks.append(block.text)
                    extracted_chars += len(block.text)
            elif isinstance(block, Table):
                for row in block.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        row_text = "\t".join(cells)
                        blocks.append(row_text)
                        extracted_chars += len(row_text)
            if extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                raise DocumentParseError("Extracted text exceeds the 200,000-character limit.")

        props = document.core_properties
        title = _clean_title(props.title or "") or filename_title
        metadata = {
            key: value for key, value in {
                "author": props.author,
                "subject": props.subject,
                "created": props.created.isoformat() if props.created else None,
                "modified": props.modified.isoformat() if props.modified else None,
                "title_source": "docx_core_properties" if props.title else "filename",
            }.items() if value
        }
    except DocumentParseError:
        raise
    except Exception:
        raise DocumentParseError("The DOCX file contains malformed document content.") from None
    return "\n\n".join(blocks), title, metadata


def _parse_pdf(content: bytes, filename_title: str) -> tuple[str, str, dict[str, Any]]:
    if b"%PDF-" not in content[:1024]:
        raise DocumentParseError("The PDF header is missing or malformed.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise DocumentParseError("Password-protected PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count < 1 or page_count > MAX_PDF_PAGES:
            raise DocumentParseError("PDFs must contain between 1 and 200 pages.")
        page_texts = []
        extracted_chars = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            extracted_chars += len(page_text)
            if extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                raise DocumentParseError("Extracted text exceeds the 200,000-character limit.")
            page_texts.append(page_text)
        metadata = reader.metadata
    except DocumentParseError:
        raise
    except Exception:
        raise DocumentParseError("The PDF is malformed or could not be read.") from None

    text = "\n\n".join(page_text.strip() for page_text in page_texts if page_text.strip())
    if not text.strip():
        raise UnsupportedScannedPdfError(
            "This PDF has no extractable text. Scanned/image-only PDFs are unsupported; "
            "upload a text-based PDF or OCR it first."
        )
    raw_title = str(metadata.title).strip() if metadata and metadata.title else ""
    title = _clean_title(raw_title) or filename_title
    try:
        creation_date = metadata.creation_date.isoformat() if metadata and metadata.creation_date else None
    except Exception:
        creation_date = None
    values = {
        "author": str(metadata.author).strip() if metadata and metadata.author else None,
        "creator": str(metadata.creator).strip() if metadata and metadata.creator else None,
        "creation_date": creation_date,
        "page_count": page_count,
        "title_source": "pdf_metadata" if raw_title else "filename",
    }
    return text, title, {key: value for key, value in values.items() if value}


def _clean_title(value: str) -> str:
    cleaned = " ".join(value.split())
    if (len(cleaned) > MAX_TITLE_CHARS
            or any(unicodedata.category(char).startswith("C") for char in cleaned)):
        return ""
    return cleaned


def _validate_extracted_text(text: str) -> None:
    if not text.strip():
        raise DocumentParseError("The document contains no usable text.")
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise DocumentParseError("Extracted text exceeds the 200,000-character limit.")
    if "\x00" in text:
        raise DocumentParseError("Extracted text contains unsupported binary characters.")
