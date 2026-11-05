"""What may leave the trusted side.

Projection copies named fields only, so raw records never pass through whole. This is the second
line: a scan of everything about to be published, which refuses rather than redacts. A bundle that
trips it is not exported, because silently editing evidence is worse than not showing it.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from typing import cast

from moody_blues.contracts.common import ErrorCategory, MoodyBluesError
from moody_blues.contracts.explorer import BoundedText

MAX_MESSAGE_CHARS = 4_000
MAX_NOTE_CHARS = 1_500
MAX_CODE_CHARS = 16_000
MAX_JSON_CHARS = 2_000
MAX_BUNDLE_BYTES = 1_500_000

# An absolute path, a home directory, or a key-shaped string. Deliberately broad: false positives
# stop an export and get looked at, while false negatives publish something.
_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("absolute_path", re.compile(r"(?<![\w.])/(?:Users|home|private|root|var/folders|tmp|etc)/")),
    ("windows_path", re.compile(r"[A-Za-z]:\\[A-Za-z]")),
    ("artifact_path", re.compile(r"\.artifacts/")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{8,}")),
    ("api_key_shape", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("env_setting", re.compile(r"\bMOODY_[A-Z_]+\s*=")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


class EvidenceRefusedError(MoodyBluesError):
    def __init__(self, reason: str) -> None:
        super().__init__(ErrorCategory.EVIDENCE_INTEGRITY, f"evidence refused: {reason}")
        self.reason = reason


def bounded(text: str, limit: int) -> BoundedText:
    return BoundedText(
        text=text[:limit],
        truncated=len(text) > limit,
        original_chars=len(text),
        sha256=hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest(),
    )


def scan(text: str, *, secrets: Iterable[str] = ()) -> list[str]:
    """Names of every forbidden pattern found. Empty means clean. Never returns the match."""
    hits = [name for name, pattern in _FORBIDDEN if pattern.search(text)]
    if any(secret and secret in text for secret in secrets):
        hits.append("configured_secret")
    return hits


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in cast(dict[object, object], value).items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _strings(item)


def require_clean(rendered_json: str, *, secrets: Iterable[str] = ()) -> None:
    """Scan decoded strings. Scanning the escaped text would read ``a:\\nb`` as a Windows path."""
    known = tuple(secrets)
    hits = {hit for s in _strings(json.loads(rendered_json)) for hit in scan(s, secrets=known)}
    if hits:
        raise EvidenceRefusedError(f"forbidden content: {', '.join(sorted(hits))}")
