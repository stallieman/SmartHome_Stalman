"""Synthetic host files and mocked Docker only; never contacts a server or daemon."""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deployment", ROOT / "scripts/battery_audit_deployment.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.config = self.base / "config"
        self.config.mkdir()
        self.write(".HA_VERSION", b"2026.10.4")
        self.original_config = b"# preserve comment\nhomeassistant:\n  packages:\n    stalman_energie: !include packages/energie_thuisbatterij.yaml\nlovelace:\n  dashboards:\n    ring-cameras:\n      mode: yaml\n      filename: dashboards/ring_cameras.yaml\n"
        self.write("configuration.yaml", self.original_config)
        self.write("dashboards/ring_cameras.yaml", b"views: []\n")
        self.write("packages/energie_thuisbatterij.yaml", b"input_boolean:\n  original: {}\ntemplate:\n- sensor:\n  - name: Existing household sensor\n    unique_id: original_household\n    state: '1'\n  - name: Old financial sensor\n    unique_id: stalman_besparingsscenario\n    state: '0'\n")
        hashes = {}
        for name in d.SOURCE:
            data = ("synthetic original " + name).encode()
            self.write(d.PREFIX + name, data)
            hashes[name] = d.digest(data)
        self.entry = {"entry_id": d.ENTRY, "domain": "battery_sim", "options": {}, "data": {
            "size_kwh": 5.12, "max_charge_rate_kw": 2.5, "max_discharge_rate_kw": .8,
            "charge_efficiency": .91, "discharge_efficiency": .91, "update_frequency": 60,
            "input_list": [{"sensor_type": r.title(), "sensor_id": f"sensor.p1_meter_energie_{r}",
                            "simulated_sensor": f"simulated_sensor.p1_meter_energie_{r}",
                            "tariff_type": "No tariff information"} for r in ("import", "export")]}}
        self.write(".storage/core.config_entries", json.dumps({"data": {"entries": [self.entry]}}).encode())
        self.write("home-assistant_v2.db", b"synthetic recorder main database")
        self.backup = self.base / "backup.tar.gz"
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        self.args = argparse.Namespace(config=self.config, container="homeassistant", backup=self.backup,
                                       restore_root=self.base / "restore", restore_point=None,
                                       apply=False, authorize_root=True,
                                       authorize_runtime_check=False, health_timeout=30)
        self.running = True
        self.calls = []
        self.real_require_root = d.require_root
        for mock in (patch.object(d, "SOURCE", hashes),
                     patch.object(d, "RESTORE_ROOT", self.args.restore_root),
                     patch.object(d, "require_root", return_value=None),
                     patch.object(d, "transform", side_effect=lambda data: data + b"\n# synthetic instrumentation\n"),
                     patch.object(d, "command", side_effect=self.docker)):
            mock.start()
            self.addCleanup(mock.stop)
        self.originals = self.tree()

    def write(self, name, data):
        p = self.config / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def tree(self):
        return {str(p.relative_to(self.config)): (p.read_bytes(), p.stat().st_mode)
                for p in self.config.rglob("*") if p.is_file()}

    def docker(self, args, timeout=120):
        self.calls.append(args)
        if args[1] == "inspect":
            return (json.dumps(self.running) + "\n" + json.dumps(d.IMAGE) + "\n" + json.dumps([
                {"Destination": "/config", "Source": str(self.config), "RW": True, "Type": "bind"}])).encode()
        if args[1:3] == ["image", "inspect"]:
            return b'{"os":"linux","arch":"arm64"}'
        if args[1] == "exec":
            self.assertIn("-B", args)
            if "urllib.request" in args[-1]:
                return b'{"ready":true}'
            if "from homeassistant.const" in args[-1]:
                return json.dumps({"version": "2026.10.4", "uid": os.geteuid()}).encode()
            return b'{"audit":true,"sequence":1,"paired":true}'
        if args[1] == "run":
            self.assertIn("--pull=never", args)
            self.assertIn("--read-only", args)
            self.assertEqual(args[args.index("--network") + 1], "none")
            stage = Path(args[args.index("-v") + 1].removesuffix(":/config:rw"))
            d.yaml_module().compose((stage / "configuration.yaml").read_bytes())
            return b""
        if args[1] == "stop":
            self.running = False
            return b""
        if args[1] == "start":
            self.running = True
            return b""
        self.fail("Unexpected command")

    def install(self):
        self.args.apply = True
        self.args.authorize_runtime_check = True
        with contextlib.redirect_stdout(io.StringIO()):
            d.install(self.args)
        points = [p for p in self.args.restore_root.iterdir() if p.is_dir()]
        self.assertEqual(len(points), 1)
        self.args.restore_point = points[0]
        return points[0]

    def test_dry_run_has_no_writes_or_lifecycle_calls(self):
        with contextlib.redirect_stdout(io.StringIO()):
            d.install(self.args)
        self.assertEqual(self.tree(), self.originals)
        self.assertFalse(self.args.restore_root.exists())
        self.assertEqual(self.calls, [])

    def test_safe_file_diagnostics_distinguish_failure_types_without_paths(self):
        component = "Synthetic approved component"
        sensitive = self.base / "private-secret-name"
        cases = []
        cases.append(("missing", "required file is missing"))
        sensitive.mkdir()
        cases.append(("wrong_type", "expected a regular file, but found another file type"))
        sensitive.rmdir()
        sensitive.symlink_to(self.config / "configuration.yaml")
        cases.append(("symlink", "symlink is not allowed"))
        sensitive.unlink()
        sensitive.write_bytes(b"never disclose this content")
        for kind, expected in cases:
            with self.subTest(kind=kind):
                if kind == "missing":
                    sensitive.unlink(missing_ok=True)
                elif kind == "wrong_type":
                    sensitive.unlink(missing_ok=True)
                    sensitive.mkdir()
                else:
                    if sensitive.is_dir():
                        sensitive.rmdir()
                    sensitive.unlink(missing_ok=True)
                    sensitive.symlink_to(self.config / "configuration.yaml")
                with self.assertRaisesRegex(d.Stop, f"^{component}: {expected}\\.$") as caught:
                    d.regular(sensitive, component)
                message = str(caught.exception)
                self.assertNotIn(str(sensitive), message)
                self.assertNotIn("private-secret-name", message)
        sensitive.unlink()
        sensitive.write_bytes(b"never disclose this content")
        with patch.object(Path, "open", side_effect=PermissionError("private path detail")):
            with self.assertRaisesRegex(d.Stop, f"^{component}: file is unreadable\\.$") as caught:
                d.regular(sensitive, component)
        self.assertNotIn("private path detail", str(caught.exception))
        self.assertNotIn("never disclose", str(caught.exception))

    def test_parse_diagnostics_name_component_without_content(self):
        cases = ((d.json_document, b'{"secret":', "JSON parse failed"),
                 (d.plain_yaml, b"secret: [", "YAML parse failed"))
        for parser, payload, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(d.Stop, f"^Approved policy: {expected}\\.$") as caught:
                    parser(payload, "Approved policy")
                self.assertNotIn("secret", str(caught.exception))

    def test_dry_run_diagnostics_identify_version_storage_source_and_repository_inputs(self):
        version = self.config / ".HA_VERSION"
        version.unlink()
        with self.assertRaisesRegex(d.Stop, "^Home Assistant version marker: required file is missing\\.$"):
            d.install(self.args)
        self.write(".HA_VERSION", b"2026.10.4")

        storage = self.config / ".storage/core.config_entries"
        storage.write_bytes(b'{"private":')
        with self.assertRaisesRegex(d.Stop, "^Home Assistant storage metadata: JSON parse failed\\.$"):
            d.install(self.args)
        storage.write_bytes(self.originals[".storage/core.config_entries"][0])

        source = self.config / (d.PREFIX + "sensor.py")
        source.unlink()
        with self.assertRaisesRegex(d.Stop, "^Battery simulator sensor module: required file is missing\\.$"):
            d.install(self.args)
        self.write(d.PREFIX + "sensor.py", self.originals[d.PREFIX + "sensor.py"][0])

        with patch.object(d, "ROOT", self.base / "missing-repository"):
            with self.assertRaisesRegex(d.Stop, "^Repository battery audit helper: required file is missing\\.$"):
                d.install(self.args)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.restore_root.exists())

    def test_dry_run_reports_configuration_yaml_parse_failure(self):
        self.write("configuration.yaml", b"homeassistant: [private")
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        with self.assertRaisesRegex(d.Stop, "^Home Assistant configuration: YAML parse failed\\.$") as caught:
            d.install(self.args)
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_root_dry_run_hashes_complete_storage_without_writes(self):
        names = ("auth", "auth_provider.homeassistant", "core.uuid", "person", "onboarding",
                 "core.restore_state")
        protected = {self.config / ".storage" / name for name in names}
        for path in protected:
            self.write(str(path.relative_to(self.config)), b"synthetic protected data")
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        expected = self.tree()
        seen = set()
        original_digest = d.file_digest

        def record(path, component="Hash input"):
            seen.add(Path(path))
            return original_digest(path, component)

        with patch.object(d, "file_digest", side_effect=record), contextlib.redirect_stdout(io.StringIO()):
            d.install(self.args)
        self.assertTrue(protected <= seen)
        self.assertFalse(self.args.restore_root.exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.tree(), expected)

    def test_apply_still_requires_readable_files_for_full_snapshot(self):
        path = self.config / ".storage/auth"
        self.write(".storage/auth", b"synthetic protected data")
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(0)
        original_access = os.access

        def access(candidate, flags):
            return False if Path(candidate) == path else original_access(candidate, flags)

        try:
            self.args.apply = True
            with patch.object(d.os, "access", side_effect=access):
                with self.assertRaisesRegex(d.Stop, "Unreadable configuration file; backup impossible"):
                    d.install(self.args)
            self.assertFalse(self.args.restore_root.exists())
            self.assertEqual(self.calls, [])
        finally:
            path.chmod(mode)

    def test_runtime_checks_require_explicit_authorization(self):
        with self.assertRaises(d.Stop):
            d.main(["runtime-check", "--authorize-root", "--config", str(self.config)])
        self.assertEqual(self.calls, [])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(["runtime-check", "--authorize-runtime-check",
                                     "--authorize-root",
                                     "--config", str(self.config)]), 0)
        self.assertTrue(any(a[1] == "exec" for a in self.calls))

    def test_root_execution_requires_both_effective_root_and_explicit_flag(self):
        args = argparse.Namespace(authorize_root=False)
        with patch.object(d.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(d.Stop, "--authorize-root"):
                self.real_require_root(args)
        args.authorize_root = True
        with patch.object(d.os, "geteuid", return_value=1234):
            with self.assertRaisesRegex(d.Stop, "explicitly as root"):
                self.real_require_root(args)
        with patch.object(d.os, "geteuid", return_value=0):
            self.real_require_root(args)

    def test_apply_requires_runtime_authorization_before_side_effects(self):
        self.args.apply = True
        with self.assertRaises(d.Stop):
            d.install(self.args)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.tree(), self.originals)
        self.assertFalse(self.args.restore_root.exists())

    def test_cli_defaults_to_dry_run_and_rollback_requires_explicit_point(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(["install", "--config", str(self.config), "--backup", str(self.backup),
                                     "--authorize-root",
                                     "--restore-root", str(self.args.restore_root)]), 0)
        self.assertEqual(self.tree(), self.originals)
        self.assertFalse(self.args.restore_root.exists())
        with self.assertRaises(d.Stop):
            d.main(["rollback", "--config", str(self.config)])

    def test_apply_and_rollback_preserve_unmanaged_files_and_battery(self):
        point = self.install()
        self.assertEqual((self.config / "dashboards/ring_cameras.yaml").read_bytes(), b"views: []\n")
        self.assertIn(b"# preserve comment", (self.config / "configuration.yaml").read_bytes())
        policy = json.loads((self.config / "energy_finance/collector.json").read_bytes())
        self.assertTrue(policy["audit"]["enabled"])
        self.assertTrue(all(p["confirmed"] is False for p in json.loads(
            (self.config / "energy_finance/tariffs.json").read_bytes())["plans"]))
        package = d.plain_yaml((self.config / "packages/energie_thuisbatterij.yaml").read_bytes())
        self.assertIn("original", package["input_boolean"])
        self.assertIn("original_household", [s["unique_id"] for b in package["template"] for s in b.get("sensor", [])])
        self.write("energy_finance/intervals.sqlite", b"preserve new runtime evidence")
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        for name, (data, mode) in self.originals.items():
            self.assertEqual((self.config / name).read_bytes(), data)
            self.assertEqual((self.config / name).stat().st_mode, mode)
        self.assertEqual((self.config / "energy_finance/intervals.sqlite").read_bytes(), b"preserve new runtime evidence")
        self.assertFalse((self.config / (d.PREFIX + "stalman_audit.py")).exists())
        self.assertEqual(json.loads((point / "manifest.json").read_bytes())["phase"], "rolled_back")

    def test_new_and_replaced_files_have_explicit_metadata(self):
        existing = self.config / "configuration.yaml"
        existing.chmod(0o640)
        expected_owner = (existing.stat().st_uid, existing.stat().st_gid)
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        point = self.install()
        self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o640)
        self.assertEqual((existing.stat().st_uid, existing.stat().st_gid), expected_owner)
        for relative in ("energy_finance/collector.py", "packages/energie_audit_adapter.yaml",
                         d.PREFIX + "stalman_audit.py"):
            info = (self.config / relative).stat()
            self.assertEqual((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)),
                             (*expected_owner, d.CONFIG_FILE_MODE))
        finance = (self.config / "energy_finance").stat()
        self.assertEqual((finance.st_uid, finance.st_gid, stat.S_IMODE(finance.st_mode)),
                         (*expected_owner, d.CONFIG_DIRECTORY_MODE))
        for path in [point, *point.rglob("*")]:
            expected = d.PRIVATE_DIRECTORY_MODE if path.is_dir() else d.PRIVATE_FILE_MODE
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected)
            self.assertEqual((path.stat().st_uid, path.stat().st_gid), (os.geteuid(), os.getegid()))
        lock = self.args.restore_root / ".deployment.lock"
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), d.PRIVATE_FILE_MODE)

    def test_config_failure_never_stops_or_changes_active_files(self):
        original = self.docker
        def fail(args, timeout=120):
            if args[1] == "run":
                raise d.Stop("Synthetic config failure")
            return original(args, timeout)
        self.args.apply = True
        self.args.authorize_runtime_check = True
        with patch.object(d, "command", side_effect=fail), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertEqual(self.tree(), self.originals)
        self.assertTrue(self.running)

    def test_install_stop_failure_does_not_restart_or_change_files(self):
        self.args.apply = True
        self.args.authorize_runtime_check = True
        original = self.docker
        def fail_stop(args, timeout=120):
            if args[1] == "stop":
                raise d.Stop("Synthetic stop failure")
            return original(args, timeout)
        with patch.object(d, "command", side_effect=fail_stop), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), self.originals)
        self.assertEqual(sum(call[1] == "start" for call in self.calls), 0)

    def test_snapshot_failure_restarts_home_assistant_without_active_changes(self):
        self.args.apply = True
        self.args.authorize_runtime_check = True
        with patch.object(d, "create_snapshot", side_effect=OSError("synthetic snapshot failure")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                d.install(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), self.originals)
        self.assertEqual(sum(call[1] == "stop" for call in self.calls), 1)
        self.assertEqual(sum(call[1] == "start" for call in self.calls), 1)

    def test_drift_blocks_rollback_before_stop(self):
        self.install()
        self.write("configuration.yaml", b"unrelated operator edit")
        self.calls.clear()
        with self.assertRaises(d.Stop):
            d.rollback(self.args)
        self.assertFalse(any(a[1] == "stop" for a in self.calls))

    def test_rollback_dry_run_is_read_only(self):
        self.install()
        self.args.apply = False
        before = self.tree()
        self.calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.calls, [])

    def test_stopped_partial_install_can_be_rolled_back(self):
        self.install()
        self.running = False
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        self.assertFalse(self.running)
        self.assertEqual((self.config / "configuration.yaml").read_bytes(), self.original_config)

    def test_unsafe_path_or_hash_or_missing_backup_stops_before_writes(self):
        for kind in ("source", "backup", "symlink"):
            with self.subTest(kind=kind):
                if kind == "source":
                    path = self.config / (d.PREFIX + "const.py")
                    original = path.read_bytes()
                    path.write_bytes(b"unexpected source")
                elif kind == "backup":
                    self.args.backup = self.base / "missing.tar.gz"
                else:
                    path = self.config / "symlink"
                    path.symlink_to(self.config / ".HA_VERSION")
                with self.assertRaises(d.Stop):
                    d.install(self.args)
                if kind == "source":
                    path.write_bytes(original)
                elif kind == "backup":
                    self.args.backup = self.backup
                else:
                    path.unlink()
        self.assertFalse(self.args.restore_root.exists())

    def test_unreadable_backup_stops_with_safe_actionable_message(self):
        with patch.object(d.tarfile, "open", side_effect=PermissionError("private path details")):
            with self.assertRaisesRegex(d.Stop, "^Confirmed backup is unreadable; backup validation failed\\.$") as caught:
                d.backup_check(self.backup, self.config)
        self.assertNotIn("private path details", str(caught.exception))

    def test_backup_manifest_detects_missing_and_changed_files_without_disclosure(self):
        secret = self.config / ".storage" / "auth"
        self.write(".storage/auth", b"private-one")
        backed_up_config = self.original_config + b"# private-one\n"
        (self.config / "configuration.yaml").write_bytes(backed_up_config)
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        (self.config / "configuration.yaml").write_bytes(backed_up_config.replace(b"private-one", b"private-two"))
        with self.assertRaisesRegex(d.Stop, "deployment-critical") as caught:
            d.backup_check(self.backup, self.config)
        self.assertNotIn("private-one", str(caught.exception))
        self.assertNotIn("private-two", str(caught.exception))
        (self.config / "configuration.yaml").write_bytes(backed_up_config)
        secret.unlink()
        with self.assertRaisesRegex(d.Stop, "does not cover"):
            d.backup_check(self.backup, self.config)

    def test_brand_integration_cache_differences_are_ignored_but_snapshot_keeps_them(self):
        cached = self.config / ".cache/brands/integrations/example/icon.png"
        self.write(".cache/brands/integrations/example/icon.png", b"old rebuildable image")
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        cached.write_bytes(b"new rebuildable image")
        self.write(".cache/brands/integrations/new_brand/logo.png", b"new cache entry")
        point = self.install()
        snapshot = d.archive_manifest(point / "configuration.tar.gz")
        self.assertEqual(snapshot[".cache/brands/integrations/example/icon.png"]["sha256"],
                         d.digest(b"new rebuildable image"))
        self.assertEqual(snapshot[".cache/brands/integrations/new_brand/logo.png"]["sha256"],
                         d.digest(b"new cache entry"))
        evidence = json.loads((point / "manifest.json").read_bytes())
        self.assertEqual(evidence["snapshot"]["manifest_sha256"], d.manifest_digest(snapshot))

    def test_cache_exception_does_not_exclude_storage_databases_or_other_caches(self):
        for relative in (".storage/new_runtime_state", "other-database.db",
                         ".cache/brands/hardware/example/icon.png", ".cache/other/value"):
            with self.subTest(relative=relative):
                path = self.config / relative
                self.write(relative, b"must remain covered")
                with self.assertRaisesRegex(d.Stop, "does not cover"):
                    d.backup_check(self.backup, self.config)
                path.unlink()
        cache_root = self.config / ".cache/brands/integrations"
        cache_root.mkdir(parents=True)
        with self.assertRaisesRegex(d.Stop, "does not cover"):
            d.backup_check(self.backup, self.config)

    def test_live_recorder_sidecars_are_allowed_and_preserved_in_stopped_snapshot(self):
        self.write("home-assistant_v2.db-wal", b"committed recorder WAL frames")
        self.write("home-assistant_v2.db-shm", b"rebuildable WAL index")
        self.write("home-assistant.log.fault", b"")
        (self.config / "home-assistant_v2.db").write_bytes(b"newer recorder main database")
        before = self.tree()
        with contextlib.redirect_stdout(io.StringIO()):
            d.install(self.args)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.restore_root.exists())
        original_snapshot = d.create_snapshot
        stopped_manifest = {}

        def stopped_snapshot(*args):
            self.assertFalse(self.running)
            stopped_manifest.update(d.filesystem_manifest(self.config))
            return original_snapshot(*args)

        with patch.object(d, "create_snapshot", side_effect=stopped_snapshot):
            point = self.install()
        snapshot = d.archive_manifest(point / "configuration.tar.gz")
        self.assertEqual(snapshot, stopped_manifest)
        for relative in ("home-assistant_v2.db", "home-assistant_v2.db-wal",
                         "home-assistant_v2.db-shm", "home-assistant.log.fault"):
            self.assertIn(relative, snapshot)
            self.assertEqual(snapshot[relative]["sha256"], d.file_digest(self.config / relative))

    def test_runtime_exception_is_exact_and_never_hides_faults_or_main_database_loss(self):
        for relative, data in (("home-assistant_v2.db-journal", b"journal"),
                               ("other.db-wal", b"wal"),
                               ("runtime/home-assistant_v2.db-shm", b"shm"),
                               ("home-assistant.log.fault", b"fatal Python error")):
            with self.subTest(relative=relative):
                path = self.config / relative
                self.write(relative, data)
                expected = "fault log" if relative == "home-assistant.log.fault" else "does not cover"
                with self.assertRaisesRegex(d.Stop, expected):
                    d.backup_check(self.backup, self.config)
                path.unlink()
                if path.parent != self.config:
                    path.parent.rmdir()
        shm = self.config / "home-assistant_v2.db-shm"
        self.write("home-assistant_v2.db-shm", b"orphaned shm")
        with self.assertRaisesRegex(d.Stop, "without its WAL"):
            d.backup_check(self.backup, self.config)
        shm.unlink()
        database = self.config / "home-assistant_v2.db"
        database_data = database.read_bytes()
        database.unlink()
        with self.assertRaisesRegex(d.Stop, "main database"):
            d.backup_check(self.backup, self.config)
        database.write_bytes(database_data)
        self.write("home-assistant_v2.db-wal", b"backup must be self-contained")
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        with self.assertRaisesRegex(d.Stop, "Stopped backup unexpectedly contains"):
            d.backup_check(self.backup, self.config)

    def test_runtime_exception_requires_nonempty_main_database_in_both_manifests(self):
        database = self.config / d.RECORDER_DATABASE
        original = database.read_bytes()
        for location in ("backup", "current"):
            for data in (None, b""):
                with self.subTest(location=location, data=data):
                    database.write_bytes(original)
                    if location == "current":
                        with tarfile.open(self.backup, "w:gz") as archive:
                            archive.add(self.config, arcname="config")
                    if data is None:
                        database.unlink()
                    else:
                        database.write_bytes(data)
                    if location == "backup":
                        with tarfile.open(self.backup, "w:gz") as archive:
                            archive.add(self.config, arcname="config")
                        database.write_bytes(original)
                    with self.assertRaisesRegex(d.Stop, "main database"):
                        d.backup_check(self.backup, self.config)

    def test_runtime_paths_must_be_regular_files_and_absent_from_stopped_backup(self):
        for name in sorted(d.CURRENT_RUNTIME_FILES):
            for kind in ("directory", "symlink"):
                with self.subTest(name=name, kind=kind):
                    path = self.config / name
                    if kind == "directory":
                        path.mkdir()
                    else:
                        path.symlink_to(self.config / d.RECORDER_DATABASE)
                    with self.assertRaises(d.Stop):
                        d.backup_check(self.backup, self.config)
                    path.rmdir() if kind == "directory" else path.unlink()
        for name in sorted(d.RECORDER_SIDECARS):
            with self.subTest(backup_sidecar=name):
                self.write(name, b"sidecar")
                with tarfile.open(self.backup, "w:gz") as archive:
                    archive.add(self.config, arcname="config")
                with self.assertRaisesRegex(d.Stop, "Stopped backup unexpectedly contains"):
                    d.backup_check(self.backup, self.config)
                (self.config / name).unlink()

    def test_runtime_allowance_preserves_deployment_critical_content_checks(self):
        self.write(d.RECORDER_DATABASE + "-wal", b"live WAL")
        self.write(d.RECORDER_DATABASE + "-shm", b"live SHM")
        for name in ("configuration.yaml", ".storage/core.config_entries", d.PREFIX + "const.py"):
            with self.subTest(name=name):
                path = self.config / name
                original = path.read_bytes()
                path.write_bytes(original + b"drift")
                with self.assertRaisesRegex(d.Stop, "deployment-critical"):
                    d.backup_check(self.backup, self.config)
                path.write_bytes(original)

    def test_stopped_snapshot_recovers_real_uncheckpointed_sqlite_commit(self):
        database = self.config / d.RECORDER_DATABASE
        database.unlink()
        with contextlib.closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE observations (value TEXT)")
            connection.commit()
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        subprocess.run([sys.executable, "-c", """
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
connection.execute('INSERT INTO observations VALUES (?)', ('committed',))
connection.commit()
os._exit(0)  # Leave committed WAL frames, with no writer or close-time checkpoint.
""", str(database)], check=True, timeout=30)
        self.assertGreater((self.config / (d.RECORDER_DATABASE + "-wal")).stat().st_size, 0)
        main_only = self.base / "main-only.db"
        main_only.write_bytes(database.read_bytes())
        with contextlib.closing(sqlite3.connect(main_only)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM observations").fetchall(), [])
        point = self.install()
        restored = self.base / "restored"
        restored.mkdir()
        with tarfile.open(point / "configuration.tar.gz") as archive:
            for name in (d.RECORDER_DATABASE, *sorted(d.RECORDER_SIDECARS)):
                with archive.extractfile("config/" + name) as stream:
                    (restored / name).write_bytes(stream.read())
        with contextlib.closing(sqlite3.connect(restored / d.RECORDER_DATABASE)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM observations").fetchall(), [("committed",)])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))

    def test_clean_shutdown_checkpoints_database_before_snapshot(self):
        database = self.config / d.RECORDER_DATABASE
        database.unlink()
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE observations (value TEXT)")
        connection.commit()
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO observations VALUES ('checkpointed')")
        connection.commit()
        self.assertTrue((self.config / (d.RECORDER_DATABASE + "-wal")).exists())
        original_docker = self.docker

        def clean_stop(args, timeout=120):
            result = original_docker(args, timeout)
            if args[1] == "stop":
                connection.close()
            return result

        with patch.object(d, "command", side_effect=clean_stop):
            point = self.install()
        snapshot = d.archive_manifest(point / "configuration.tar.gz")
        self.assertTrue(d.RECORDER_SIDECARS.isdisjoint(snapshot))
        self.assertEqual(snapshot[d.RECORDER_DATABASE]["sha256"], d.file_digest(database))
        with contextlib.closing(sqlite3.connect(database)) as restored:
            self.assertEqual(restored.execute("SELECT * FROM observations").fetchall(), [("checkpointed",)])

    def test_snapshot_wal_mismatch_restarts_without_active_changes(self):
        self.write(d.RECORDER_DATABASE + "-wal", b"committed WAL")
        before = self.tree()
        original_manifest = d.archive_manifest

        def missing_wal(path):
            manifest = original_manifest(path)
            if path.name == "configuration.tar.gz":
                self.assertFalse(self.running)
                del manifest[d.RECORDER_DATABASE + "-wal"]
            return manifest

        with patch.object(d, "archive_manifest", side_effect=missing_wal):
            with self.assertRaisesRegex(d.Stop, "Stopped configuration changed"):
                self.install()
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), before)
        self.assertEqual(sum(call[1] == "start" for call in self.calls), 1)

    def test_health_failure_restores_files_and_restarts_container(self):
        self.args.apply = True
        self.args.authorize_runtime_check = True
        with patch.object(d, "health", side_effect=d.Stop("Synthetic unhealthy audit")), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), self.originals)
        self.assertEqual(sum(a[1] == "start" for a in self.calls), 2)
        self.assertFalse((self.config / (d.PREFIX + "stalman_audit.py")).exists())
        point = next(p for p in self.args.restore_root.iterdir() if p.is_dir())
        self.assertEqual(json.loads((point / "manifest.json").read_bytes())["phase"], "recovered")

    def test_install_write_failure_restores_files_and_restarts_container(self):
        self.args.apply = True
        self.args.authorize_runtime_check = True
        original = d.atomic
        failed = False
        def failure(path, data, info, directory_info=None):
            nonlocal failed
            if path == self.config / "energy_finance/compare.py" and not failed:
                failed = True
                raise OSError("synthetic disk failure")
            return original(path, data, info, directory_info)
        with patch.object(d, "atomic", side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                d.install(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), self.originals)

    def test_rollback_write_failure_restores_installed_files_and_restarts(self):
        self.install()
        installed = self.tree()
        original = d.atomic
        failed = False
        def failure(path, data, info, directory_info=None):
            nonlocal failed
            if path == self.config / "configuration.yaml" and not failed:
                failed = True
                raise OSError("synthetic rollback disk failure")
            return original(path, data, info, directory_info)
        with patch.object(d, "atomic", side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                d.rollback(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), installed)
        self.assertEqual(json.loads((self.args.restore_point / "manifest.json").read_bytes())["phase"], "validated")

    def test_rollback_config_failure_keeps_container_and_files(self):
        self.install()
        installed = self.tree()
        original = self.docker
        def fail_check(args, timeout=120):
            if args[1] == "run":
                raise d.Stop("Synthetic rollback config failure")
            return original(args, timeout)
        self.calls.clear()
        with patch.object(d, "command", side_effect=fail_check), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.rollback(self.args)
        self.assertTrue(self.running)
        self.assertEqual(self.tree(), installed)
        self.assertFalse(any(call[1] == "stop" for call in self.calls))

    def test_apply_writeability_probe_uses_real_filesystem_operation(self):
        with patch.object(d.tempfile, "mkstemp", side_effect=PermissionError("synthetic denied")):
            with self.assertRaises(PermissionError):
                d.verify_writable(self.config / "configuration.yaml")
        self.assertEqual(self.tree(), self.originals)

    def test_changed_battery_or_existing_finance_path_is_rejected(self):
        changed = copy.deepcopy(self.entry)
        changed["data"]["size_kwh"] = 99
        self.write(".storage/core.config_entries", json.dumps({"data": {"entries": [changed]}}).encode())
        with self.assertRaises(d.Stop):
            d.install(self.args)
        self.write(".storage/core.config_entries", self.originals[".storage/core.config_entries"][0])
        self.write("energy_finance/observations.json", b"{}")
        with self.assertRaises(d.Stop):
            d.install(self.args)
        self.assertFalse(self.args.restore_root.exists())

    def test_corrupt_restore_snapshot_is_rejected(self):
        point = self.install()
        (point / "configuration.tar.gz").write_bytes(b"damaged")
        self.calls.clear()
        with self.assertRaises(d.Stop):
            d.rollback(self.args)
        self.assertFalse(any(a[1] == "stop" for a in self.calls))

    def test_backup_missing_member_or_unsafe_link_is_rejected(self):
        for linked in (False, True):
            with tarfile.open(self.backup, "w:gz") as archive:
                if linked:
                    member = tarfile.TarInfo("config/link")
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/etc/passwd"
                    archive.addfile(member)
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertFalse(self.args.restore_root.exists())

    def test_duplicate_package_include_is_rejected(self):
        self.write("configuration.yaml", self.original_config.replace(
            b"lovelace:", b"    stalman_audit: !include packages/other.yaml\nlovelace:"))
        with self.assertRaises(d.Stop):
            d.install(self.args)
        self.assertFalse(self.args.restore_root.exists())

    def test_wrong_image_or_mount_stops_before_mutation(self):
        for response in (b'true\n"wrong-image"\n[]', ("true\n" + json.dumps(d.IMAGE) + "\n[]").encode()):
            with self.subTest(response=response), patch.object(d, "command", return_value=response):
                with self.assertRaises(d.Stop):
                    d.runtime_check(self.args, require_running=True)
        self.assertEqual(self.tree(), self.originals)

    def test_insufficient_space_or_permissions_stops_before_mutation(self):
        with patch.object(d.shutil, "disk_usage", return_value=type("Space", (), {"free": 0})()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        with patch.object(d.os, "access", return_value=False):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertEqual(self.tree(), self.originals)


if __name__ == "__main__":
    unittest.main()
