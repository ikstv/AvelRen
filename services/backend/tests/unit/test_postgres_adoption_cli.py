"""CLI rejects ambiguous/production operations before connecting."""

from types import SimpleNamespace

import pytest

from avelren.adoption_inventory import AdoptionError
from avelren.postgres_adoption import main


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["production-adopt"],
        ["apply-test", "--production"],
        ["inventory"],
        ["inventory", "--output-dir", "/tmp/private", "--dsn", "sentinel-secret-dsn"],
    ],
)
def test_cli_invalid_arguments_are_sanitized(arguments, monkeypatch, capsys):
    monkeypatch.delenv("AVELREN_ADOPTION_DSN", raising=False)
    monkeypatch.delenv("AVELREN_ADOPTION_TARGET", raising=False)
    assert main(arguments) == 2
    output = capsys.readouterr()
    assert "sentinel-secret-dsn" not in output.out + output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(
    "category,expected_rc",
    [
        ("pre_commit_failure", 2),
        ("mutation_connection_unavailable", 2),
        ("adoption_lock_failed", 2),
        ("adoption_lock_timeout", 2),
        ("plan_drift", 1),
        ("active_sessions", 1),
    ],
)
def test_disposable_cli_preserves_refusal_and_unavailable_rc(
    category,
    expected_rc,
    monkeypatch,
    tmp_path,
    capsys,
):
    from avelren import postgres_adoption

    monkeypatch.setenv("AVELREN_ADOPTION_DSN", "sentinel-secret-dsn")
    monkeypatch.setenv("AVELREN_ADOPTION_TARGET", "target")
    monkeypatch.setattr(postgres_adoption, "_guards", lambda *args: None)
    monkeypatch.setattr(
        postgres_adoption,
        "_load_plan",
        lambda path: SimpleNamespace(
            before="before",
            expected="expected",
            forward=("mutation",),
        ),
    )
    monkeypatch.setattr(postgres_adoption, "fingerprint", lambda snapshot: snapshot)
    monkeypatch.setattr(postgres_adoption, "read_snapshot", lambda dsn: "before")

    def unavailable(*args, **kwargs):
        raise AdoptionError(category)

    monkeypatch.setattr(postgres_adoption, "run_mutation", unavailable)
    assert main(["apply-test", "--evidence-dir", str(tmp_path)]) == expected_rc
    output = capsys.readouterr()
    assert "sentinel-secret-dsn" not in output.out + output.err
    assert "Traceback" not in output.err
