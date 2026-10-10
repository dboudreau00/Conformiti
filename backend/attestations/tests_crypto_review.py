"""Signing-key creation under concurrency, and the strictness of verify.py's
Ed25519 point decoding."""
import os
import tempfile
import threading
from pathlib import Path

from django.test import SimpleTestCase

from attestations import signing, verifier


class KeyFileCreationTests(SimpleTestCase):
    def test_the_key_file_appears_complete_and_only_one_worker_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets" / "signing.pem"
            results = []

            def worker():
                results.append(signing._generate_into(path))

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            winners = [r for r in results if r is not None]
            self.assertEqual(len(winners), 1)
            # What is on disk is the winner's key, whole, mode 0600.
            on_disk = signing._parse_private(path.read_text(encoding="utf-8"), "test")
            self.assertEqual(signing.public_b64(on_disk.public_key()),
                             signing.public_b64(winners[0].public_key()))
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            # No temporary file is left behind.
            self.assertEqual([p.name for p in path.parent.iterdir()], ["signing.pem"])


class PointDecodingTests(SimpleTestCase):
    def test_negative_zero_is_not_an_encoding(self):
        # y = 1 is the identity (x = 0); the sign bit set on x = 0 is "-0".
        canonical = (1).to_bytes(32, "little")
        negative_zero = ((1 << 255) | 1).to_bytes(32, "little")
        verifier._decode(canonical)
        with self.assertRaises(ValueError):
            verifier._decode(negative_zero)

    def test_a_good_signature_still_verifies(self):
        key = signing.ed25519.Ed25519PrivateKey.generate()
        message = b"manifest"
        sig = key.sign(message)
        self.assertTrue(verifier.ed25519_verify(signing.public_raw(key.public_key()), message, sig))
        self.assertFalse(verifier.ed25519_verify(signing.public_raw(key.public_key()), message + b"x", sig))


class KeyIdentityTests(SimpleTestCase):
    def test_a_blank_key_file_is_an_error_not_silent_unsigned(self):
        from django.core.exceptions import ImproperlyConfigured
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.pem"
            path.write_text("  \n", encoding="utf-8")
            with override_settings(SIGNING_KEY="", SIGNING_KEY_FILE=str(path)):
                signing._cache.update(path=None, mtime=None, key=None)
                with self.assertRaises(ImproperlyConfigured):
                    signing.load_private_key(create=True)
                signing._cache.update(path=None, mtime=None, key=None)


from attestations.tests import PackageTestBase  # noqa: E402


class KeyRegistrationTests(PackageTestBase):
    def test_a_colliding_short_id_cannot_take_over_a_registered_key(self):
        from django.core.exceptions import ImproperlyConfigured
        from unittest import mock

        from attestations.models import SigningKey

        mine = signing.active_private_key().public_key()
        signing.register_key(signing.public_b64(mine))
        other = signing.ed25519.Ed25519PrivateKey.generate().public_key()
        with mock.patch.object(signing, "key_id", return_value=signing.key_id(mine)):
            with self.assertRaises(ImproperlyConfigured):
                signing.register_key(signing.public_b64(other))
        row = SigningKey.objects.get(key_id=signing.key_id(mine))
        self.assertEqual(row.public_key, signing.public_b64(mine))
