"""The upload allow-list and its content types (HLD 71 §71.11, ТЗ ¶387 «DOCX для методических
материалов», ¶370 «PDF для документации», ¶386).

The stored `content_type` is derived from the file's extension, never trusted from the client's
`Content-Type` header (SPEC §41: input from the caller is not authoritative for what a byte stream
"is"). `extension_of` reads the extension the same way for the allow-list check and for the stored
value, so a `.PDF` upload and a `.pdf` upload can never disagree about either.
"""

from __future__ import annotations

__all__ = ["ALLOWED_EXTENSIONS", "content_type_of", "extension_of"]

#: ТЗ ¶387/¶370/¶386's accepted types, HLD 71 §71.11's allow-list, literally.
_CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
    "md": "text/markdown",
    "png": "image/png",
    "jpg": "image/jpeg",
    # Not named by §71.11's list, which spells only "jpg" — accepted as the same type since a
    # browser's own file picker offers both extensions for one format (this task's technical call,
    # not a widening of the organizer allow-list).
    "jpeg": "image/jpeg",
}

ALLOWED_EXTENSIONS: frozenset[str] = frozenset(_CONTENT_TYPE_BY_EXTENSION)


def extension_of(file_name: str) -> str:
    """The lowercase extension without its dot; `""` for a name with none."""
    _, dot, suffix = file_name.rpartition(".")
    return suffix.lower() if dot else ""


def content_type_of(extension: str) -> str | None:
    """The stored `content_type` for an allowed extension; `None` for one that is not allowed."""
    return _CONTENT_TYPE_BY_EXTENSION.get(extension)
