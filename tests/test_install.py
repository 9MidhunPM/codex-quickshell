"""Isolated additive-installer tests; never contact the user's service manager."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "public_codex_installer", Path(__file__).resolve().parents[1] / "scripts/install.py"
)
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
TEMPLATE = (installer.REPO / "systemd" / (installer.UNIT + ".in")).read_bytes()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.config = self.base / "config/quickshell"
        self.config.mkdir(parents=True)
        self.originals = {"shell.qml": b"// An unrelated existing shell\n",
                          "Bar.qml": b"// An unrelated existing bar\n"}
        for name, data in self.originals.items():
            (self.config / name).write_bytes(data)
        self.state = self.base / "state/install"
        self.units = self.base / "systemd/user"
        self.module = self.config / "modules" / installer.MODULE
        self.repo = self.base / "checkout with spaces % $"
        (self.repo / "qml").mkdir(parents=True)
        (self.repo / "systemd").mkdir()
        self.assets = {"CodexStatus.qml": b"import Quickshell\nScope {}\n",
                       "CodexPill.qml": b"import QtQuick\nItem {}\n",
                       "StatusFormat.js": b"function value() { return 0; }\n",
                       "qmldir": b"CodexStatus 1.0 CodexStatus.qml\n"}
        for name, data in self.assets.items():
            (self.repo / "qml" / name).write_bytes(data)
        (self.repo / "qml/preview.qml").write_text("// Preview fixtures are not distributed\n")
        (self.repo / "qml/test-format.cjs").write_text("// Tests are not distributed\n")
        (self.repo / "systemd" / (installer.UNIT + ".in")).write_bytes(TEMPLATE)
        self.addCleanup(patch.stopall)
        patch.object(installer, "REPO", self.repo).start()
        patch.object(installer.shutil, "which", return_value="/usr/bin/codex").start()
        self.systemctl = patch.object(installer, "run_systemctl",
                                     side_effect=AssertionError("Unexpected systemctl call")).start()
        patch.object(installer, "read_service_definition",
                     side_effect=AssertionError("Unexpected manager metadata query")).start()

    def invoke(self, *args, service=False, module=None):
        argv = ["--config-root", str(self.config), "--state-root", str(self.state),
                "--unit-root", str(self.units)]
        if not service:
            argv.append("--no-service")
        if module is not None:
            argv.extend(("--module-dir", str(module)))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = installer.main([*argv, *args])
        return result, output.getvalue()

    def invoke_default_roots(self, *args):
        output = io.StringIO()
        with patch.object(installer, "default_roots", return_value=(self.config, self.state, self.units)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = installer.main(list(args))
        return result, output.getvalue()

    def install(self, *args, **kwargs):
        result, output = self.invoke("--install", *args, **kwargs)
        self.assertEqual(result, 0, output)

    def manifest(self):
        return json.loads((self.state / installer.MANIFEST).read_text())

    def owned_definition(self):
        return {"LoadState": "loaded", "FragmentPath": str(self.units / installer.UNIT)}

    def rewrite_manifest(self, value):
        (self.state / installer.MANIFEST).write_bytes(installer.encode_manifest(value))

    def assert_originals(self):
        for name, data in self.originals.items():
            self.assertEqual((self.config / name).read_bytes(), data)

    def tree(self):
        return sorted(str(path) for path in self.base.rglob("*"))

    def test_default_is_a_non_mutating_dry_run(self):
        before = self.tree()
        result, output = self.invoke()
        self.assertEqual(result, 0, output)
        self.assertIn("Dry-run", output)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.state.exists())
        self.assert_originals()

    def test_explicit_dry_run_overrides_install(self):
        before = self.tree()
        self.assertEqual(self.invoke("--install", "--dry-run")[0], 0)
        self.assertEqual(self.tree(), before)

    def test_install_is_additive_and_copies_only_module_assets(self):
        self.install()
        self.assertEqual({path.name for path in self.module.iterdir()}, set(self.assets))
        for name, data in self.assets.items():
            path = self.module / name
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.read_bytes(), data)
        self.assert_originals()
        self.assertFalse(self.units.exists())
        self.systemctl.assert_not_called()

    def test_installed_qml_survives_source_changes(self):
        self.install()
        (self.repo / "qml/CodexStatus.qml").write_bytes(b"// different source\n")
        self.assertEqual((self.module / "CodexStatus.qml").read_bytes(), self.assets["CodexStatus.qml"])

    def test_existing_shell_contents_are_never_read(self):
        read = Path.read_bytes

        def guarded(path):
            if path in [self.config / name for name in self.originals]:
                raise AssertionError("Existing shell was read")
            return read(path)

        with patch.object(Path, "read_bytes", guarded):
            self.install()

    def test_standalone_is_a_new_configuration(self):
        self.install("--standalone")
        wrapper = (self.config / "codex-status/shell.qml").read_text()
        self.assertIn("import " + json.dumps(self.module.as_uri()) + " as CodexModule", wrapper)
        self.assertIn("CodexModule.CodexStatus", wrapper)
        self.assert_originals()

    def test_standalone_import_encodes_url_sensitive_characters(self):
        module = self.config / 'modules/name " ? # % é'
        self.install("--standalone", module=module)
        wrapper = (self.config / "codex-status/shell.qml").read_text()
        self.assertIn(json.dumps(module.as_uri()), wrapper)
        self.assertNotIn('import "file://' + str(module), wrapper)

    def test_custom_module_directory_within_config_root(self):
        module = self.config / "plugins/codex"
        self.install(module=module)
        self.assertTrue((module / "qmldir").is_file())
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertFalse(module.exists())

    def test_module_outside_config_root_is_refused(self):
        result, output = self.invoke("--install", module=self.base / "outside")
        self.assertEqual(result, 1)
        self.assertIn("child of", output)
        self.assertFalse(self.state.exists())

    def test_module_cannot_equal_config_root(self):
        self.assertEqual(self.invoke("--install", module=self.config)[0], 1)

    def test_module_cannot_overlap_standalone_configuration(self):
        for module in (self.config / "codex-status", self.config / "codex-status/nested"):
            with self.subTest(module=module):
                self.assertEqual(self.invoke("--install", module=module)[0], 1)

    def test_relative_and_traversing_paths_are_refused(self):
        for module in ("relative/module", str(self.config / "modules/../escape")):
            with self.subTest(module=module):
                self.assertEqual(self.invoke("--install", module=module)[0], 1)

    def test_control_characters_in_paths_are_refused(self):
        for suffix in ("\nnew", "\tnew", "\x00new", "\x7fnew"):
            with self.subTest(suffix=repr(suffix)):
                self.assertEqual(self.invoke("--install", module=str(self.config / "module") + suffix)[0], 1)

    def test_overlapping_roots_are_refused(self):
        self.state = self.config / "private-state"
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("separate", output)

    def test_symlinked_config_root_is_refused(self):
        real = self.config
        self.config = self.base / "linked-config"
        self.config.symlink_to(real, target_is_directory=True)
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertFalse(self.state.exists())

    def test_symlinked_state_ancestor_is_refused(self):
        real = self.base / "real-state"
        real.mkdir()
        (self.base / "state").symlink_to(real, target_is_directory=True)
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertFalse(self.module.exists())

    def test_symlinked_unit_ancestor_is_refused(self):
        real = self.base / "real-units"
        real.mkdir()
        (self.base / "systemd").symlink_to(real, target_is_directory=True)
        self.assertEqual(self.invoke("--install", service=True)[0], 1)
        self.assertFalse(self.module.exists())

    def test_module_only_ignores_unrelated_symlinked_unit_directory(self):
        real = self.base / "real-units"
        real.mkdir()
        (self.base / "systemd").symlink_to(real, target_is_directory=True)
        self.install()
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertTrue((self.base / "systemd").is_symlink())
        self.assertEqual(list(real.iterdir()), [])
        self.systemctl.assert_not_called()

    def test_writable_config_ancestor_is_refused(self):
        self.config.parent.chmod(0o777)
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("Unsafe writable directory", output)

    def test_foreign_empty_module_directory_is_preserved(self):
        self.module.mkdir(parents=True)
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("without an owned manifest", output)
        self.assertTrue(self.module.is_dir())
        self.assertFalse(self.state.exists())

    def test_foreign_module_file_is_preserved(self):
        self.module.parent.mkdir(parents=True)
        self.module.write_bytes(b"foreign")
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertEqual(self.module.read_bytes(), b"foreign")

    def test_foreign_module_symlink_is_preserved(self):
        self.module.parent.mkdir(parents=True)
        self.module.symlink_to(self.repo / "qml")
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertTrue(self.module.is_symlink())

    def test_foreign_unit_is_never_replaced(self):
        self.units.mkdir(parents=True)
        unit = self.units / installer.UNIT
        unit.write_bytes(b"foreign user service")
        result, output = self.invoke("--install", service=True)
        self.assertEqual(result, 1)
        self.assertIn("existing file", output)
        self.assertEqual(unit.read_bytes(), b"foreign user service")
        self.assertFalse(self.module.exists())

    def test_no_service_install_leaves_foreign_unit_untouched(self):
        self.units.mkdir(parents=True)
        unit = self.units / installer.UNIT
        unit.write_bytes(b"foreign")
        self.install()
        self.assertEqual(unit.read_bytes(), b"foreign")
        self.assertFalse(self.manifest()["settings"]["service"])

    def test_foreign_standalone_configuration_is_preserved(self):
        standalone = self.config / "codex-status"
        standalone.mkdir()
        (standalone / "shell.qml").write_bytes(b"foreign")
        self.assertEqual(self.invoke("--install", "--standalone")[0], 1)
        self.assertEqual((standalone / "shell.qml").read_bytes(), b"foreign")

    def test_missing_required_source_is_refused(self):
        (self.repo / "qml/qmldir").unlink()
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertFalse(self.state.exists())

    def test_symlinked_source_asset_is_refused(self):
        path = self.repo / "qml/CodexStatus.qml"
        path.unlink()
        path.symlink_to(self.repo / "qml/CodexPill.qml")
        self.assertEqual(self.invoke("--install")[0], 1)

    def test_writable_source_asset_is_refused(self):
        (self.repo / "qml/CodexStatus.qml").chmod(0o666)
        self.assertEqual(self.invoke("--install")[0], 1)

    def test_oversized_source_asset_is_refused(self):
        with patch.object(installer, "MAX_ASSET", 10):
            self.assertEqual(self.invoke("--install")[0], 1)
        self.assertFalse(self.module.exists())

    def test_all_created_assets_and_state_are_private(self):
        self.install("--standalone", service=True)
        for item in self.manifest()["files"]:
            self.assertEqual(stat.S_IMODE(Path(item["path"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state / installer.MANIFEST).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.module.stat().st_mode), 0o700)

    def test_repeat_install_is_idempotent(self):
        self.install("--standalone")
        before = (self.state / installer.MANIFEST).read_bytes()
        result, output = self.invoke("--install", "--standalone")
        self.assertEqual(result, 0, output)
        self.assertIn("Already installed", output)
        self.assertEqual((self.state / installer.MANIFEST).read_bytes(), before)

    def test_changed_install_options_require_uninstall_first(self):
        self.install()
        result, output = self.invoke("--install", "--standalone")
        self.assertEqual(result, 1)
        self.assertIn("uninstall before reinstalling", output)
        self.assertFalse((self.config / "codex-status").exists())

    def test_changed_source_does_not_overwrite_installed_version(self):
        self.install()
        (self.repo / "qml/StatusFormat.js").write_bytes(b"// updated release")
        self.assertEqual(self.invoke("--install")[0], 1)
        self.assertEqual((self.module / "StatusFormat.js").read_bytes(), self.assets["StatusFormat.js"])
        self.assertEqual(self.invoke("--uninstall")[0], 0)

    def test_uninstall_exact_and_repeatable(self):
        self.install("--standalone")
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertFalse(self.module.exists())
        self.assertFalse(self.state.exists())
        self.assertFalse((self.config / "codex-status").exists())
        self.assert_originals()
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertIn("Already uninstalled", output)

    def test_uninstall_dry_run_preserves_owned_files(self):
        self.install("--standalone", service=True)
        before = self.tree()
        result, output = self.invoke("--uninstall", "--dry-run", service=True)
        self.assertEqual(result, 0, output)
        self.assertEqual(before, self.tree())
        self.systemctl.assert_not_called()

    def test_modified_module_file_blocks_all_uninstall_changes(self):
        self.install("--standalone", service=True)
        path = self.module / "CodexStatus.qml"
        path.write_bytes(b"// user modified")
        before = self.tree()
        result, output = self.invoke("--uninstall", service=True)
        self.assertEqual(result, 1)
        self.assertIn("preserving all files", output)
        self.assertEqual(before, self.tree())
        self.assertEqual(path.read_bytes(), b"// user modified")

    def test_modified_unit_blocks_module_deletion(self):
        self.install(service=True)
        (self.units / installer.UNIT).write_bytes(b"foreign replacement")
        self.assertEqual(self.invoke("--uninstall", service=True)[0], 1)
        self.assertTrue((self.module / "qmldir").exists())

    def test_modified_wrapper_blocks_module_deletion(self):
        self.install("--standalone")
        (self.config / "codex-status/shell.qml").write_bytes(b"user modified")
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        self.assertTrue(self.module.exists())

    def test_uninstall_preserves_untracked_files_and_their_directory(self):
        self.install()
        extra = self.module / "personal-notes.txt"
        extra.write_bytes(b"unrelated local note")
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertEqual(extra.read_bytes(), b"unrelated local note")
        self.assertEqual(list(self.module.iterdir()), [extra])

    def test_uninstall_can_resume_after_owned_file_already_removed(self):
        self.install()
        (self.module / "CodexPill.qml").unlink()
        self.assertEqual(self.invoke("--uninstall")[0], 0)
        self.assertFalse(self.module.exists())

    def test_uninstall_does_not_require_checkout_assets(self):
        self.install()
        for path in (self.repo / "qml").iterdir():
            path.unlink()
        self.assertEqual(self.invoke("--uninstall")[0], 0)

    def test_fixture_unit_install_and_uninstall_never_control_systemd(self):
        self.install(service=True)
        self.assertTrue((self.units / installer.UNIT).exists())
        self.assertEqual(self.invoke("--uninstall", service=True)[0], 0)
        self.systemctl.assert_not_called()

    def test_no_service_cannot_hide_an_installed_service_during_uninstall(self):
        self.install(service=True)
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 1)
        self.assertIn("omit --no-service", output)
        self.assertTrue((self.units / installer.UNIT).exists())

    def test_fixture_activation_is_refused_before_any_mutation(self):
        result, output = self.invoke("--install", "--activate", service=True)
        self.assertEqual(result, 1)
        self.assertIn("default user roots", output)
        self.assertFalse(self.state.exists())
        self.systemctl.assert_not_called()

    def test_no_service_and_activation_are_incompatible(self):
        self.assertEqual(self.invoke("--install", "--activate")[0], 1)

    def test_default_root_activation_is_explicit_and_ordered(self):
        with patch.object(installer, "assert_service_name_unused") as probe, \
                patch.object(installer, "read_service_definition", return_value=self.owned_definition()), \
                patch.object(installer, "run_systemctl") as control:
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 0, output)
        probe.assert_called_once_with()
        self.assertEqual([call.args for call in control.call_args_list],
                         [("daemon-reload",), ("enable", "--now", installer.UNIT)])
        self.assertTrue(self.manifest()["settings"]["activated"])

    def test_activation_dry_run_never_contacts_service_manager(self):
        with patch.object(installer, "assert_service_name_unused", side_effect=AssertionError("probe")):
            result, output = self.invoke_default_roots("--activate")
        self.assertEqual(result, 0, output)
        self.assertFalse(self.state.exists())
        self.systemctl.assert_not_called()

    def test_failed_activation_rolls_back_after_stopping_its_service(self):
        calls = []

        def control(*args):
            calls.append(args)
            if args == ("enable", "--now", installer.UNIT):
                raise installer.InstallError("activation failed")

        with patch.object(installer, "assert_service_name_unused"), \
                patch.object(installer, "read_service_definition", return_value=self.owned_definition()), \
                patch.object(installer, "run_systemctl", side_effect=control):
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertIn("rolled back", output)
        self.assertIn(("disable", "--now", installer.UNIT), calls)
        self.assertEqual(calls[-1], ("daemon-reload",))
        self.assertFalse(self.module.exists())
        self.assertFalse(self.state.exists())

    def test_failed_activation_cleanup_retains_all_owned_assets(self):
        def control(*args):
            if args[0] in ("enable", "disable"):
                raise installer.InstallError("user manager unavailable")

        with patch.object(installer, "assert_service_name_unused"), \
                patch.object(installer, "read_service_definition", return_value=self.owned_definition()), \
                patch.object(installer, "run_systemctl", side_effect=control):
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertIn("manifest retained", output)
        self.assertEqual(self.manifest()["status"], "installing")
        self.assertTrue((self.module / "qmldir").exists())
        self.assertTrue((self.units / installer.UNIT).exists())

    def test_unknown_existing_service_blocks_activation_before_files(self):
        with patch.object(installer, "assert_service_name_unused",
                          side_effect=installer.InstallError("foreign global unit")):
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.module.exists())
        self.systemctl.assert_not_called()

    def test_default_root_uninstall_stops_only_verified_owned_unit(self):
        result, output = self.invoke_default_roots("--install")
        self.assertEqual(result, 0, output)
        self.systemctl.assert_not_called()
        with patch.object(installer, "read_service_definition", return_value=self.owned_definition()), \
                patch.object(installer, "run_systemctl") as control:
            result, output = self.invoke_default_roots("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertEqual([call.args for call in control.call_args_list],
                         [("disable", "--now", installer.UNIT), ("daemon-reload",)])

    def test_missing_owned_unit_never_stops_a_foreign_manager_definition(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        (self.units / installer.UNIT).unlink()
        before = self.tree()
        foreign = {"LoadState": "loaded", "FragmentPath": "/etc/systemd/user/codex-quickshell.service"}
        with patch.object(installer, "read_service_definition", return_value=foreign):
            result, output = self.invoke_default_roots("--uninstall")
        self.assertEqual(result, 1)
        self.assertIn("foreign", output)
        self.assertEqual(before, self.tree())
        self.systemctl.assert_not_called()

    def test_existing_owned_file_does_not_authorize_stopping_foreign_loaded_unit(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        foreign = {"LoadState": "loaded", "FragmentPath": "/run/user/1234/systemd/transient/codex-quickshell.service"}
        with patch.object(installer, "read_service_definition", return_value=foreign):
            self.assertEqual(self.invoke_default_roots("--uninstall")[0], 1)
        self.assertTrue((self.module / "qmldir").exists())
        self.assertTrue((self.units / installer.UNIT).exists())
        self.systemctl.assert_not_called()

    def test_missing_unit_and_confirmed_absent_manager_need_no_service_control(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        (self.units / installer.UNIT).unlink()
        absent = {"LoadState": "not-found", "FragmentPath": ""}
        with patch.object(installer, "read_service_definition", return_value=absent):
            result, output = self.invoke_default_roots("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.module.exists())
        self.systemctl.assert_not_called()

    def test_missing_unit_with_loaded_own_path_requires_manual_resolution(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        (self.units / installer.UNIT).unlink()
        with patch.object(installer, "read_service_definition", return_value=self.owned_definition()):
            result, output = self.invoke_default_roots("--uninstall")
        self.assertEqual(result, 1)
        self.assertIn("unit is missing while still loaded", output)
        self.assertTrue(self.state.exists())
        self.systemctl.assert_not_called()

    def test_unloaded_verified_unit_is_disabled_without_stopping_a_name(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        unloaded = {"LoadState": "not-found", "FragmentPath": ""}
        with patch.object(installer, "read_service_definition", return_value=unloaded), \
                patch.object(installer, "run_systemctl") as control:
            result, output = self.invoke_default_roots("--uninstall")
        self.assertEqual(result, 0, output)
        self.assertEqual([call.args for call in control.call_args_list],
                         [("disable", installer.UNIT), ("daemon-reload",)])

    def test_unverifiable_manager_preserves_all_files_during_uninstall(self):
        self.assertEqual(self.invoke_default_roots("--install")[0], 0)
        before = self.tree()
        with patch.object(installer, "read_service_definition",
                          side_effect=installer.InstallError("manager unavailable")):
            self.assertEqual(self.invoke_default_roots("--uninstall")[0], 1)
        self.assertEqual(before, self.tree())
        self.systemctl.assert_not_called()

    def test_activation_checks_loaded_fragment_before_enabling(self):
        foreign = {"LoadState": "loaded", "FragmentPath": "/etc/systemd/user/codex-quickshell.service"}
        with patch.object(installer, "assert_service_name_unused"), \
                patch.object(installer, "read_service_definition", return_value=foreign), \
                patch.object(installer, "run_systemctl") as control:
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertIn("foreign", output)
        self.assertFalse(self.state.exists())
        self.assertEqual([call.args for call in control.call_args_list],
                         [("daemon-reload",), ("daemon-reload",)])

    def test_rollback_never_stops_a_replacement_foreign_definition(self):
        foreign = {"LoadState": "loaded", "FragmentPath": "/etc/systemd/user/codex-quickshell.service"}
        calls = []

        def control(*args):
            calls.append(args)
            if args == ("enable", "--now", installer.UNIT):
                raise installer.InstallError("activation failed after definition changed")

        with patch.object(installer, "assert_service_name_unused"), \
                patch.object(installer, "read_service_definition", side_effect=[self.owned_definition(), foreign]), \
                patch.object(installer, "run_systemctl", side_effect=control):
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertIn("manifest retained", output)
        self.assertNotIn(("disable", "--now", installer.UNIT), calls)
        self.assertTrue((self.module / "qmldir").exists())

    def test_rollback_rechecks_disk_hash_before_stopping(self):
        calls = []

        def control(*args):
            calls.append(args)
            if args == ("enable", "--now", installer.UNIT):
                (self.units / installer.UNIT).write_bytes(b"concurrent foreign edit")
                raise installer.InstallError("activation failed after unit edit")

        with patch.object(installer, "assert_service_name_unused"), \
                patch.object(installer, "read_service_definition", return_value=self.owned_definition()), \
                patch.object(installer, "run_systemctl", side_effect=control):
            result, output = self.invoke_default_roots("--install", "--activate")
        self.assertEqual(result, 1)
        self.assertIn("manifest retained", output)
        self.assertNotIn(("disable", "--now", installer.UNIT), calls)
        self.assertEqual((self.units / installer.UNIT).read_bytes(), b"concurrent foreign edit")

    def test_service_options_are_incompatible_with_no_service(self):
        for flags in (("--terminal", "foot -e"), ("--codex-bin", "/usr/bin/codex"), ("--disable-actions",)):
            with self.subTest(flags=flags):
                self.assertEqual(self.invoke("--install", *flags)[0], 1)

    def test_missing_codex_cli_only_blocks_service_install(self):
        with patch.object(installer.shutil, "which", return_value=None):
            self.assertEqual(self.invoke("--install", service=True)[0], 1)
            self.install()

    def test_relative_codex_executable_is_refused(self):
        self.assertEqual(self.invoke("--install", "--codex-bin", "relative/codex", service=True)[0], 1)

    def test_quoted_home_codex_path_is_expanded_consistently(self):
        self.install("--codex-bin", "~/bin/codex", service=True)
        unit = (self.units / installer.UNIT).read_text()
        self.assertIn("--codex-bin " + installer.systemd_quote(str(Path.home() / "bin/codex")), unit)
        self.assertNotIn("/~/", unit)

    def test_literal_placeholder_text_in_paths_is_not_interpolated(self):
        binary = "/opt/@OPTIONS@/codex"
        terminal = "terminal --title @UNRELATED@ -e"
        self.install("--codex-bin", binary, "--terminal", terminal, service=True)
        unit = (self.units / installer.UNIT).read_text()
        self.assertIn("--codex-bin " + installer.systemd_quote(binary), unit)
        self.assertIn("--terminal " + installer.systemd_quote(terminal), unit)

    def test_rendered_unit_escapes_paths_and_terminal_arguments(self):
        self.install("--codex-bin", '/opt/program " $CODING %/codex',
                     "--terminal", 'terminal --title "$LABEL %n" -e', "--disable-actions", service=True)
        unit = (self.units / installer.UNIT).read_text()
        self.assertIn('"/opt/program \\" $$CODING %%/codex"', unit)
        self.assertIn('--terminal "terminal --title \\"$$LABEL %%n\\" -e" --disable-actions', unit)
        self.assertIn("WorkingDirectory=" + installer.systemd_directory(str(self.repo)), unit)
        self.assertNotIn("@OPTIONS@", unit)
        self.assertNotIn("kitty", unit)
        self.systemctl.assert_not_called()

    def test_control_characters_in_service_arguments_are_refused(self):
        self.assertEqual(self.invoke("--install", "--terminal", "foot\n-e", service=True)[0], 1)
        self.assertFalse(self.module.exists())

    def test_invalid_manifest_is_refused_without_mutation(self):
        self.install()
        path = self.state / installer.MANIFEST
        path.write_bytes(b"not json")
        before = self.tree()
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        self.assertEqual(before, self.tree())

    def test_manifest_cannot_record_an_unrelated_file(self):
        self.install()
        target = self.config / "shell.qml"
        value = self.manifest()
        value["files"][0] = {"path": str(target), "sha256": installer.digest(target.read_bytes()), "kind": "module"}
        self.rewrite_manifest(value)
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        self.assert_originals()
        self.assertTrue(self.module.exists())

    def test_manifest_cannot_record_unrelated_directories(self):
        self.install()
        unrelated = self.base / "unrelated-empty-directory"
        unrelated.mkdir()
        value = self.manifest()
        value["directories"].append(str(unrelated))
        self.rewrite_manifest(value)
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        self.assertTrue(unrelated.exists())

    def test_duplicate_manifest_file_is_refused(self):
        self.install()
        value = self.manifest()
        value["files"].append(value["files"][0])
        self.rewrite_manifest(value)
        self.assertEqual(self.invoke("--uninstall")[0], 1)

    def test_manifest_service_flag_must_match_unit_entry(self):
        self.install(service=True)
        value = self.manifest()
        value["files"] = [item for item in value["files"] if item["kind"] != "unit"]
        self.rewrite_manifest(value)
        self.assertEqual(self.invoke("--uninstall", service=True)[0], 1)

    def test_manifest_must_be_private(self):
        self.install()
        (self.state / installer.MANIFEST).chmod(0o644)
        result, output = self.invoke("--uninstall")
        self.assertEqual(result, 1)
        self.assertIn("private", output)

    def test_manifest_symlink_is_refused(self):
        self.install()
        path = self.state / installer.MANIFEST
        other = self.base / "manifest-copy"
        other.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(other)
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        self.assertTrue(self.module.exists())

    def test_foreign_state_files_are_not_claimed(self):
        self.state.mkdir(parents=True)
        (self.state / "foreign.txt").write_bytes(b"foreign")
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("foreign files", output)
        self.assertFalse(self.module.exists())

    def test_uninstall_refuses_changed_root_flags(self):
        self.install(service=True)
        self.units = self.base / "different-systemd"
        result, output = self.invoke("--uninstall", service=True)
        self.assertEqual(result, 1)
        self.assertIn("roots do not match", output)

    def test_mid_install_failure_rolls_back_only_new_files(self):
        publish = installer.atomic_publish

        def fail(path, data, **kwargs):
            if path == self.module / "StatusFormat.js":
                raise OSError("injected asset failure")
            return publish(path, data, **kwargs)

        with patch.object(installer, "atomic_publish", side_effect=fail):
            result, output = self.invoke("--install", "--standalone", service=True)
        self.assertEqual(result, 1)
        self.assertIn("rolled back", output)
        self.assertFalse(self.module.exists())
        self.assertFalse(self.state.exists())
        self.assertFalse(self.units.exists())
        self.assert_originals()

    def test_final_manifest_failure_rolls_back_assets(self):
        publish = installer.atomic_publish

        def fail(path, data, **kwargs):
            if kwargs.get("replace"):
                raise OSError("injected final manifest failure")
            return publish(path, data, **kwargs)

        with patch.object(installer, "atomic_publish", side_effect=fail):
            self.assertEqual(self.invoke("--install", service=True)[0], 1)
        self.assertFalse(self.module.exists())
        self.assertFalse(self.state.exists())

    def test_unit_that_appears_after_preflight_is_never_overwritten(self):
        publish = installer.atomic_publish
        unit = self.units / installer.UNIT

        def race(path, data, **kwargs):
            if path == unit:
                unit.write_bytes(b"concurrent foreign unit")
            return publish(path, data, **kwargs)

        with patch.object(installer, "atomic_publish", side_effect=race):
            self.assertEqual(self.invoke("--install", service=True)[0], 1)
        self.assertEqual(unit.read_bytes(), b"concurrent foreign unit")
        self.assertFalse(self.module.exists())
        self.assertFalse(self.state.exists())

    def test_modified_file_during_rollback_retains_recovery_manifest(self):
        publish = installer.atomic_publish
        changed = self.module / "CodexStatus.qml"

        def fail(path, data, **kwargs):
            if path == self.module / "StatusFormat.js":
                changed.write_bytes(b"concurrent user change")
                raise OSError("injected failure")
            return publish(path, data, **kwargs)

        with patch.object(installer, "atomic_publish", side_effect=fail):
            result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("manifest retained", output)
        self.assertEqual(self.manifest()["status"], "installing")
        self.assertEqual(changed.read_bytes(), b"concurrent user change")
        self.assertEqual(self.invoke("--uninstall")[0], 1)
        changed.write_bytes(self.assets["CodexStatus.qml"])
        self.assertEqual(self.invoke("--uninstall")[0], 0)

    def test_incomplete_install_manifest_requires_recovery_first(self):
        self.install()
        value = self.manifest()
        value["status"] = "installing"
        self.rewrite_manifest(value)
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("interrupted installation", output)
        self.assertEqual(self.invoke("--uninstall")[0], 0)

    def test_state_directory_must_be_private(self):
        self.state.mkdir(parents=True, mode=0o755)
        self.state.chmod(0o755)
        result, output = self.invoke("--install")
        self.assertEqual(result, 1)
        self.assertIn("private", output)
        self.assertFalse(self.module.exists())


class EncodingTests(unittest.TestCase):
    def test_working_directory_keeps_spaces_and_only_escapes_specifiers(self):
        self.assertEqual(installer.systemd_directory("/opt/source path %/"), "/opt/source path %%")
        self.assertEqual(installer.systemd_directory("/opt/source\\directory"), "/opt/source\\directory")

    def test_working_directory_refuses_unrepresentable_line_endings(self):
        for path in ("/opt/directory ", "/opt/directory\\"):
            with self.subTest(path=path), self.assertRaises(installer.InstallError):
                installer.systemd_directory(path)

    def test_systemd_word_escapes_expansion_characters(self):
        self.assertEqual(installer.systemd_quote('a"b\\c%d$e'), '"a\\"b\\\\c%%d$$e"')

    def test_control_characters_are_not_service_words(self):
        for value in ("a\nb", "a\rb", "a\x00b", "a\x7fb"):
            with self.subTest(value=repr(value)), self.assertRaises(installer.InstallError):
                installer.systemd_quote(value)


class ActivationProbeTests(unittest.TestCase):
    def test_missing_unit_is_the_only_safe_activation_state(self):
        result = subprocess.CompletedProcess([], 4, "LoadState=not-found\nFragmentPath=\n", "")
        with patch.object(installer.subprocess, "run", return_value=result) as run:
            installer.assert_service_name_unused()
        self.assertEqual(run.call_args.args[0],
                         ["systemctl", "--user", "show", "--no-pager", "--all", "--property=LoadState",
                          "--property=FragmentPath", installer.UNIT])

    def test_global_and_transient_units_are_refused(self):
        for output in ("LoadState=loaded\nFragmentPath=/etc/systemd/user/example.service\n",
                       "LoadState=loaded\nFragmentPath=\n", "", "LoadState=error\n"):
            with self.subTest(output=output), patch.object(
                    installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")), \
                    self.assertRaises(installer.InstallError):
                installer.assert_service_name_unused()

    def test_manager_failure_is_not_treated_as_unused_name(self):
        result = subprocess.CompletedProcess([], 1, "", "Cannot connect to bus")
        with patch.object(installer.subprocess, "run", return_value=result), \
                self.assertRaises(installer.InstallError):
            installer.assert_service_name_unused()

    def test_probe_timeout_is_a_safe_installation_error(self):
        with patch.object(installer.subprocess, "run", side_effect=subprocess.TimeoutExpired("systemctl", 20)), \
                self.assertRaises(installer.InstallError):
            installer.assert_service_name_unused()

    def test_ambiguous_or_incomplete_manager_metadata_is_refused(self):
        for output in ("LoadState=not-found\n", "FragmentPath=\n",
                       "LoadState=not-found\nLoadState=loaded\nFragmentPath=\n",
                       "LoadState=not-found\nFragmentPath=\nUnexpected=value\n"):
            with self.subTest(output=output), patch.object(
                    installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")), \
                    self.assertRaises(installer.InstallError):
                installer.read_service_definition()


if __name__ == "__main__":
    unittest.main()
