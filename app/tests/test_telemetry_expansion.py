"""PR-B — розширення `/admin/telemetry`: services, docker, inodes, upstream,
last_collector_run/success, version.

Основний інваріант — той самий, що в PR-A:
**відсутнє поле = null, а не «здоровий сервер із нулями»**.

Плюс security-регресія: `services()` не сміє віддавати нічого поза whitelist
навіть якщо host-скрипт випадково запише зайве поле.
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
# services() — чиста функція на snapshot, security-критична
# ============================================================================

def test_services_returns_empty_when_snapshot_missing(tmp_path, monkeypatch):
    """Snapshot нема — не exception, не «здорові сервіси», а порожньо. Клієнт
    відмалює як ⚪ Unknown, а не приховає провал моніторингу."""
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
    """Security-регресія: якщо host-скрипт випадково додасть поле поза
    whitelist (env, mounts, cmd, ports), telemetry МАЄ його викинути. Без
    цього одна необережна правка в deploy/ відкриває канал утечки secrets.

    N2 (review PR #34): раніше тест перевіряв лише кілька відомих forbidden
    keys. Тепер positive-allowlist: `entry.keys() ⊆ {"name"} ∪ ALLOWED`. Це
    робить регресію mutation-safe — навіть якщо injected поле не збігається
    з блеклістом (напр., майбутній `secrets_path`), тест впаде."""
    snapshot(
        {
            "services": [
                {
                    "name": "api",
                    "status": "running",
                    "health": "healthy",
                    # Зайві поля, які теоретично могли б потрапити з docker inspect.
                    "env": ["DATABASE_URL=postgres://user:secret@db/avelren"],
                    "mounts": ["/secrets:/secrets:ro"],
                    "cmd": ["python", "-m", "avelren.api"],
                    "network_settings": {"IPAddress": "10.0.0.5"},
                    "labels": {"com.docker.compose.project": "avelren"},
                    # Поле, якого немає в поточному blacklist — саме сценарій,
                    # що позитивний allowlist ловить, а негативний пропускає.
                    "secrets_path": "/run/secrets/firebase.json",
                }
            ]
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.services()
    assert len(result) == 1
    entry = result[0]

    # Positive-allowlist інваріант: жодного поля поза дозволеним набором.
    allowed = {"name"} | telemetry._SERVICE_ALLOWED_FIELDS
    extra = set(entry.keys()) - allowed
    assert not extra, f"поля поза whitelist: {extra}"

    # Явна перевірка типових ризикових ключів — залишаю для читабельності
    # діагностики (перший рядок збою вкаже конкретно на утечку secrets).
    forbidden = {"env", "mounts", "cmd", "network_settings", "labels",
                 "config", "secrets_path"}
    leaked = forbidden & set(entry.keys())
    assert not leaked, f"утечка полів поза whitelist: {leaked}"


def test_services_whitelist_blocks_unseen_future_field(snapshot):
    """Mutation-регресія: тест доводить, що конкретний refactor «повертаємо
    весь entry» (напр. `out.append(dict(entry))`) буде спійманий. Іменований
    сценарій ловить клас багу, а не конкретне ім'я поля."""
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
        f"whitelist пропустив невідоме поле {hypothetical_new_field!r} — "
        "це саме той клас регресії, від якого захищає positive-allowlist"
    )


def test_services_ignores_unknown_container_names(snapshot):
    """Whitelist імен: якщо в snapshot з'явиться контейнер, якого ми не знаємо
    (напр. хтось додав `postgres-backup-1`), API його не покаже. Це захищає від
    сценарію «випадково засвітили внутрішній сервіс на клієнті»."""
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
    """UI має отримувати сервіси у стабільному порядку, інакше картки
    «стрибають» між композиціями. Порядок — за призначенням (db → caddy)."""
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
    """Якщо один рядок пошкоджений (не dict), сусідні мають вижити."""
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
    """Якщо весь блок пошкоджений (не list) — теж [], а не exception."""
    snapshot({"services": {"api": "running"}}, collected_at=datetime.now(UTC))
    assert telemetry.services() == []


def test_services_stopped_container(snapshot):
    """Зупинений контейнер має з'явитися саме як stopped, а не бути прихованим.
    Зникнення сервісу з UI — гірший стан, ніж чесний 🔴 exited."""
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
# docker() / inodes() — прості чисті функції
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
# upstream() — читає settings
# ============================================================================

def test_upstream_reads_from_settings():
    """upstream() не залежить від snapshot — це чиста конфігурація. Клієнт
    бачить, який саме URL ходить збирач, без здогадок."""
    result = telemetry.upstream()
    assert "workload_url" in result
    assert "poll_interval_seconds" in result
    assert result["poll_interval_seconds"] == 60


# ============================================================================
# End-to-end через /admin/telemetry (pipeline, last_collector_run, version)
# ============================================================================

def _make_admin(conn, device):
    conn.execute("UPDATE devices SET is_admin = true WHERE id = %s", (device.device_id,))


def test_admin_telemetry_new_blocks_present_and_backward_compatible(
    device, api_client, conn, snapshot
):
    """Існуючі поля (system/network/pipeline/certificate/backups/problems) —
    на місці; додані блоки — теж. Порушення = зламали клієнта PR-A або старий
    APK, тому цей тест — контракт."""
    _make_admin(conn, device)
    snapshot(
        {"system": {"cpu_count": 2}, "services": [], "docker": {}, "inodes": {}},
        collected_at=datetime.now(UTC),
    )

    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 200
    body = r.json()

    # PR-A / раніший контракт — має залишатися.
    for old in ("system", "network", "pipeline", "certificate", "backups", "problems"):
        assert old in body, f"втрачено існуюче поле {old}"

    # Нові блоки PR-B.
    for new in (
        "services", "docker", "inodes", "upstream",
        "last_collector_run", "last_collector_success", "version",
    ):
        assert new in body, f"відсутній новий блок {new}"


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
    # body_sha256 навмисно НЕ у відповіді — технічний артефакт, клієнту непотрібен.
    assert "body_sha256" not in last

    success = body["last_collector_success"]
    assert success["http_status"] == 200
    assert success["rows_written"] == 38
    # success НЕ має error / derived — це чисто «останній успіх», спрощений набір.
    assert "error" not in success


def test_admin_telemetry_version_reads_env_and_migrations(
    device, api_client, conn, snapshot, monkeypatch
):
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    monkeypatch.setenv("AVELREN_GIT_SHA", "abc123def")

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    v = body["version"]
    assert v["app_version"]  # непорожній
    assert v["git_sha"] == "abc123def"
    # migrations_version — max(version) з БД; в тестовій БД міграції накачані,
    # тож рядок не буде порожнім (точне значення міняється з часом).
    assert v["migrations_version"] is not None


def test_admin_telemetry_version_git_sha_null_when_env_missing(
    device, api_client, conn, snapshot, monkeypatch
):
    """Без env AVELREN_GIT_SHA — git_sha=null, а не «unknown»/«dev». Клієнт
    розрізняє «версія відома, це dev» і «версія просто не проставлена в build»."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    monkeypatch.delenv("AVELREN_GIT_SHA", raising=False)

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    assert body["version"]["git_sha"] is None


def test_admin_telemetry_upstream_shows_workload_url(
    device, api_client, conn, snapshot
):
    """Дашборд має чесно показувати, куди зараз ходить збирач — це головна
    цифра для «чи ЄЧерга v4 чи v5»."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    upstream = body["upstream"]
    assert "workload_url" in upstream
    assert upstream["poll_interval_seconds"] == 60


def test_admin_telemetry_services_still_authenticated(
    device, api_client, conn, snapshot
):
    """Гейт is_admin не має ослабнути після додавання нових блоків.
    Пристрій без is_admin=true отримує 403 на весь endpoint (включно з новими
    полями). Регресія на випадок, якщо хтось випадково винесе один із блоків
    у public — зайві очі."""
    snapshot(
        {"services": [{"name": "api", "status": "running"}]},
        collected_at=datetime.now(UTC),
    )
    # is_admin навмисно НЕ виставляємо.
    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 403


# ============================================================================
# completeness_percent — рахує УСПІШНІ цикли, а не спроби (issue #22)
# ============================================================================

def _add_collector_run(conn, minutes_ago: int, *, error: str | None) -> None:
    conn.execute(
        "INSERT INTO collector_runs (time, error) VALUES (now() - make_interval(mins => %s), %s)",
        (minutes_ago, error),
    )


def test_completeness_ignores_failed_cycles(device, api_client, conn, snapshot):
    """Регресія issue #22: коли ЄЧерга щохвилини віддає помилку, collector_runs
    усе одно поповнюється, але жодне спостереження не зібране. Completeness має
    рахувати УСПІШНІ цикли (error IS NULL), інакше показує 100% повноти під час
    повного збою збору даних."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    # 60 циклів за годину, але ВСІ з помилкою — повнота має бути 0, не 100.
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
    """Змішаний годину: 30 успішних + 30 з помилкою → повнота 50%, не 100%."""
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
    """60 успішних циклів → 100%. Кламп min(100, ...) утримує стелю."""
    _make_admin(conn, device)
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    conn.execute("DELETE FROM collector_runs")

    for m in range(60):
        _add_collector_run(conn, m, error=None)

    body = api_client.get("/admin/telemetry", headers=device.headers()).json()
    assert body["pipeline"]["completeness_percent"] == 100

    conn.execute("DELETE FROM collector_runs")
