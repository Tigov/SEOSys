"""Password hashing (argon2id) and the password rules from NIST SP 800-63B: length and a blocklist, no
composition rules."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128
BLOCKLIST = Path(__file__).resolve().parent.parent / "data" / "common-passwords.txt"
SEQUENCES = ("01234567890", "abcdefghijklmnopqrstuvwxyz", "qwertyuiop", "asdfghjkl", "zxcvbnm")

_hasher = PasswordHasher()  # argon2id with the library's current recommended parameters


def hash(password: str) -> str:  # noqa: A001 - reads naturally as passwords.hash(...)
    return _hasher.hash(password)


def verify(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        burn_time(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


def burn_time(password: str) -> None:
    """Spend the same time as a real check, so an unknown email can't be told apart by response time."""
    try:
        _hasher.verify(DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


@lru_cache(maxsize=1)
def _blocklist() -> frozenset[str]:
    lines = BLOCKLIST.read_text(encoding="utf-8").splitlines() if BLOCKLIST.exists() else []
    return frozenset(l.strip().lower() for l in lines if l.strip() and not l.startswith("#"))


def _is_sequence(text: str) -> bool:
    return any(text in seq or text in seq[::-1] for seq in SEQUENCES)


def problem(password: str, email: str = "") -> str | None:
    """Why this password can't be used, in words for the person choosing it. None if it's fine."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    lowered = password.lower()
    core = re.sub(r"[\d\W_]+$", "", re.sub(r"^[\d\W_]+", "", lowered))
    blocked = _blocklist()
    if lowered in blocked or core in blocked or len(set(lowered)) <= 2 or _is_sequence(lowered):
        return "This password is too common or easy to guess. Try a short sentence or a few unrelated words."
    name = email.split("@")[0].lower()
    if len(name) >= 3 and name in lowered:
        return "Don't include your email address in your password."
    return None
