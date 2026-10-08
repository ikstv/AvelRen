"""Приватні evidence-файли не перезаписуються і не йдуть за symlinks."""

import os
from pathlib import Path

import pytest

from avelren.adoption_evidence import read_verified, write_private
from avelren.adoption_inventory import AdoptionError


def test_private_publication_roundtrip(tmp_path):
    directory = tmp_path / "evidence"
    digest = write_private(directory, "snapshot.json", b"proof")
    assert read_verified(directory, "snapshot.json", digest) == b"proof"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "snapshot.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(AdoptionError):
        write_private(directory, "snapshot.json", b"replacement")
    assert (directory / "snapshot.json").read_bytes() == b"proof"
    with pytest.raises(AdoptionError):
        read_verified(directory, "snapshot.json", "0" * 64)


@pytest.mark.parametrize("name", ["../proof", "/tmp/proof", "a/b", "a\\b", "..", ""])
def test_path_traversal_refused(tmp_path, name):
    with pytest.raises(AdoptionError):
        write_private(tmp_path / "private", name, b"proof")


def test_symlink_directory_and_file_refused(tmp_path):
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(AdoptionError):
        write_private(alias, "proof", b"proof")
    (target / "proof").symlink_to(Path("/etc/passwd"))
    with pytest.raises(AdoptionError):
        read_verified(target, "proof", "0" * 64)


def test_public_directory_refused(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(AdoptionError):
        write_private(tmp_path, "proof", b"proof")


@pytest.mark.parametrize("failure", ["write", "fsync"])
def test_failed_write_does_not_publish_partial_file(tmp_path, monkeypatch, failure):
    def denied(*args, **kwargs):
        raise OSError("sentinel-secret-dsn")
    monkeypatch.setattr(os, failure, denied)
    directory = tmp_path / "private"
    with pytest.raises(AdoptionError) as error:
        write_private(directory, "proof", b"proof")
    assert "sentinel-secret-dsn" not in str(error.value)
    assert not (directory / "proof").exists()
