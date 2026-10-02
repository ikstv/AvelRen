"""Перевірки collector-only runtime. Секретні значення не виводяться."""
import json
import os
from pathlib import Path
import re
import stat

FIELDS = {'source_commit', 'image_id', 'env_file', 'compose_file', 'project',
          'container_name', 'network', 'volume', 'state_dir'}
PRODUCTION = dict(project='avelren-collector-runtime', container_name='avelren-collector-1',
                  network='avelren_default', volume='avelren_collector_spool_v1')


def private_path(path: Path, *, directory=False, test_mode=False):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('unsafe_path')
    info = path.stat()
    if directory != stat.S_ISDIR(info.st_mode) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError('wrong_path_type')
    if os.name != 'posix':
        if not test_mode:
            raise ValueError('linux_required')
        # Windows mode bits cannot establish Unix private permissions.
        if info.st_mode & 0o077:
            raise ValueError('private_permissions_unverified')
    elif info.st_mode & (0o077 if not directory else 0o022):
        raise ValueError('unsafe_permissions')
    if not test_mode:
        for ancestor in (path, *path.parents):
            parent = ancestor.stat()
            if parent.st_uid != 0 or parent.st_mode & 0o022:
                raise ValueError('untrusted_path_owner')


def load_manifest(path: Path, *, test_mode: bool = False) -> dict:
    private_path(path, test_mode=test_mode)
    try:
        value = json.loads(path.read_text())
    except (ValueError, OSError):
        raise ValueError('invalid_manifest') from None
    if not isinstance(value, dict) or set(value) != FIELDS or not all(isinstance(v, str) for v in value.values()):
        raise ValueError('invalid_manifest_fields')
    if not re.fullmatch('[0-9a-f]{40}', value['source_commit']) or not re.fullmatch('sha256:[0-9a-f]{64}', value['image_id']):
        raise ValueError('invalid_image_identity')
    for key, expected in PRODUCTION.items():
        if test_mode:
            if not re.fullmatch('avelren-runtime-test-[a-z0-9-]+', value[key]):
                raise ValueError('unsafe_test_resource')
        elif value[key] != expected:
            raise ValueError('unexpected_production_resource')
    private_path(Path(value['env_file']), test_mode=test_mode)
    private_path(Path(value['state_dir']), directory=True, test_mode=test_mode)
    compose = Path(value['compose_file'])
    if not compose.is_absolute() or not compose.is_file() or compose.is_symlink():
        raise ValueError('invalid_compose_path')
    if not test_mode:
        for ancestor in (compose, *compose.parents):
            info = ancestor.stat()
            if ancestor.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('untrusted_compose')
    return value
