"""Policy linter (FDD BR-1, BR-3): blocks promises and tactics the business never offers."""
from __future__ import annotations

import re

BANNED_PATTERNS = {
    r"\bguarantee\w*|\bguaranty\b": "No guarantees of rankings or results (BR-3)",
    r"#\s?1(?:st)?\b|\bno\.?\s?1\b|\bnumber[- ]one\b|\brank(?:ed|s|ing)? (?:first|#?\s?1|top)\b|\btop (?:spot|position) on google\b":
        "No #1 ranking promises (BR-3)",
    r"\bgoogle[- ]partner\b|\bendorsed by google\b": "No claims of Google endorsement (BR-3)",
    r"\bbuy (?:back)?links?\b|\bpaid links?\b|\bpbn\b": "No paid or scheme links (BR-1)",
}


def lint(text: str) -> list[str]:
    """Return a list of policy violations found in outbound text."""
    return [reason for pattern, reason in BANNED_PATTERNS.items() if re.search(pattern, text or "", re.I)]
