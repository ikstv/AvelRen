import unittest

from avelren.release_notice import release_payload


class ReleaseNoticeTests(unittest.TestCase):
    def test_legacy_compatible_information_not_queue_alert(self):
        payload = release_payload("0.1.1", 4)
        self.assertEqual(payload["type"], "health")
        self.assertEqual(payload["subtype"], "app_update")
        self.assertEqual(payload["version_code"], "4")
        self.assertNotIn("alert_id", payload)
        self.assertIn("Вийшла версія 0.1.1", payload["body"])
        self.assertTrue(all(isinstance(value, str) for value in payload.values()))

    def test_future_version_is_not_hardcoded(self):
        self.assertIn("0.1.2", release_payload("0.1.2", 5)["body"])

    def test_invalid_release_is_rejected(self):
        for name, code in (("", 4), ("0.1.1-test", 4), ("0.1.1", 0),
                           ("0.1.1", True), ("0.1.1", 2_100_000_001)):
            with self.assertRaises(ValueError):
                release_payload(name, code)
