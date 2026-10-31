"""Synthetic host files and mocked Docker only; never contacts a server or daemon."""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
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
        self.backup = self.base / "backup.tar.gz"
        with tarfile.open(self.backup, "w:gz") as archive:
            archive.add(self.config, arcname="config")
        self.args = argparse.Namespace(config=self.config, container="homeassistant", backup=self.backup,
                                       restore_root=self.base / "restore", restore_point=None,
                                       apply=False, health_timeout=30)
        self.running = True
        self.calls = []
        for mock in (patch.object(d, "SOURCE", hashes),
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
        self.assertFalse(any(a[1] in ("run", "stop", "start") for a in self.calls))

    def test_cli_defaults_to_dry_run_and_rollback_requires_explicit_point(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(["install", "--config", str(self.config), "--backup", str(self.backup),
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

    def test_config_failure_never_stops_or_changes_active_files(self):
        original = self.docker
        def fail(args, timeout=120):
            if args[1] == "run":
                raise d.Stop("Synthetic config failure")
            return original(args, timeout)
        self.args.apply = True
        with patch.object(d, "command", side_effect=fail), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertEqual(self.tree(), self.originals)
        self.assertTrue(self.running)

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
        self.assertFalse(any(a[1] in ("run", "stop", "start") for a in self.calls))

    def test_stopped_partial_install_can_be_rolled_back(self):
        self.install()
        self.running = False
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        self.assertTrue(self.running)
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

    def test_health_failure_requires_explicit_rollback(self):
        self.args.apply = True
        with patch.object(d, "health", side_effect=d.Stop("Synthetic unhealthy audit")), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(d.Stop):
                d.install(self.args)
        self.assertTrue(self.running)
        self.assertTrue((self.config / (d.PREFIX + "stalman_audit.py")).exists())
        self.assertEqual(sum(a[1] == "start" for a in self.calls), 1)
        self.args.restore_point = next(p for p in self.args.restore_root.iterdir() if p.is_dir())
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        self.assertFalse((self.config / (d.PREFIX + "stalman_audit.py")).exists())

    def test_partial_file_write_failure_can_be_explicitly_rolled_back(self):
        self.args.apply = True
        original = d.atomic
        def failure(path, data, info=None):
            if path == self.config / "energy_finance/compare.py":
                raise OSError("synthetic disk failure")
            return original(path, data, info)
        with patch.object(d, "atomic", side_effect=failure), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(OSError):
                d.install(self.args)
        self.assertFalse(self.running)
        self.args.restore_point = next(p for p in self.args.restore_root.iterdir() if p.is_dir())
        with contextlib.redirect_stdout(io.StringIO()):
            d.rollback(self.args)
        for name, (data, mode) in self.originals.items():
            self.assertEqual((self.config / name).read_bytes(), data)

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
                    d.install(self.args)
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
