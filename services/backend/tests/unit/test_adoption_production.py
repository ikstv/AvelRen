"""Production coordination refuses stale authority before opening PostgreSQL."""

import hashlib
from dataclasses import replace
from importlib import import_module, util

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
