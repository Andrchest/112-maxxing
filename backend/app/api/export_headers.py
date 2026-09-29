"""`Content-Disposition` for the CSV/Excel/PDF export endpoints (I7 E46b, owner item 6).

A Russian file name is outside `Content-Disposition`'s plain `filename="..."` grammar (RFC 6266
§4.3 restricts it to ISO-8859-1), so every export here sends the pair the RFC recommends: a
Russian-safe ASCII fallback for a client that reads only `filename`, plus `filename*` (RFC 5987,
percent-encoded UTF-8) for the one every modern browser actually uses.
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["content_disposition"]


def content_disposition(filename_ru: str, filename_ascii: str) -> str:
    return f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{quote(filename_ru)}"
