import os
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ENTRYPOINT = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")


def _posix_bash():
    """A bash that runs a script in this process's environment, or None.
    On Windows, System32's bash.exe starts WSL instead."""
    found = shutil.which("bash")
    if found and os.name == "nt" and "system32" in found.lower():
        return None
    return found


class ScannerBootWarningTests(SimpleTestCase):
    @skipUnless(_posix_bash(), "needs bash")
    def test_the_warning_follows_the_same_spellings_the_application_reads(self):
        """Runs the scanner check in bash with ``python`` stubbed to say clamd did not answer."""
        start = ENTRYPOINT.index("# Say at boot whether the scanner is reachable")
        block = ENTRYPOINT[start:]
        block = block[:block.index("\nfi\n") + len("\nfi\n")]
        script = ("set -euo pipefail\n"
                  "log() { printf '%s\n' \"$*\"; }\n"
                  "python() { return 1; }\n"
                  f"{block}")
        base = {k: v for k, v in os.environ.items() if not k.startswith("CLAMAV_")}
        for value, warns in (("true", True), ("True", True), ("1", True), ("yes", True), ("ON", True),
                             ("false", False), ("", False), ("0", False), ("no", False), ("off", False)):
            with self.subTest(CLAMAV_ENABLED=value):
                done = subprocess.run([_posix_bash(), "-c", script], env={**base, "CLAMAV_ENABLED": value},
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual("Malware scanning is ON but clamd did not answer" in done.stdout, warns, done.stdout)

    @skipUnless(_posix_bash(), "needs bash")
    def test_an_unset_flag_does_not_stop_the_boot(self):
        start = ENTRYPOINT.index("# Say at boot whether the scanner is reachable")
        block = ENTRYPOINT[start:]
        block = block[:block.index("\nfi\n") + len("\nfi\n")]
        script = f"set -euo pipefail\nlog() {{ :; }}\npython() {{ return 1; }}\n{block}echo booted\n"
        base = {k: v for k, v in os.environ.items() if not k.startswith("CLAMAV_")}
        done = subprocess.run([_posix_bash(), "-c", script], env=base, capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "booted"), done.stderr)
