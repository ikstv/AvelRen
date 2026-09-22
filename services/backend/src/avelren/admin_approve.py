"""Host-side approval of an independently verified installation; never an HTTP endpoint."""

import argparse
import getpass
from uuid import UUID

import psycopg

from .admin_pin import hash_pin
from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device_id", type=UUID)
    parser.add_argument("--set-pin", action="store_true")
    args = parser.parse_args()
    encoded = None
    if args.set_pin:
        pin = getpass.getpass("PIN: ")
        if pin != getpass.getpass("Repeat PIN: "):
            parser.error("PIN confirmation differs")
        encoded = hash_pin(pin)
    with psycopg.connect(settings.database_dsn) as conn:
        row = conn.execute(
            "SELECT pin_hash FROM admin_access WHERE singleton FOR UPDATE"
        ).fetchone()
        if row is None or (not row[0] and encoded is None):
            parser.error("Set up a PIN with --set-pin first")
        device = conn.execute(
            "SELECT fcm_token IS NOT NULL FROM devices WHERE id=%s FOR UPDATE",
            (args.device_id,),
        ).fetchone()
        if device is None or not device[0]:
            parser.error("Installation must exist and have a notification token")
        conn.execute(
            "UPDATE admin_access SET approved_device_id=%s, pin_hash=coalesce(%s,pin_hash) "
            "WHERE singleton", (args.device_id, encoded),
        )
    print("Installation approved; attempts and lockout preserved. PIN entry still required.")


if __name__ == "__main__":
    main()
