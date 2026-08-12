"""Fail-closed database and role identity checks for restore verification."""

import psycopg


def connection_identity_problems(
    conn: psycopg.Connection,
    expected_database: str,
    expected_role: str,
) -> list[str]:
    row = conn.execute(
        "SELECT current_database(), current_user, session_user, system_user"
    ).fetchone()
    actual_database = str(row[0])
    actual_role = str(row[1])
    authenticated_role = str(row[2])
    system_authentication = None if row[3] is None else str(row[3])
    problems: list[str] = []
    if actual_database != expected_database:
        problems.append(
            f"database identity mismatch: expected {expected_database}, got {actual_database}"
        )
    if actual_role != expected_role:
        problems.append(f"role identity mismatch: expected {expected_role}, got {actual_role}")
    if authenticated_role != expected_role:
        problems.append(
            "authenticated role identity mismatch: "
            f"expected {expected_role}, got {authenticated_role}"
        )
    auth_method, separator, authentication_identity = (
        system_authentication or ""
    ).partition(":")
    if not auth_method or not separator or authentication_identity != expected_role:
        problems.append(
            "system authentication identity mismatch: "
            f"expected {expected_role}, got {system_authentication or 'NULL'}"
        )
    return problems


def dsn_identity_problems(
    dsn: str,
    expected_database: str,
    expected_role: str,
) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return connection_identity_problems(conn, expected_database, expected_role)
