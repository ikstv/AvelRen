"""Mark a device as an admin — the supported path, instead of a hand-written UPDATE.

`is_admin` decides who the watchdog can reach. Until now nothing set it: the
column had readers everywhere and no writer anywhere, so the only way to fill it
was `UPDATE devices SET is_admin = true` typed against production by hand
(issue #112). An operation with no tooling is an operation nobody does, and the
result is measurable — on production today: 71 devices, 1 admin, and **zero**
admins carrying an FCM token, while 65 ordinary devices carry one. The watchdog
has nobody to warn, and that is a channel which fails silently by construction:
the alert it cannot deliver is the alert saying something is wrong.

This is a host-side command, not an HTTP endpoint, and that is deliberate. Any
endpoint able to grant admin needs a second secret to guard it, and a wrong guard
there hands an attacker the health channel. Running here requires shell access to
the production host, which is the trust boundary the operator already crosses to
deploy — so the capability adds no new attack surface at all.

    docker compose run --rm --no-deps -e DATABASE_URL=... api \\
        python -m avelren.admin_enroll --list
    ... python -m avelren.admin_enroll <device-id>
    ... python -m avelren.admin_enroll <device-id> --revoke

Requires a DSN allowed to write `devices.is_admin`. The runtime service roles are
not: this is an admin/migrator operation by design (see README, PostgreSQL roles).
"""

import argparse
import logging
import sys

import psycopg
from psycopg.rows import dict_row

from .config import settings

log = logging.getLogger("avelren.admin_enroll")

# A promoted device without a token is the exact shape of the current production
# failure: is_admin says the channel exists, and nothing can be delivered to it.
NO_TOKEN_WARNING = (
    "device %s is now an admin but has NO fcm_token — it cannot receive health "
    "alerts. Open the app on that device so it registers a token, then re-check "
    "with --list."
)


def _channel_size(conn) -> int:
    """Admins the watchdog can actually reach — the number that matters.

    Counting `is_admin` alone would report a healthy channel in precisely the
    state that broke: an admin with no token is a subscriber to nothing.
    """
    row = conn.execute(
        "SELECT count(*) AS n FROM devices WHERE is_admin AND fcm_token IS NOT NULL"
    ).fetchone()
    return row["n"]


def list_devices(conn, limit: int) -> int:
    rows = conn.execute(
        """
        SELECT id, is_admin, fcm_token IS NOT NULL AS has_token, platform, last_seen
        FROM devices
        ORDER BY last_seen DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()

    if not rows:
        print("no devices registered")
        return 0

    print(f"{'device id':38} {'admin':6} {'token':6} {'platform':9} last seen")
    for r in rows:
        print(
            f"{str(r['id']):38} "
            f"{'yes' if r['is_admin'] else '-':6} "
            f"{'yes' if r['has_token'] else '-':6} "
            f"{r['platform']:9} "
            f"{r['last_seen']:%Y-%m-%d %H:%M}"
        )
    print(f"\nreachable admin channel: {_channel_size(conn)} device(s)")
    return 0


def set_admin(conn, device_id: str, admin: bool) -> int:
    row = conn.execute(
        """
        UPDATE devices SET is_admin = %s
        WHERE id = %s
        RETURNING id, is_admin, fcm_token IS NOT NULL AS has_token
        """,
        (admin, device_id),
    ).fetchone()

    if row is None:
        log.error("no device with id %s — run --list to see the registered ones", device_id)
        return 1

    log.info("device %s: is_admin=%s", row["id"], row["is_admin"])
    if admin and not row["has_token"]:
        log.warning(NO_TOKEN_WARNING, row["id"])

    reachable = _channel_size(conn)
    log.info("reachable admin channel: %s device(s)", reachable)
    # Revoking the last reachable admin is legitimate (a lost phone), but it
    # leaves the watchdog mute, and that must be said out loud rather than
    # discovered the next time something breaks.
    if reachable == 0:
        log.warning(
            "the admin alert channel is now EMPTY — the watchdog has nobody to "
            "warn about stale data or a stale backup"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(prog="avelren.admin_enroll", description=__doc__)
    parser.add_argument("device_id", nargs="?", help="device UUID to promote")
    parser.add_argument(
        "--revoke", action="store_true", help="clear is_admin instead of setting it"
    )
    parser.add_argument("--list", action="store_true", help="show devices and the channel size")
    parser.add_argument("--limit", type=int, default=20, help="rows for --list (default 20)")
    args = parser.parse_args(argv)

    if args.list == bool(args.device_id):
        parser.error("give exactly one of: a device id, or --list")

    with psycopg.connect(settings.database_dsn, autocommit=False) as conn:
        conn.row_factory = dict_row
        if args.list:
            return list_devices(conn, args.limit)
        return set_admin(conn, args.device_id, admin=not args.revoke)


if __name__ == "__main__":
    sys.exit(main())
