"""install.sh and install.ps1 before they touch anything, and the documents that count what the repository ships.

The shell blocks are cut out of install.sh and run in bash with the commands they call stubbed, as the entrypoint
tests do; install.ps1 is checked as text, because no PowerShell is assumed on the machine that runs the suite."""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent.parent
INSTALL_SH = (ROOT / "install.sh").read_text(encoding="utf-8")
INSTALL_PS1 = (ROOT / "install.ps1").read_text(encoding="utf-8")


def _posix_bash():
    """A bash that runs a script in this process's environment, or None.
    On Windows, System32's bash.exe starts WSL instead."""
    found = shutil.which("bash")
    if found and os.name == "nt" and "system32" in found.lower():
        return None
    return found


def _block(source, start, end="esac\n"):
    """The text from ``start`` to the first ``end`` after it."""
    first = source.index(start)
    return source[first:source.index(end, first) + len(end)]


@skipUnless(_posix_bash(), "needs bash")
class GitBashGuardTests(SimpleTestCase):
    """A Windows Python makes .venv/Scripts/python.exe, not .venv/bin/python, so install.sh run from Git Bash took the
    new .venv for a broken one, deleted it and blamed a Debian package. It has to stop before that step."""

    guard = _block(INSTALL_SH, 'case "$(uname -s')

    def run_guard(self, kernel):
        script = ("set -euo pipefail\n"
                  "die() { printf 'Error: %s\\n' \"$*\" >&2; exit 1; }\n"
                  f"uname() {{ echo {shlex.quote(kernel)}; }}\n"
                  f"{self.guard}echo CONTINUES\n")
        return subprocess.run([_posix_bash(), "-c", script], capture_output=True, text=True, timeout=30)

    def test_git_bash_and_cygwin_are_sent_to_install_ps1_or_wsl(self):
        for kernel in ("MINGW64_NT-10.0-26100", "MINGW32_NT-6.1-7601", "MSYS_NT-10.0-26100", "CYGWIN_NT-10.0-26100"):
            with self.subTest(kernel=kernel):
                done = self.run_guard(kernel)
                self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
                self.assertNotIn("CONTINUES", done.stdout)
                self.assertIn("install.ps1", done.stderr)
                self.assertIn("WSL", done.stderr)

    def test_linux_and_macos_go_on(self):
        for kernel in ("Linux", "Darwin"):
            with self.subTest(kernel=kernel):
                done = self.run_guard(kernel)
                self.assertEqual((done.returncode, done.stdout.strip()), (0, "CONTINUES"), done.stderr)

    def test_the_guard_sits_before_the_first_step_that_creates_or_removes_a_venv(self):
        guard_at = INSTALL_SH.index("MINGW*|MSYS*|CYGWIN*")
        for step in ("rm -rf .venv", '-m venv .venv', "cp .env.example .env", "npm ci"):
            self.assertLess(guard_at, INSTALL_SH.index(step), step)

    def test_the_whole_script_stops_in_git_bash_having_changed_nothing(self):
        # An empty folder holding only the script: had the guard not stopped it, the run would have ended at its
        # first missing file, with another message and nothing worth losing.
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(ROOT / "install.sh", tmp)
            script = "uname() { echo MINGW64_NT-10.0-26100; }\nexport -f uname\nexec bash ./install.sh --setup-only\n"
            done = subprocess.run([_posix_bash(), "-c", script], cwd=tmp, capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("install.ps1", done.stderr)
            self.assertEqual(os.listdir(tmp), ["install.sh"])


@skipUnless(_posix_bash(), "needs bash")
class SyncedFolderWarningTests(SimpleTestCase):
    """A folder a sync client watches makes pip, npm and Vite fail part way or hang; install.sh says so up front."""

    block = _block(INSTALL_SH, 'case "$(pwd -P | tr')

    def warns_in(self, path):
        script = ("set -euo pipefail\n"
                  "warn() { printf 'WARN %s\\n' \"$*\"; }\n"
                  f"pwd() {{ printf '%s\\n' {shlex.quote(path)}; }}\n"
                  f"{self.block}echo DONE\n")
        done = subprocess.run([_posix_bash(), "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("DONE", done.stdout)
        return "WARN" in done.stdout

    def test_the_sync_services_are_named(self):
        for path in ("/mnt/c/Users/a/OneDrive/Desktop/Conformiti", "/mnt/c/Users/a/OneDrive - Contoso/c",
                     "/home/a/Dropbox/c", "/Users/a/iCloud Drive/c",
                     "/Users/a/Library/Mobile Documents/com~apple~CloudDocs/c",
                     "/Users/a/Library/CloudStorage/GoogleDrive-a@b.c/My Drive/c", "/mnt/c/Users/a/Google Drive/c"):
            with self.subTest(path=path):
                self.assertTrue(self.warns_in(path))

    def test_a_plain_folder_is_left_alone(self):
        for path in ("/home/a/conformiti", "/srv/conformiti", "/mnt/c/conformiti", "/home/a/clouds/c"):
            with self.subTest(path=path):
                self.assertFalse(self.warns_in(path))

    def test_install_ps1_warns_for_the_same_services(self):
        pattern = re.search(r"\$PSScriptRoot -match '([^']+)'", INSTALL_PS1)
        self.assertIsNotNone(pattern, "install.ps1 does not look at the folder it runs from")
        for name in ("OneDrive", "Dropbox", "iCloud", "Google"):
            self.assertIn(name, pattern.group(1))


PROMPT = "Load the sample workspace so you can look around first? [Y/n]"


@skipUnless(_posix_bash(), "needs bash")
class SampleWorkspaceQuestionTests(SimpleTestCase):
    """install.sh asks once whether to load the demo data, and only where nothing has already said and a person is there
    to answer; the answer then does what --demo or --no-demo does."""

    block = _block(INSTALL_SH, "have_terminal()", "\n}\n")

    def ask(self, *, mode="run", terminal=True, fresh="yes", demo_set="", assume_yes="", typed="\n"):
        script = ("set -euo pipefail\nCR=$(printf '\\r')\n"
                  f"{self.block}"
                  f"have_terminal() {{ return {0 if terminal else 1}; }}\n"
                  f"MODE={shlex.quote(mode)}; DEMO=false; DEMO_SET={shlex.quote(demo_set)}; "
                  f"ASSUME_YES={shlex.quote(assume_yes)}\n"
                  f"offer_demo {shlex.quote(fresh)}\n"
                  'echo; echo "DEMO=$DEMO DEMO_SET=$DEMO_SET"\n')
        done = subprocess.run([_posix_bash(), "-c", script], input=typed,capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return PROMPT in done.stdout, done.stdout.strip().splitlines()[-1]

    def test_it_asks_on_a_terminal_when_no_flag_was_given_and_enter_means_yes(self):
        for mode in ("run", "docker"):
            with self.subTest(mode=mode):
                self.assertEqual(self.ask(mode=mode), (True, "DEMO=true DEMO_SET=yes"))

    def test_the_answer_is_what_the_flag_would_have_set(self):
        for typed, demo in (("y\n", "true"), ("Y\n", "true"), ("yes\n", "true"), ("n\n", "false"), ("No\n", "false"),
                            ("maybe\n", "false"), ("", "false")):
            with self.subTest(typed=typed):
                self.assertEqual(self.ask(typed=typed), (True, f"DEMO={demo} DEMO_SET=yes"))

    def test_a_flag_means_no_question(self):
        # --demo or --no-demo sets DEMO_SET; DEMO keeps the value the flag gave it.
        self.assertEqual(self.ask(demo_set="yes"), (False, "DEMO=false DEMO_SET=yes"))

    def test_assume_yes_means_no_question(self):
        self.assertEqual(self.ask(assume_yes="yes"), (False, "DEMO=false DEMO_SET="))

    def test_without_a_terminal_it_does_not_ask(self):
        self.assertEqual(self.ask(terminal=False), (False, "DEMO=false DEMO_SET="))

    def test_the_modes_that_do_not_start_the_stack_never_ask(self):
        for mode in ("setup", "test", "reset"):
            with self.subTest(mode=mode):
                self.assertEqual(self.ask(mode=mode), (False, "DEMO=false DEMO_SET="))

    def test_a_kept_installation_is_not_asked(self):
        self.assertEqual(self.ask(fresh=""), (False, "DEMO=false DEMO_SET="))

    def test_a_piped_run_does_not_wait_for_an_answer(self):
        # The real terminal test, not the stub: under subprocess, standard input and output are pipes.
        script = (f"CR=$(printf '\\r')\n{self.block}MODE=run; DEMO=false; DEMO_SET=; ASSUME_YES=\n"
                  'offer_demo yes\necho "DEMO=$DEMO DEMO_SET=$DEMO_SET"\n')
        done = subprocess.run([_posix_bash(), "-c", script], input="", capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "DEMO=false DEMO_SET="), done.stderr)

    def test_it_is_called_where_the_stack_is_about_to_start_and_before_anything_uses_the_answer(self):
        docker_call = INSTALL_SH.index('offer_demo "$FRESH"')
        self.assertLess(docker_call, INSTALL_SH.index("cat > .env <<ENV"))
        self.assertLess(docker_call, INSTALL_SH.index("docker compose up -d --build"))
        local_call = INSTALL_SH.index('offer_demo "$ENV_CREATED"')
        self.assertGreater(local_call, INSTALL_SH.index('ENV_CREATED="yes"'))
        self.assertLess(local_call, INSTALL_SH.index('say "Installing frontend dependencies'))
        self.assertLess(local_call, INSTALL_SH.index('DEMO_PW=""; DEMO_STATE=""'))

    def test_the_help_text_says_so(self):
        help_text = re.sub(r"\n# ?", " ", INSTALL_SH.split("set -euo pipefail")[0])
        self.assertIn(PROMPT, help_text)

    def test_install_ps1_asks_the_same_question_in_the_same_places(self):
        self.assertIn(PROMPT, INSTALL_PS1)
        function = _block(INSTALL_PS1, "function Request-DemoChoice", "\n}\n")
        for guard in ("$Demo -or $NoDemo -or $Yes -or -not $Fresh",
                      "-not $Docker -and ($SetupOnly -or $Test -or $Reset)",
                      "[Console]::IsInputRedirected -or [Console]::IsOutputRedirected"):
            self.assertIn(guard, function)
        self.assertIn("$script:Demo = $true", function)
        self.assertIn("$script:NoDemo = $true", function)
        docker_call = INSTALL_PS1.index("Request-DemoChoice ((-not")
        self.assertLess(docker_call, INSTALL_PS1.index('"SEED_DEMO_DATA=$seedDemo"'))
        local_call = INSTALL_PS1.index("Request-DemoChoice $envCreated")
        self.assertGreater(local_call, INSTALL_PS1.index("$envCreated = $true"))
        self.assertLess(local_call, INSTALL_PS1.index("if ($Reset) {"))


class InstallerFollowUpTests(SimpleTestCase):
    def test_install_ps1_warns_when_the_folder_tree_step_fails(self):
        """The step's exit code was thrown away, so the installer said "database ready" over missing folders."""
        self.assertNotIn("$null = Probe $pyexe manage.py generate_folder_tree", INSTALL_PS1)
        self.assertRegex(
            INSTALL_PS1,
            r"\$treeCode = Probe \$pyexe manage\.py generate_folder_tree\s+if \(\$treeCode -ne 0\) \{\s+Warn ")

    def test_both_installers_wait_six_minutes_and_say_the_stack_may_still_be_starting(self):
        self.assertIn('wait_for_health "http://localhost:${PORT}/api/health/" 360', INSTALL_SH)
        self.assertIn("[int]$Seconds = 360", INSTALL_PS1)
        for source in (INSTALL_SH, INSTALL_PS1):
            self.assertIn("Still not healthy after 360 seconds", source)
            self.assertNotIn("did not become healthy in time", source)


class ValidatorCountInDocumentsTests(SimpleTestCase):
    """README, TESTING, VALIDATION and CONTRIBUTING each said a different number of static checks."""

    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_every_document_states_the_number_of_checks_the_validator_defines(self):
        checks = len(re.findall(r"^def check_\w+\(", self.read("tools/validate.py"), re.M))
        self.assertGreater(checks, 10)
        self.assertIn(f"**{checks} static checks**", self.read("README.md"))
        self.assertIn(f"({checks} static checks)", self.read("TESTING.md"))
        self.assertIn(f"({checks} checks)", self.read("CONTRIBUTING.md"))
        self.assertEqual(len(re.findall(r"^\| \d+ \| ", self.read("VALIDATION.md"), re.M)), checks)
