"""Серіалізоване керування перевіреним collector; без implicit recreate."""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import time

_spec = importlib.util.spec_from_file_location('collector_runtime', Path(__file__).with_name('collector-runtime-preflight.py'))
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)


@contextmanager
def operator_lock(directory: Path):
    import fcntl
    fd = os.open(directory / 'control.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise ValueError('unsafe_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('operator_busy') from None
        yield
    finally:
        os.close(fd)


def wait_interval(seconds: int):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(min(1, deadline - time.monotonic()))


def record_stop(manifest: dict, target: dict):
    directory = Path(manifest['state_dir'])
    fd, temporary = tempfile.mkstemp(prefix='.stop-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(container_id=target['Id'], stopped_at=time.time()), stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'stop.json')
        if os.name == 'posix':
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(manifest: dict, action: str, arguments: list[str]) -> dict:
    manifest, target = runtime.preflight(manifest, require_managed=True)
    command, env = runtime.compose_command(manifest)
    if action == 'status':
        return runtime.status(manifest, target)
    if action == 'logs':
        # Application logs only; no inspect/config/environment output.
        print(runtime.run([*command, 'logs', '--no-color', '--tail', '100', 'collector'], env=env), end='')
        return {'status': 'logs_complete'}
    if action == 'preflight':
        if not arguments:
            return {'status': 'verified'}
        if len(arguments) != 2 or arguments[0] != '--window-minutes' or not arguments[1].isdigit() or int(arguments[1]) <= 0:
            raise ValueError('invalid_window')
        code = ('import json; from dataclasses import asdict; from pathlib import Path; '
                'from avelren.collector_spool import SpoolStore; '
                's=SpoolStore(Path("/var/lib/avelren/collector-spool/cycles.sqlite3")); '
                'print(json.dumps(asdict(s.maintenance_preflight(' + str(int(arguments[1])) + ')), default=str)); s.close()')
        return json.loads(runtime.run(['docker', 'exec', manifest['container_name'], 'python', '-c', code]))
    if action == 'capture-only':
        if arguments not in (['on'], ['off'], ['status']) or not target['State']['Running']:
            raise ValueError('invalid_capture_mode_or_stopped')
        value = json.loads(runtime.run(['docker', 'exec', manifest['container_name'], 'python', '-m',
                                      'avelren.collector_control', 'capture-only', arguments[0]]))
        if arguments[0] != 'status':
            requested = arguments[0] == 'on'
            if value.get('capture_only') is not requested or value.get('mode_ack') is not requested:
                raise ValueError('capture_mode_not_acknowledged')
        return value
    if action not in ('start', 'stop', 'restart') or arguments:
        raise ValueError('invalid_action')
    if action == 'start' and target['State']['Running']:
        return {'status': 'already_running'}
    if action in ('stop', 'restart'):
        runtime.run([*command, 'stop', '--timeout', '30', 'collector'], env=env)
        _, target = runtime.preflight(manifest, require_managed=True)
        if target['State']['Running']:
            raise ValueError('stop_not_confirmed')
        record_stop(manifest, target)
        if action == 'stop':
            return {'status': 'stopped', 'container_id': target['Id']}
    # Always wait 60 monotonic seconds: safe across missing state, reboot and wall-clock changes.
    wait_interval(60)
    _, stopped = runtime.preflight(manifest, require_managed=True)
    if stopped['State']['Running'] or stopped['Id'] != target['Id']:
        raise ValueError('target_changed_during_wait')
    runtime.run([*command, 'start', 'collector'], env=env)
    _, started = runtime.preflight(manifest, require_managed=True)
    if not started['State']['Running'] or started['Id'] != target['Id']:
        raise ValueError('start_not_confirmed')
    return {'status': 'running', 'container_id': started['Id']}


def main():
    parser = argparse.ArgumentParser(description='Керування окремим collector runtime')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--test-mode', action='store_true')
    parser.add_argument('command', choices=['status', 'logs', 'preflight', 'start', 'stop', 'restart', 'capture-only'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if os.name != 'posix' or (not args.test_mode and os.geteuid() != 0):
            raise ValueError('root_linux_required')
        manifest = runtime.load_manifest(args.manifest, test_mode=args.test_mode)
        if args.command in ('start', 'stop', 'restart', 'capture-only'):
            with operator_lock(Path(manifest['state_dir'])):
                result = execute(manifest, args.command, args.arguments)
        else:
            result = execute(manifest, args.command, args.arguments)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        print(json.dumps({'status': 'denied', 'reason': 'collector_control_failed'}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({'status': 'interrupted'}))
        return 130


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
