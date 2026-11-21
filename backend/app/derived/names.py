"""Stop-name normalisation shared by clustering, search and the alias loader. Pure and deterministic."""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalise(text: str | None) -> str:
    """NFKC, case-fold, punctuation/symbols/brackets -> space, collapse whitespace.

    Combining marks are kept on purpose: stripping them would destroy Devanagari. The raw name is always kept
    separately for display; this value is only for matching and grouping.
    """
    s = unicodedata.normalize("NFKC", text or "").casefold()
    s = "".join(" " if unicodedata.category(ch)[0] in "PSZC" else ch for ch in s)   # P*, S*, Z* (spaces), C* (control)
    return _WS.sub(" ", s).strip()


def tokens(text: str | None) -> list[str]:
    n = normalise(text)
    return n.split(" ") if n else []
