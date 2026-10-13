"""Контракти source systemd wiring; реальне verify виконується окремо."""

import unittest
from pathlib import Path


class Units(unittest.TestCase):
    def test_bounded_recovery_wiring(self):
        root = Path(__file__).parent
        backup = (root / "avelren-backup.service").read_text()
        recovery_path = root / "avelren-backup-recovery.service"
        self.assertTrue(recovery_path.exists(), "recovery unit missing")
        recovery = recovery_path.read_text()
        self.assertIn("OnFailure=avelren-backup-recovery.service", backup)
        self.assertIn("TimeoutStartSec=1800", backup)
        self.assertIn("TimeoutStopSec=180", backup)
        self.assertIn("KillMode=control-group", backup)
        self.assertIn("ExecStopPost=/usr/local/sbin/avelren-paired-backup recover", backup)
        self.assertNotIn("ExecStopPost=-", backup)
        self.assertIn("ExecStart=/usr/local/sbin/avelren-paired-backup recover", recovery)
        self.assertIn("TimeoutStartSec=180", recovery)
        self.assertIn("KillMode=control-group", recovery)
        self.assertIn("UMask=0077", recovery)

    def test_dispatch_preserves_default(self):
        script = Path(__file__).with_name("backup.sh").read_text()
        self.assertIn("AVELREN_BACKUP_MODE:-sql-only", script)
        self.assertIn("AVELREN_PAIRED_BACKUP_SCRIPT:-/usr/local/sbin/avelren-paired-backup", script)
        self.assertIn("AVELREN_RUNTIME_MANIFEST", script)


if __name__ == "__main__":
    unittest.main()
