import re
import unicodedata

PUNCTUATION_RE = re.compile(r"[\s!！_\-‐‑‒–—―・/\\.,:;()\[\]{}「」『』【】]")


def normalize_card_number(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.upper()
    text = PUNCTUATION_RE.sub("", text)
    return text


def base_number(value: str | None) -> str:
    normalized = normalize_card_number(value)
    return re.sub(r"(R\+|L\+|PE\+|[A-Z]+)$", "", normalized)

