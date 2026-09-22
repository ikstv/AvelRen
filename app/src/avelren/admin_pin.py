"""PIN verification and lock policy, independent of HTTP and storage."""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_ATTEMPTS = 3
LOCK_DURATION = timedelta(hours=24)


def hash_pin(pin: str) -> str:
    if len(pin) != 4 or any(c not in "0123456789" for c in pin):
        raise ValueError("PIN must contain exactly four ASCII digits")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    if len(pin) != 4 or any(c not in "0123456789" for c in pin):
        return False
    try:
        version, salt_hex, digest_hex = encoded.split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if version != "scrypt-v1" or len(salt) != 16 or len(expected) != 32:
            return False
    except ValueError:
        return False
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest, expected)


@dataclass(frozen=True)
class Attempt:
    state: str
    failures: int
    locked_until: datetime | None

    @property
    def remaining(self) -> int:
        return max(0, MAX_ATTEMPTS - self.failures)


def evaluate_attempt(
    failures: int, locked_until: datetime | None, now: datetime, matches: bool,
) -> Attempt:
    if locked_until is not None and locked_until > now:
        return Attempt("blocked", MAX_ATTEMPTS, locked_until)
    if locked_until is not None:
        failures = 0
    if matches:
        return Attempt("authorized", 0, None)
    failures += 1
    if failures >= MAX_ATTEMPTS:
        return Attempt("blocked", MAX_ATTEMPTS, now + LOCK_DURATION)
    return Attempt("invalid_pin", failures, None)
