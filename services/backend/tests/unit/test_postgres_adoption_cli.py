"""CLI rejects ambiguous/production operations before connecting."""

import pytest

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
