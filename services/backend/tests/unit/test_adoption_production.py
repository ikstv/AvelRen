"""Production coordination refuses stale authority before opening PostgreSQL."""

import hashlib
from dataclasses import replace
from importlib import import_module, util
from types import SimpleNamespace

import pytest

from avelren.adoption_inventory import SECTIONS, AdoptionError, Snapshot
from avelren.adoption_operation import make_operation, write_operation
from avelren.adoption_operator import Confirmation
from avelren.adoption_plan import AdoptionPlan
from avelren.adoption_target import TargetBinding


def inputs(tmp_path, runtime_digest="b" * 64):
    assert util.find_spec("avelren.adoption_production") is not None, "coordinator is missing"
    module = import_module("avelren.adoption_production")
    before = Snapshot(1, "unit_database", {name: [] for name in SECTIONS})
    after = replace(before, sections={**before.sections, "shared": [{"kind": "target"}]})
    plan = AdoptionPlan(1, before, after, ("forward SQL",), ("inverse SQL",))
    binding = TargetBinding(1, "1234", before.database, 16384, "admin", "a" * 40, runtime_digest)
    manifest = make_operation(binding, plan)
    directory = tmp_path / "evidence"
    write_operation(directory, manifest)
    context = module.MaintenanceContext(
        manifest.operation_id,
        manifest.target_digest,
        manifest.plan_digest,
        runtime_digest,
        "quiescent",
    )
    confirmation = Confirmation(
        "ADOPT", manifest.operation_id, manifest.target_digest, manifest.plan_digest
    )
    return module, binding, plan, directory, context, confirmation


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "0" * 32),
        ("target_digest", "0" * 64),
        ("plan_digest", "0" * 64),
        ("runtime_digest", "0" * 64),
        ("phase", "stopped"),
    ],
)
def test_adoption_production_rejects_context_before_connect(tmp_path, monkeypatch, field, value):
    module, binding, plan, directory, context, confirmation = inputs(tmp_path)
    opened = []
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: opened.append(True))
    with pytest.raises(AdoptionError, match="maintenance_context"):
        module.apply_production(
            "password=DO_NOT_EXPOSE",
            binding,
            plan,
            directory,
            replace(context, **{field: value}),
            confirmation,
            object(),
        )
    assert not opened


@pytest.mark.parametrize("variable", ["AVELREN_DATABASE_TEST", "AVELREN_ADOPTION_TEST_FAILPOINT"])
@pytest.mark.parametrize("value", ["", "0", "1"])
def test_adoption_production_environment_presence_refuses(tmp_path, monkeypatch, variable, value):
    module, binding, plan, directory, context, confirmation = inputs(tmp_path)
    monkeypatch.setenv(variable, value)
    with pytest.raises(AdoptionError, match="production_test_environment"):
        module.apply_production("dsn", binding, plan, directory, context, confirmation, object())


@pytest.mark.parametrize(
    "damage,category",
    [
        ("action", "operator_confirmation"),
        ("binding", "operation_plan_mismatch"),
        ("runtime", "runtime_unverified"),
        ("roots", "production_evidence_location"),
        ("manifest", "evidence_hash"),
    ],
)
def test_adoption_production_authority_refusals_are_redacted(
    tmp_path, monkeypatch, capsys, damage, category
):
    module, binding, plan, directory, context, confirmation = inputs(tmp_path)
    connected = []
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: connected.append(True))

    class Runtime:
        def verify(self, context, manifest):
            if damage == "runtime":
                raise RuntimeError("password=DO_NOT_EXPOSE")

        def checkout_roots(self):
            return (tmp_path,) if damage == "roots" else (directory.parent / "source",)

    (tmp_path / "source").mkdir()
    if damage == "action":
        confirmation = replace(confirmation, action="INVERSE")
    elif damage == "binding":
        binding = replace(binding, source_commit="0" * 40)
    elif damage == "manifest":
        (directory / "production-operation.sha256").write_bytes(b"0" * 64 + b"\n")
    with pytest.raises(AdoptionError, match=category) as caught:
        module.apply_production(
            "password=DO_NOT_EXPOSE", binding, plan, directory, context, confirmation, Runtime()
        )
    assert not connected
    assert "DO_NOT_EXPOSE" not in str(caught.value)
    assert "DO_NOT_EXPOSE" not in repr(caught.value)
    assert "DO_NOT_EXPOSE" not in "".join(capsys.readouterr())
    assert caught.value.__suppress_context__


def test_adoption_production_physical_clone_requires_original_host_runtime(tmp_path, monkeypatch):
    # A physical clone keeps PostgreSQL's system identifier; runtime host binding must refuse it.
    original_host = hashlib.sha256(b"host=original;project=owned-first;image=pinned").hexdigest()
    cloned_host = hashlib.sha256(b"host=clone;project=owned-second;image=pinned").hexdigest()
    module, binding, plan, directory, context, confirmation = inputs(tmp_path, original_host)
    clone_binding = replace(binding)  # The complete database identity is indistinguishable.
    assert clone_binding.system_identifier == binding.system_identifier == "1234"
    connected = []
    monkeypatch.setattr(module.psycopg, "connect", lambda *a, **k: connected.append(True))

    class CloneRuntime:
        def verify(self, context, manifest):
            if context.runtime_digest != cloned_host:
                raise AdoptionError("runtime_drift")

        def checkout_roots(self):
            return (tmp_path / "source",)

    with pytest.raises(AdoptionError, match="^runtime_drift$"):
        module.apply_production(
            "unused-clone-dsn",
            clone_binding,
            plan,
            directory,
            context,
            confirmation,
            CloneRuntime(),
        )
    assert not connected
    assert not (directory / "production-apply-intent.json").exists()


class GuardConnection:
    """Session double keeps acquisition, ownership and closure independently observable."""

    def __init__(self):
        self.identity = ("1234", "admin", "unit_database", 16384, "postgres")
        self.held = False
        self.busy = False
        self.fail = None
        self.acquisitions = 0
        self.closed = False
        self.close_calls = 0

    def execute(self, query, params=None):
        if "pg_control_system" in query:
            kind, row = "identity", self.identity
        elif "pg_try_advisory_lock" in query:
            self.acquisitions += 1
            kind, row = "acquire", (not self.busy,)
            self.held = not self.busy
        elif "pg_locks" in query:
            kind, row = "verify", (self.held,)
        elif "pg_advisory_unlock" in query:
            kind, row = "release", (self.held,)
            self.held = False
        else:
            raise AssertionError("unexpected guard query")
        if self.fail == kind:
            raise RuntimeError("password=DO_NOT_EXPOSE")
        self.row = row
        return self

    def fetchone(self):
        return self.row

    def close(self):
        self.close_calls += 1
        self.closed = True
        self.held = False
        if self.fail == "close":
            raise RuntimeError("password=DO_NOT_EXPOSE")


def guard_inputs(monkeypatch):
    module = import_module("avelren.adoption_production")
    assert hasattr(module, "_LifecycleLock"), "production lifecycle lock is missing"
    conn = GuardConnection()
    binding = TargetBinding(1, "1234", "unit_database", 16384, "admin", "a" * 40, "b" * 64)

    def connect(dsn, **kwargs):
        assert dsn == "private supplied DSN"
        assert kwargs["dbname"] == "postgres"
        assert kwargs["autocommit"] is True
        assert "default_transaction_read_only=on" in kwargs["options"]
        return conn

    monkeypatch.setattr(module.psycopg, "connect", connect)
    return module, conn, binding


def test_production_lifecycle_guard_owns_one_lock_and_closes(monkeypatch):
    module, conn, binding = guard_inputs(monkeypatch)
    guard = module._LifecycleLock.acquire("private supplied DSN", binding)
    assert conn.held and not conn.closed
    guard.verify()
    guard.verify()
    assert conn.acquisitions == 1  # A liveness probe must not reenter the advisory lock.
    assert guard.release() is True
    assert not conn.held and conn.closed and conn.close_calls == 1


@pytest.mark.parametrize("field", range(5))
def test_production_lifecycle_guard_identity_precedes_lock(monkeypatch, field):
    module, conn, binding = guard_inputs(monkeypatch)
    changed = list(conn.identity)
    changed[field] = "wrong" if field != 3 else 999
    conn.identity = tuple(changed)
    with pytest.raises(AdoptionError, match="^target_mismatch$"):
        module._LifecycleLock.acquire("private supplied DSN", binding)
    assert conn.acquisitions == 0 and conn.closed


@pytest.mark.parametrize("failure", ["identity", "acquire", "busy"])
def test_production_lifecycle_guard_refusal_closes_without_secret(monkeypatch, failure):
    module, conn, binding = guard_inputs(monkeypatch)
    conn.fail = failure
    conn.busy = failure == "busy"
    expected = "production_operation_busy" if conn.busy else "production_lock_unavailable"
    with pytest.raises(AdoptionError, match="^" + expected + "$") as caught:
        module._LifecycleLock.acquire("private supplied DSN", binding)
    assert conn.closed and not conn.held
    assert "DO_NOT_EXPOSE" not in str(caught.value)


@pytest.mark.parametrize("failure", ["verify", "lost_ownership"])
def test_production_lifecycle_guard_lost_session_cannot_authorize(monkeypatch, failure):
    module, conn, binding = guard_inputs(monkeypatch)
    guard = module._LifecycleLock.acquire("private supplied DSN", binding)
    conn.fail = failure
    if failure == "lost_ownership":
        conn.held = False
    with pytest.raises(AdoptionError, match="^production_lock_unavailable$"):
        guard.verify()
    assert conn.acquisitions == 1
    guard.release()
    assert conn.closed


@pytest.mark.parametrize("failure", ["release", "close", "lost_ownership"])
def test_production_lifecycle_guard_release_failure_still_closes(monkeypatch, failure):
    module, conn, binding = guard_inputs(monkeypatch)
    guard = module._LifecycleLock.acquire("private supplied DSN", binding)
    conn.fail = failure
    if failure == "lost_ownership":
        conn.held = False
    assert guard.release() is False
    assert conn.close_calls == 1 and conn.closed


@pytest.mark.parametrize(
    "status,expected_category",
    [
        ("rollback_failed", "pre_commit_unverified"),
        ("rolled_back", "production_lock_release_unavailable"),
    ],
)
def test_production_lifecycle_cleanup_cannot_downgrade_mutation_outcome(
    tmp_path, monkeypatch, status, expected_category
):
    from avelren.adoption_operation import read_operation
    from avelren.postgres_adoption import AdoptionResult

    module, binding, plan, directory, context, confirmation = inputs(tmp_path)
    manifest = read_operation(directory)
    outcome = AdoptionResult(status, "pre_commit_unverified", manifest.before_fingerprint, None)
    guard = SimpleNamespace(possible_commit=False, release=lambda: False)
    monkeypatch.setattr(module, "_authority", lambda *args: (manifest, plan, set()))
    monkeypatch.setattr(module._LifecycleLock, "acquire", lambda dsn, binding: guard)
    monkeypatch.setattr(module, "_coordinate_locked", lambda *args, **kwargs: outcome)
    result = module.apply_production(
        "private supplied DSN", binding, plan, directory, context, confirmation, object()
    )
    assert (result.status, result.category) == ("rollback_failed", expected_category)
