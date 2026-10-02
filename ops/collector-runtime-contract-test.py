"""Контракт окремого runtime; Compose config не запускає daemon."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'ops/collector-runtime-preflight.py'


def load_module():
    spec = importlib.util.spec_from_file_location('runtime_preflight', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = self.root / 'collector.env'
        self.env.write_text("DATABASE_URL=sentinel-$PASSWORD 'quoted'\nECHERHA_DEVICE_ID=11111111-1111-4111-8111-111111111111\n")
        self.env.chmod(0o600)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.manifest = dict(source_commit='a' * 40, image_id='sha256:' + 'b' * 64,
            env_file=str(self.env.resolve()), compose_file=str((ROOT / 'ops/compose.collector-runtime.yml').resolve()),
            project='avelren-runtime-test-unit', container_name='avelren-runtime-test-unit-collector',
            network='avelren-runtime-test-unit-network', volume='avelren-runtime-test-unit-volume',
            state_dir=str(self.state.resolve()))
        self.path = self.root / 'manifest.json'

    def save(self):
        self.path.write_text(json.dumps(self.manifest))
        self.path.chmod(0o600)

    def config(self):
        env = dict(os.environ, COLLECTOR_IMAGE_ID=self.manifest['image_id'],
            COLLECTOR_ENV_FILE=self.manifest['env_file'], COLLECTOR_CONTAINER_NAME=self.manifest['container_name'],
            COLLECTOR_NETWORK=self.manifest['network'], COLLECTOR_VOLUME=self.manifest['volume'])
        p = subprocess.run(['docker', 'compose', '-p', self.manifest['project'], '-f', self.manifest['compose_file'],
            'config', '--format', 'json'], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, 'Compose config failed (output withheld)')
        return json.loads(p.stdout)

    def test_single_service_external_resources(self):
        cfg = self.config()
        self.assertEqual(set(cfg['services']), {'collector'})
        svc = cfg['services']['collector']
        for key in ('build', 'depends_on', 'ports', 'mem_limit', 'cpus'):
            self.assertNotIn(key, svc)
        self.assertEqual(svc['image'], self.manifest['image_id'])
        self.assertEqual(cfg['volumes']['collector_spool'], {'name': self.manifest['volume'], 'external': True})
        self.assertEqual(cfg['networks']['runtime']['name'], self.manifest['network'])
        self.assertTrue(cfg['networks']['runtime']['external'])

    def test_security_matches_live(self):
        svc = self.config()['services']['collector']
        self.assertEqual(svc['user'], '10001:10001')
        self.assertTrue(svc['read_only'])
        self.assertEqual(svc['cap_drop'], ['ALL'])
        self.assertEqual(svc['security_opt'], ['no-new-privileges:true'])
        self.assertEqual(svc['pids_limit'], 128)
        self.assertEqual(svc['restart'], 'unless-stopped')
        self.assertIn('size=64m', svc['tmpfs'][0])

    def test_env_values_are_literal(self):
        # Canonical Compose config escapes literal dollars for serialization.
        self.assertEqual(self.config()['services']['collector']['environment']['DATABASE_URL'], "sentinel-$$PASSWORD 'quoted'")

    def test_missing_manifest_field_denied(self):
        del self.manifest['image_id']
        self.save()
        with self.assertRaises(ValueError):
            load_module().load_manifest(self.path, test_mode=True)

    def test_private_file_permissions_denied(self):
        self.save()
        self.env.chmod(0o666)
        with self.assertRaises(ValueError):
            load_module().load_manifest(self.path, test_mode=True)


if __name__ == '__main__':
    unittest.main()
