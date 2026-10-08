"""Private, exclusive evidence publication on the Linux database-test runner."""

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

from .adoption_inventory import AdoptionError


def _name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) or ".." in name:
        raise AdoptionError("evidence_name")


def _directory(directory: Path, *, create: bool) -> int:
    if os.name != "posix":
        # Windows ACL equivalence is not silently approximated by chmod.
        raise AdoptionError("evidence_platform")
    path = Path(os.path.abspath(directory))
    for ancestor in (*reversed(path.parents), path):
        if ancestor.is_symlink():
            raise AdoptionError("evidence_path")
    try:
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            os.close(fd)
            raise AdoptionError("evidence_permissions")
        return fd
    except OSError as exc:
        raise AdoptionError("evidence_directory") from exc


def write_private(directory: Path, name: str, payload: bytes) -> str:
    _name(name)
    root = _directory(directory, create=True)
    temporary = ".adoption-" + uuid.uuid4().hex
    fd = None
    published = False
    identity = None
    try:
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root
        )
        info = os.fstat(fd)
        identity = (info.st_dev, info.st_ino)
        view = memoryview(payload)
        while view:
            size = os.write(fd, view)
            if size <= 0:
                raise OSError("incomplete evidence write")
            view = view[size:]
        os.fsync(fd)
        os.link(temporary, name, src_dir_fd=root, dst_dir_fd=root, follow_symlinks=False)
        published = True
        os.fsync(root)
        return hashlib.sha256(payload).hexdigest()
    except OSError as exc:
        if published:
            current = os.stat(name, dir_fd=root, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == identity:
                os.unlink(name, dir_fd=root)
        raise AdoptionError("evidence_publication") from exc
    finally:
        if fd is not None:
            os.close(fd)
            current = os.stat(temporary, dir_fd=root, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == identity:
                os.unlink(temporary, dir_fd=root)
        os.close(root)


def read_private(directory: Path, name: str) -> bytes:
    _name(name)
    root = _directory(directory, create=False)
    fd = None
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > 32 * 1024 * 1024
        ):
            raise AdoptionError("evidence_permissions")
        with os.fdopen(fd, "rb") as stream:
            fd = None
            payload = stream.read(32 * 1024 * 1024 + 1)
        if len(payload) != info.st_size:
            raise AdoptionError("evidence_size")
        return payload
    except OSError as exc:
        raise AdoptionError("evidence_read") from exc
    finally:
        if fd is not None:
            os.close(fd)
        os.close(root)


def read_verified(directory: Path, name: str, expected_sha256: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise AdoptionError("evidence_hash")
    payload = read_private(directory, name)
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise AdoptionError("evidence_hash")
    return payload
