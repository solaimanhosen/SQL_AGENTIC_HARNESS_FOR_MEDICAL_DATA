"""Password hashing with scrypt from the standard library, so no extra dependency is needed.

A stored hash names its parameters, `scrypt$n$r$p$salt$key` in base64, so the cost can be
raised later without breaking passwords set before. Comparison is constant-time, and checking
an account that does not exist costs the same as checking one that does.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from functools import lru_cache

MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_CHARS = 128

# 2^15 iterations with r=8 needs 32 MB and takes tens of milliseconds: slow for a guesser,
# fine for a person. Tests lower it through COST.
COST = (2**15, 8, 1)
_KEY_BYTES = 32
_SALT_BYTES = 16


class PasswordRejected(ValueError):
    """The password does not meet the rules."""


def check_rules(password: str) -> None:
    """Raise PasswordRejected unless the password is long enough and not too long.

    Length is the rule that matters. Composition rules add little, and NIST 800-63B advises
    against them.
    """
    if len(password) < MIN_PASSWORD_CHARS:
        raise PasswordRejected(f"A password needs at least {MIN_PASSWORD_CHARS} characters.")
    if len(password) > MAX_PASSWORD_CHARS:
        raise PasswordRejected(f"A password can have at most {MAX_PASSWORD_CHARS} characters.")


def hash_password(password: str) -> str:
    n, r, p = COST
    salt = os.urandom(_SALT_BYTES)
    key = _derive(password, salt, n, r, p)
    return f"scrypt${n}${r}${p}${_encode(salt)}${_encode(key)}"


def verify_password(password: str, stored: str | None) -> bool:
    """True if the password matches. With no stored hash, the same work is done and False returned."""
    if stored is None:
        verify_password(password, _dummy_hash())
        return False
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(key)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # maxmem must exceed 128 * n * r * p, or OpenSSL refuses the parameters.
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=256 * n * r * p, dklen=_KEY_BYTES
    )


def _encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@lru_cache(maxsize=4)
def _dummy_for(cost: tuple[int, int, int]) -> str:
    return hash_password("not a real password, only spends the same time")


def _dummy_hash() -> str:
    return _dummy_for(COST)
