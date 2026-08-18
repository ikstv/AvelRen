"""PR-B — expansion of `/admin/telemetry`: services, docker, inodes, upstream,
last_collector_run/success, version.

The core invariant is the same as in PR-A:
**a missing field = null, not "a healthy server with zeros"**.

Plus a security regression: `services()` must not expose anything outside the
whitelist, even if the host script accidentally writes an extra field.
"""

import json
from datetime import UTC, datetime

import pytest

from avelren import telemetry


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "host.json"
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)

    def write(payload: dict, *, collected_at: datetime | None = None) -> None:
        if collected_at is not None:
            payload = {
                **payload,
                "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        path.write_text(json.dumps(payload), encoding="utf-8")

    return write


# ============================================================================
# services() — a pure function on the snapshot, security-critical
# ============================================================================

def test_services_returns_empty_when_snapshot_missing(tmp_path, monkeypatch):
    """No snapshot — not an exception, not "healthy services", but empty. The
    client renders it as ⚪ Unknown, rather than hiding a monitoring failure."""
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    assert telemetry.services() == []


def test_services_returns_whitelisted_fields(snapshot):
    snapshot(
        {
            "services": [
                {
                    "name": "api",
                    "status": "running",
                    "health": "healthy",
                    "started_at": "2026-08-01T00:00:00Z",
                    "restart_count": 0,
                    "exit_code": None,
                    "oom_killed": False,
                    "image": "avelren-app:latest",
                }
            ]
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.services()
    assert len(result) == 1
    assert result[0]["name"] == "api"
    assert result[0]["status"] == "running"
    assert result[0]["health"] == "healthy"


def test_services_strips_fields_outside_whitelist(snapshot):
    """Security regression: if the host script accidentally adds a field outside
    the whitelist (env, mounts, cmd, ports), telemetry MUST drop it. Without this,
    one careless edit in deploy/ opens a channel for leaking secrets.

    N2 (review PR #34): previously the test checked only a few known forbidden
    keys. Now a positive allowlist: `entry.keys() ⊆ {"name"} ∪ ALLOWED`. This makes
    the regression mutation-safe — even if the injected field does not match the
    blacklist (e.g. a future `secrets_path`), the test fails."""
    snapshot(
        {
            "services": [
                {
                    "name": "api",
                    "status": "running",
                    "health": "healthy",
                    # Extra fields that could theoretically come from docker inspect.
                    "env": ["DATABASE_URL=postgres://user:secret@db/avelren"],
                    "mounts": ["/secrets:/secrets:ro"],
                    "cmd": ["python", "-m", "avelren.api"],
                    "network_settings": {"IPAddress": "10.0.0.5"},
                    "labels": {"com.docker.compose.project": "avelren"},
                    # A field not in the current blacklist — exactly the scenario
                    # the positive allowlist catches and the negative one misses.
                    "secrets_path": "/run/secrets/firebase.json",
                }
            ]
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.services()
    assert len(result) == 1
    entry = result[0]

    # Positive-allowlist invariant: no field outside the allowed set.
    allowed = {"name"} | telemetry._SERVICE_ALLOWED_FIELDS
    extra = set(entry.keys()) - allowed
    assert not extra, f"fields outside the whitelist: {extra}"

    # An explicit check of the typical risky keys — kept for diagnostic
    # readability (the first failure line points specifically at a secrets leak).
    forbidden = {"env", "mounts", "cmd", "network_settings", "labels",
                 "config", "secrets_path"}
    leaked = forbidden & set(entry.keys())
    assert not leaked, f"leak of fields outside the whitelist: {leaked}"


def test_services_whitelist_blocks_unseen_future_field(snapshot):
    """Mutation regression: the test proves that a specific refactor "return the
    whole entry" (e.g. `out.append(dict(entry))`) would be caught. A named scenario
    catches the class of bug, not a specific field name."""
    hypothetical_new_field = "future_docker_inspect_field_2027"
    snapshot(
        {
            "services": [
                {
                    "name": "api",
                    "status": "running",
                    hypothetical_new_field: "should never appear on client",
                }
            ]
        },
        collected_at=datetime.now(UTC),
    )
    entry = telemetry.services()[0]
    assert hypothetical_new_field not in entry, (
        f"the whitelist let through the unknown field {hypothetical_new_field!r} — "
        "exactly the class of regression the positive allowlist protects against"
    )


def test_services_ignores_unknown_container_names(snapshot):
    """Name whitelist: if a container we do not know appears in the snapshot
    (e.g. someone added `postgres-backup-1`), the API will not show it. This
    protects against the scenario "accidentally exposed an internal service on the client"."""
    snapshot(
        {
            "services": [
                {"name": "api", "status": "running"},
                {"name": "some-internal-tool", "status": "running"},
                {"name": "postgres-exporter", "status": "running"},
            ]
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.services()
    assert [s["name"] for s in result] == ["api"]


def test_services_stable_order(snapshot):
    """The UI must receive services in a stable order, otherwise the cards "jump"
    between compositions. The order is by role (db → caddy)."""
    snapshot(
        {
            "services": [
                {"name": "caddy", "status": "running"},
                {"name": "collector", "status": "running"},
                {"name": "db", "status": "running"},
                {"name": "api", "status": "running"},
            ]
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.services()
    assert [s["name"] for s in result] == ["db", "api", "collector", "caddy"]


def test_services_handles_malformed_entry(snapshot):
    """If one row is corrupt (not a dict), the neighbors must survive."""
    snapshot(
        {
            "services": [
                "not a dict",
                {"name": "api", "status": "running"},
                None,
            ]
        },
        collected_at=datetime.now(UTC),
    )
    assert [s["name"] for s in telemetry.services()] == ["api"]


def test_services_handles_non_list_services_block(snapshot):
    """If the whole block is corrupt (not a list) — also [], not an exception."""
    snapshot({"services": {"api": "running"}}, collected_at=datetime.now(UTC))
    assert telemetry.services() == []


def test_services_stopped_container(snapshot):
    """A stopped container must appear precisely as stopped, not be hidden. A
    service disappearing from the UI is a worse state than an honest 🔴 exited."""
    snapshot(
        {
            "services": [
                {
                    "name": "collector",
                    "status": "exited",
                    "health": None,
                    "started_at": "2026-08-01T00:00:00Z",
                    "restart_count": 5,
                    "exit_code": 137,
                    "oom_killed": True,
                    "image": "avelren-app:latest",
                }
            ]
        },
        collected_at=datetime.now(UTC),
    )
    entry = telemetry.services()[0]
    assert entry["status"] == "exited"
    assert entry["oom_killed"] is True
    assert entry["exit_code"] == 137


# ============================================================================
# docker() / inodes() — simple pure functions
# ============================================================================

def test_docker_reads_from_snapshot(snapshot):
    snapshot(
        {"docker": {"daemon_version": "27.0.3", "compose_version": "2.29.1"}},
        collected_at=datetime.now(UTC),
    )
    assert telemetry.docker() == {
        "daemon_version": "27.0.3",
        "compose_version": "2.29.1",
    }


def test_docker_null_when_snapshot_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    assert telemetry.docker() == {"daemon_version": None, "compose_version": None}


def test_inodes_reads_from_snapshot(snapshot):
    snapshot(
        {"inodes": {"total": 2_500_000, "used": 300_000, "used_percent": 12}},
        collected_at=datetime.now(UTC),
    )
    assert telemetry.inodes() == {"total": 2_500_000, "used": 300_000, "used_percent": 12}


def test_inodes_all_null_when_snapshot_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    assert telemetry.inodes() == {"total": None, "used": None, "used_percent": None}


# ============================================================================
# upstream() — reads settings
# ============================================================================

def test_upstream_reads_from_settings():
    """upstream() does not depend on the snapshot — it is pure configuration. The
    client sees which URL the collector fetches, without guessing."""
    result = telemetry.upstream()
    assert "workload_url" in result
    assert "poll_interval_seconds" in result
    assert result["poll_interval_seconds"] == 60


# ============================================================================
# End-to-end via /admin/telemetry (pipeline, last_collector_run, version)
# ============================================================================

def _make_admin(conn, device):
    conn.execute("UPDATE devices SET is_admin = true WHERE id = %s", (device.device_id,))


def test_admin_telemetry_new_blocks_present_and_backward_compatible(
    device, api_client, conn, snapshot
):
    """The existing fields (system/network/pipeline/certificate/backups/problems)
    are in place; the added blocks too. A violation = broke the PR-A client or the
    old APK, so this test is a contract."""
    _make_admin(conn, device)
    snapshot(
        {"system": {"cpu_count": 2}, "services": [], "docker": {}, "inodes": {}},
        collected_at=datetime.now(UTC),
    )

    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 200
    body = r.json()

    # PR-A / the earlier contract — must remain.
    for old in ("system", "network", "pipeline", "certificate", "backups", "problems"):
        assert old in body, f"lost existing field {old}"

    # New PR-B blocks.
    for new in (
        "services", "docker", "inodes", "upstream",
        "last_collector_run", "last_collector_success", "version",
    ):
        assert new in body, f"missing new block {new}"


def test_admin_telemetry_last_collector_run_null_when_empty(
    device, api_client, conn, snapshot
):
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    assert body["last_collector_run"] is None
    assert body["last_collector_success"] is None


def test_admin_telemetry_last_collector_run_returns_latest(
    device, api_client, conn, snapshot
):
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))

    conn.execute("DELETE FROM collector_runs")
    conn.execute(
        "INSERT INTO collector_runs (time, http_status, duration_ms, rows_written, error) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("2026-08-12 10:00:00+00", 200, 120, 38, None),
    )
    conn.execute(
        "INSERT INTO collector_runs (time, http_status, duration_ms, rows_written, error) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("2026-08-12 10:01:00+00", 502, 5000, 0, "upstream 502"),
    )

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    last = body["last_collector_run"]
    assert last["http_status"] == 502
    assert last["error"] == "upstream 502"
    # body_sha256 is deliberately NOT in the response — a technical artifact the
    # client does not need.
    assert "body_sha256" not in last

    success = body["last_collector_success"]
    assert success["http_status"] == 200
    assert success["rows_written"] == 38
    # success has NO error / derived — it is purely "the last success", a simplified set.
    assert "error" not in success


def test_admin_telemetry_version_reads_env_and_migrations(
    device, api_client, conn, snapshot, monkeypatch
):
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    monkeypatch.setenv("AVELREN_GIT_SHA", "abc123def")

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    v = body["version"]
    assert v["app_version"]  # non-empty
    assert v["git_sha"] == "abc123def"
    # migrations_version — max(version) from the DB; in the test DB the migrations
    # are applied, so the string will not be empty (the exact value changes over time).
    assert v["migrations_version"] is not None


def test_admin_telemetry_version_git_sha_null_when_env_missing(
    device, api_client, conn, snapshot, monkeypatch
):
    """Without the env AVELREN_GIT_SHA — git_sha=null, not "unknown"/"dev". The
    client distinguishes "version known, this is dev" from "version simply not set in the build"."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    monkeypatch.delenv("AVELREN_GIT_SHA", raising=False)

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    assert body["version"]["git_sha"] is None


def test_admin_telemetry_upstream_shows_workload_url(
    device, api_client, conn, snapshot
):
    """The dashboard must honestly show where the collector currently fetches from
    — the key figure for "is it eCherha v4 or v5"."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    upstream = body["upstream"]
    assert "workload_url" in upstream
    assert upstream["poll_interval_seconds"] == 60


def test_admin_telemetry_services_still_authenticated(
    device, api_client, conn, snapshot
):
    """The is_admin gate must not weaken after adding the new blocks. A device
    without is_admin=true gets a 403 on the whole endpoint (including the new
    fields). A regression in case someone accidentally moves one of the blocks to
    public — extra eyes."""
    snapshot(
        {"services": [{"name": "api", "status": "running"}]},
        collected_at=datetime.now(UTC),
    )
    # We deliberately do NOT set is_admin.
    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 403


# ============================================================================
# completeness_percent — counts SUCCESSFUL cycles, not attempts (issue #22)
# ============================================================================

def _add_collector_run(conn, minutes_ago: int, *, error: str | None) -> None:
    conn.execute(
        "INSERT INTO collector_runs (time, error) VALUES (now() - make_interval(mins => %s), %s)",
        (minutes_ago, error),
    )


def test_completeness_ignores_failed_cycles(device, api_client, conn, snapshot):
    """Regression for issue #22: when eCherha returns an error every minute,
    collector_runs still fills up, but no observation is collected. Completeness
    must count SUCCESSFUL cycles (error IS NULL), otherwise it shows 100%
    completeness during a total data-collection failure."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    # 60 cycles per hour, but ALL with an error — completeness must be 0, not 100.
    for m in range(60):
        _add_collector_run(conn, m, error="502 Bad Gateway")

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    pipeline = body["pipeline"]
    assert pipeline["runs_last_hour"] == 60
    assert pipeline["errors_last_hour"] == 60
    assert pipeline["successful_runs_last_hour"] == 0
    assert pipeline["completeness_percent"] == 0

    conn.execute("DELETE FROM collector_runs")


def test_completeness_counts_only_successful_cycles(device, api_client, conn, snapshot):
    """A mixed hour: 30 successful + 30 with an error → completeness 50%, not 100%."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    for m in range(30):
        _add_collector_run(conn, m, error=None)
    for m in range(30, 60):
        _add_collector_run(conn, m, error="timeout")

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    pipeline = body["pipeline"]
    assert pipeline["runs_last_hour"] == 60
    assert pipeline["successful_runs_last_hour"] == 30
    assert pipeline["completeness_percent"] == 50

    conn.execute("DELETE FROM collector_runs")


def test_completeness_full_when_all_cycles_succeed(device, api_client, conn, snapshot):
    """60 successful cycles → 100%. The min(100, ...) clamp holds the ceiling."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    for m in range(60):
        _add_collector_run(conn, m, error=None)

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    assert body["pipeline"]["completeness_percent"] == 100

    conn.execute("DELETE FROM collector_runs")
