"""Live local operator confirmation, bound to a single production operation."""

import os
import sys
from dataclasses import dataclass

from .adoption_inventory import AdoptionError
from .adoption_operation import OperationManifest, encode_operation

ACTIONS = ("ADOPT", "INVERSE")
FORBIDDEN_ENVIRONMENT = ("AVELREN_DATABASE_TEST", "AVELREN_ADOPTION_TEST_FAILPOINT")


@dataclass(frozen=True)
class Confirmation:
    action: str
    operation_id: str
    target_digest: str
    plan_digest: str


def _expected(action: str, manifest: OperationManifest) -> Confirmation:
    if action not in ACTIONS:
        raise AdoptionError("operator_action")
    encode_operation(manifest)
    return Confirmation(action, manifest.operation_id, manifest.target_digest, manifest.plan_digest)


def confirm_operator(action: str, manifest: OperationManifest) -> Confirmation:
    confirmation = _expected(action, manifest)
    if sys.platform != "linux" or os.geteuid() != 0:
        raise AdoptionError("operator_platform")
    if any(name in os.environ for name in FORBIDDEN_ENVIRONMENT):
        raise AdoptionError("production_test_environment")
    phrase = f"{action} {manifest.target_digest} {manifest.plan_digest}"
    try:
        # Separate streams support the non-seekable controlling terminal. Text
        # update mode (r+) would require a seekable BufferedRandom device.
        with (
            open("/dev/tty", encoding="utf-8") as reader,
            open("/dev/tty", "w", encoding="utf-8") as writer,
        ):
            if not reader.isatty() or not writer.isatty():
                raise AdoptionError("operator_tty")
            writer.write(f"Confirm operation {manifest.operation_id}: type {phrase}\n")
            writer.flush()
            response = reader.readline(len(phrase) + 2)
    except (OSError, UnicodeError):
        raise AdoptionError("operator_tty") from None
    if response != phrase + "\n":
        raise AdoptionError("operator_confirmation")
    return confirmation


def verify_confirmation(
    confirmation: Confirmation, action: str, manifest: OperationManifest
) -> None:
    if not isinstance(confirmation, Confirmation) or confirmation != _expected(action, manifest):
        raise AdoptionError("operator_confirmation")
