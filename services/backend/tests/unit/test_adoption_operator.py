"""Operator approval requires exact digests on a live, local Linux root TTY."""

import builtins
import io
from dataclasses import FrozenInstanceError, replace

import psycopg
import pytest

from avelren import adoption_operator as operator
from avelren.adoption_inventory import AdoptionError
from avelren.adoption_operation import OperationManifest
from avelren.adoption_operator import Confirmation, confirm_operator, verify_confirmation

MANIFEST = OperationManifest(1, "c" * 32, "d" * 64, "e" * 64, "f" * 64, "0" * 64)
PHRASE = "ADOPT " + "d" * 64 + " " + "e" * 64


class FakeTTY(io.StringIO):
    def __init__(self, phrase, *, live=True):
        super().__init__()
        self.phrase = phrase
        self.live = live

    def isatty(self):
        return self.live

    def readline(self, size=-1):
        return self.phrase


@pytest.fixture
def local_root(monkeypatch):
    monkeypatch.setattr(operator.sys, "platform", "linux")
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    for name in ("AVELREN_DATABASE_TEST", "AVELREN_ADOPTION_TEST_FAILPOINT"):
        monkeypatch.delenv(name, raising=False)

    def denied_connection(*args, **kwargs):
        raise AssertionError("Operator confirmation must never connect to PostgreSQL")

    monkeypatch.setattr(psycopg, "connect", denied_connection)


def fake_terminal(monkeypatch, phrase=PHRASE + "\n", *, live=True):
    def open_tty(path, mode="r", **kwargs):
        assert path == "/dev/tty"
        if mode == "r+":
            # Text update mode uses BufferedRandom, which requires seekability;
            # the real terminal is a character device, not a seekable file.
            raise io.UnsupportedOperation("File or stream is not seekable")
        assert mode in {"r", "w"}
        return FakeTTY(phrase, live=live)

    monkeypatch.setattr(builtins, "open", open_tty)


@pytest.mark.parametrize("action", ["ADOPT", "INVERSE"])
def test_adoption_operator_requires_live_tty_and_exact_action(local_root, monkeypatch, action):
    fake_terminal(monkeypatch, PHRASE.replace("ADOPT", action) + "\n")
    confirmation = confirm_operator(action, MANIFEST)
    assert confirmation == Confirmation(action, "c" * 32, "d" * 64, "e" * 64)
    verify_confirmation(confirmation, action, MANIFEST)
    with pytest.raises(FrozenInstanceError):
        confirmation.action = "OTHER"


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        "yes\n",
        PHRASE.replace("ADOPT", "INVERSE") + "\n",
        PHRASE + " \n",
        " " + PHRASE + "\n",
        PHRASE.replace("d" * 64, "d" * 8) + "\n",
        PHRASE.replace("e" * 64, "e" * 8) + "\n",
        PHRASE,
    ],
)
def test_operator_wrong_phrase_refused(local_root, monkeypatch, phrase):
    fake_terminal(monkeypatch, phrase)
    with pytest.raises(AdoptionError):
        confirm_operator("ADOPT", MANIFEST)


@pytest.mark.parametrize("action", ["adopt", "inverse", "YES", "", None])
def test_operator_unknown_action_refused(local_root, monkeypatch, action):
    fake_terminal(monkeypatch)
    with pytest.raises(AdoptionError):
        confirm_operator(action, MANIFEST)


@pytest.mark.parametrize("boundary", ["platform", "root", "not-tty", "unavailable", "read-error"])
def test_operator_system_boundary_refused(local_root, monkeypatch, capsys, boundary):
    fake_terminal(monkeypatch, live=boundary != "not-tty")
    if boundary == "platform":
        monkeypatch.setattr(operator.sys, "platform", "darwin")
    elif boundary == "root":
        monkeypatch.setattr(operator.os, "geteuid", lambda: 10001)
    elif boundary == "unavailable":

        def denied(*args, **kwargs):
            raise OSError("sentinel-credential")

        monkeypatch.setattr(builtins, "open", denied)
    elif boundary == "read-error":

        def denied(*args, **kwargs):
            raise OSError("sentinel-credential")

        monkeypatch.setattr(FakeTTY, "readline", denied)
    with pytest.raises(AdoptionError) as caught:
        confirm_operator("ADOPT", MANIFEST)
    assert "sentinel-credential" not in str(caught.value)
    assert caught.value.__cause__ is None
    captured = capsys.readouterr()
    assert "sentinel-credential" not in captured.out + captured.err


@pytest.mark.parametrize("name", ["AVELREN_DATABASE_TEST", "AVELREN_ADOPTION_TEST_FAILPOINT"])
@pytest.mark.parametrize("value", ["", "0", "1", "sentinel-credential"])
def test_operator_test_environment_presence_refused(local_root, monkeypatch, name, value):
    fake_terminal(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(AdoptionError):
        confirm_operator("ADOPT", MANIFEST)


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "INVERSE"),
        ("operation_id", "1" * 32),
        ("target_digest", "1" * 64),
        ("plan_digest", "1" * 64),
    ],
)
def test_confirmation_binding_mismatch_refused(field, value):
    confirmation = Confirmation("ADOPT", "c" * 32, "d" * 64, "e" * 64)
    with pytest.raises(AdoptionError):
        verify_confirmation(replace(confirmation, **{field: value}), "ADOPT", MANIFEST)
