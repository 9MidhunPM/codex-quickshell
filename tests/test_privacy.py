import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("privacy_guard", Path(__file__).resolve().parents[1] / "scripts/check_privacy.py")
guard = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = guard
SPEC.loader.exec_module(guard)


class PrivacyTests(unittest.TestCase):
    def test_personal_values_and_artifacts(self):
        self.assertTrue(guard.inspect("auth.json", b"{}"))
        self.assertTrue(guard.inspect("file", b"/home/" + b"private-person/project"))
        self.assertTrue(guard.inspect("file", b"user@" + b"mail.invalid"))
        self.assertTrue(guard.inspect("file", ("sk-" + "x" * 40).encode()))
        self.assertTrue(guard.inspect("file", b"private literal", ("private literal",)))
        self.assertTrue(guard.inspect("file.png", b"\0private literal", ("private literal",)))

    def test_documented_placeholders_are_safe(self):
        self.assertFalse(guard.inspect("README.md", b"/home/example/project user@example.com"))
        self.assertFalse(guard.inspect("README.md", b"123+example@users.noreply.github.com"))
        self.assertFalse(guard.inspect("README.md", b"/home/test/Codex Data"))

    def test_only_known_relative_example_links_are_allowed(self):
        self.assertTrue(guard.safe_link("examples/standalone/CodexStatusModule", b"../../qml"))
        self.assertFalse(guard.safe_link("other", b"../../qml"))
        self.assertFalse(guard.safe_link("examples/standalone/CodexStatusModule", b"/tmp/private"))

    def test_history_detects_deleted_leaks_and_commit_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", "-C", directory, *args], check=True,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            git("init", "-q")
            git("config", "user.name", "Example Contributor")
            git("config", "user.email", "contributor@example.com")
            git("config", "commit.gpgsign", "false")
            (root / "deleted.txt").write_text("sk-" + "x" * 40)
            git("add", "deleted.txt")
            git("commit", "-qm", "Fixture")
            (root / "deleted.txt").unlink()
            git("add", "-u")
            git("commit", "-qm", "Remove fixture")
            self.assertFalse(guard.check(root, False))
            self.assertTrue(any(i.rule == "provider-token" for i in guard.check(root, True)))
            git("commit", "--allow-empty", "-qm", "private-marker")
            self.assertTrue(any(i.path.startswith("commit:") for i in guard.check(root, True, ("private-marker",))))


if __name__ == "__main__":
    unittest.main()
