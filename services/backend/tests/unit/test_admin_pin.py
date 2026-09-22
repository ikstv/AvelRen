import unittest
from datetime import UTC, datetime, timedelta

from avelren.admin_pin import evaluate_attempt, hash_pin, verify_pin


class AdminPinTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 22, tzinfo=UTC)

    def test_hash_is_salted_and_verifiable(self):
        first = hash_pin("7392")
        self.assertNotEqual(first, hash_pin("7392"))
        self.assertTrue(verify_pin("7392", first))
        self.assertFalse(verify_pin("7393", first))

    def test_malformed_pin_or_hash_fails_closed(self):
        encoded = hash_pin("7392")
        for pin in ("", "123", "12345", "abcd", "１２３４"):
            self.assertFalse(verify_pin(pin, encoded))
            with self.assertRaises(ValueError):
                hash_pin(pin)
        for malformed in ("", "scrypt-v1$aa$bb", "scrypt-v2$aa$bb", "x$zz$zz"):
            self.assertFalse(verify_pin("7392", malformed))

    def test_third_failure_blocks_for_24_hours(self):
        failures = 0
        for remaining in (2, 1, 0):
            result = evaluate_attempt(failures, None, self.now, False)
            self.assertEqual(result.remaining, remaining)
            failures = result.failures
        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.locked_until, self.now + timedelta(hours=24))

    def test_correct_pin_cannot_bypass_active_lock(self):
        until = self.now + timedelta(hours=24)
        result = evaluate_attempt(3, until, self.now + timedelta(hours=23), True)
        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.locked_until, until)

    def test_retries_do_not_extend_lock(self):
        until = self.now + timedelta(hours=24)
        result = evaluate_attempt(3, until, self.now + timedelta(hours=1), False)
        self.assertEqual(result.locked_until, until)

    def test_exact_expiry_starts_fresh_attempt_window(self):
        result = evaluate_attempt(3, self.now, self.now, False)
        self.assertEqual(result.state, "invalid_pin")
        self.assertEqual(result.remaining, 2)
        self.assertIsNone(result.locked_until)

    def test_success_resets_failures(self):
        result = evaluate_attempt(2, None, self.now, True)
        self.assertEqual(result.state, "authorized")
        self.assertEqual(result.failures, 0)


if __name__ == "__main__":
    unittest.main()
