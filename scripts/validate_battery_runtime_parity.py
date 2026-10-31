"""Run the pinned Battery Simulator and audit proposal inside Home Assistant Core."""
import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6"
SOURCE_FILES = {
    "__init__.py": SOURCE_SHA256,
    "const.py": "c84a30d515e842897364b6a96b4ca1144932f278e24f91bef8e0f59a64932dbc",
    "helpers.py": "8d5bd7d6772cf9093798a3c383c1c0ec68a8f6d1f2da6d8a30e5b19623019b9e",
}
BASE = datetime(2027, 1, 2, 8, 0, tzinfo=timezone.utc)
BATTERY_ID = "isolated-runtime-test"
ENTITY_CONFIG = json.loads((ROOT / "config/energy_finance/collector.json").read_text())
sys.path.insert(0, str(ROOT))


def load_prepare_patch():
    path = ROOT / "proposals/battery_sim_audit/prepare_patch.py"
    spec = importlib.util.spec_from_file_location("battery_sim_prepare_patch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the pinned audit transformer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_upstream_packages(source_path):
    # Home Assistant patches voluptuous during import; initialize it first.
    importlib.import_module("homeassistant")

    source_path = source_path.resolve()
    source_dir = source_path.parent
    for filename, expected in SOURCE_FILES.items():
        if hashlib.sha256((source_dir / filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Unsupported Battery Simulator source file: {filename}")
    source = source_path.read_bytes()

    prepare_patch = load_prepare_patch()
    patched_source = prepare_patch.transform(source)
    temp_root = tempfile.TemporaryDirectory(prefix="battery-sim-parity-")
    root = Path(temp_root.name)
    for package_name, initializer in (
        ("battery_sim_unmodified", source.decode()),
        ("battery_sim_audited", patched_source),
    ):
        package_dir = root / package_name
        package_dir.mkdir()
        for filename in ("const.py", "helpers.py"):
            copyfile(source_dir / filename, package_dir / filename)
        (package_dir / "__init__.py").write_text(initializer)
        if package_name == "battery_sim_audited":
            copyfile(
                ROOT / "proposals/battery_sim_audit/stalman_audit.py",
                package_dir / "stalman_audit.py",
            )

    sys.path.insert(0, str(root))
    try:
        return temp_root, (
            importlib.import_module("battery_sim_unmodified"),
            importlib.import_module("battery_sim_audited"),
        )
    except Exception:
        sys.path.remove(str(root))
        temp_root.cleanup()
        raise


class BatteryRuntimeParityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        source_path = Path(cls.source_path)
        cls.package_temp, cls.modules = load_upstream_packages(source_path)
        cls.config = ENTITY_CONFIG
        sys.path.insert(0, str(ROOT / "config/energy_finance"))
        from collector import Collector
        from compare import report

        cls.Collector = Collector
        cls.report = staticmethod(report)
        cls.tariffs = {
            "netting_ends": "2027-01-01",
            "plans": [
                {
                    "id": "synthetic-runtime-test",
                    "valid_from": "2027-01-01",
                    "valid_until": "2028-01-01",
                    "confirmed": True,
                    "cash_basis_confirmed": True,
                    "vat_fraction": ".21",
                    "delivery_discount_fraction": ".10",
                    "import": {
                        tariff: {
                            "quoted_total": ".363",
                            "quote_includes_vat": True,
                            "quote_includes_discount": False,
                            "delivery_ex_vat": ".20",
                            "energy_tax_ex_vat": ".10",
                        }
                        for tariff in ("normal", "offpeak")
                    },
                    "export_credit_cash_per_kwh": ".08",
                    "export_fee_cash_per_kwh": ".06",
                }
            ],
        }

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(ROOT / "config/energy_finance"))
        sys.path.remove(str(cls.package_temp.name))
        cls.package_temp.cleanup()

    def setUp(self):
        from homeassistant.util import dt as dt_util

        self.now = BASE
        self.clock_patch = patch.object(dt_util, "utcnow", side_effect=lambda: self.now)
        self.clock_patch.start()

    async def asyncTearDown(self):
        if getattr(self, "hass", None) is not None:
            await self.stop_runtime()
        self.clock_patch.stop()

    async def stop_runtime(self):
        for handle in getattr(self, "handles", []):
            for cancel in handle._listeners:
                cancel()
        if getattr(self, "hass", None) is not None:
            await self.hass.async_stop()
        if getattr(self, "runtime_temp", None) is not None:
            self.runtime_temp.cleanup()
        self.hass = None
        self.handles = []
        self.runtime_temp = None

    async def start_runtime(self):
        from homeassistant.const import CONF_NAME
        from homeassistant.core import HomeAssistant

        self.runtime_temp = tempfile.TemporaryDirectory(prefix="ha-battery-parity-")
        self.hass = HomeAssistant(self.runtime_temp.name)
        entities = self.config["entities"]
        initial = {
            "real_import": (100, "kWh"),
            "real_export": (20, "kWh"),
            "real_import_1": (100, "kWh"),
            "real_import_2": (0, "kWh"),
            "real_export_1": (20, "kWh"),
            "real_export_2": (0, "kWh"),
            "tariff": ("1", None),
        }
        for role, (value, unit) in initial.items():
            attributes = {"unit_of_measurement": unit} if unit else {}
            self.hass.states.async_set(
                entities[role],
                str(value),
                attributes,
                timestamp=self.now.timestamp(),
            )

        self.handles = []
        for module in self.modules:
            constants = importlib.import_module(f"{module.__name__}.const")
            inputs = [
                {
                    module.SENSOR_ID: entities["real_import"],
                    module.SENSOR_TYPE: module.IMPORT,
                    module.SIMULATED_SENSOR: constants.GRID_IMPORT_SIM,
                    module.TARIFF_TYPE: module.NO_TARIFF_INFO,
                },
                {
                    module.SENSOR_ID: entities["real_export"],
                    module.SENSOR_TYPE: module.EXPORT,
                    module.SIMULATED_SENSOR: constants.GRID_EXPORT_SIM,
                    module.TARIFF_TYPE: module.NO_TARIFF_INFO,
                },
            ]
            config = {
                CONF_NAME: "Isolated parity test",
                module.CONF_INPUT_LIST: inputs,
                module.CONF_BATTERY_SIZE: 5.0,
                module.CONF_BATTERY_MAX_CHARGE_RATE: 2.5,
                module.CONF_BATTERY_MAX_DISCHARGE_RATE: 2.5,
                module.CONF_BATTERY_EFFICIENCY: 0.91,
            }
            handle = module.SimulatedBatteryHandle(config, self.hass, BATTERY_ID)
            handle.async_source_tracking(None)
            self.handles.append(handle)

        self.packets = []
        from battery_sim_audited.stalman_audit import EVENT

        self.hass.bus.async_listen(
            EVENT, lambda event: self.packets.append(copy.deepcopy(event.data))
        )
        await self.hass.async_block_till_done()

    async def set_counter(self, role, value, tariff_register=None):
        entities = self.config["entities"]
        self.hass.states.async_set(
            entities[role],
            str(value),
            {"unit_of_measurement": "kWh"},
            timestamp=self.now.timestamp(),
        )
        if tariff_register is not None:
            register_role, code, register_value = tariff_register
            self.hass.states.async_set(
                entities[f"real_{register_role}_{code}"],
                str(register_value),
                {"unit_of_measurement": "kWh"},
                timestamp=self.now.timestamp(),
            )
        await self.hass.async_block_till_done()

    async def process(self, at):
        self.now = at
        for handle in self.handles:
            handle.async_periodic_update(at)
        await self.hass.async_block_till_done()

    def snapshots(self):
        keys = (
            "_charge_state",
            "_sensors",
            "_accumulated_import_reading",
            "_accumulated_export_reading",
            "_accumulated_solar_reading",
            "_last_battery_update_time",
            "_stored_energy_value",
            "_last_import_reading_sensor_data",
            "_last_export_reading_sensor_data",
        )
        return [{key: copy.deepcopy(getattr(handle, key)) for key in keys} for handle in self.handles]

    def financial_config(self):
        config = copy.deepcopy(self.config)
        from battery_sim_audited.stalman_audit import HELPER_SHA256

        config.update(
            mapping_confirmed=True,
            tariff_mapping={"1": "offpeak", "2": "normal"},
            audit={
                "enabled": True,
                "battery_id": BATTERY_ID,
                "expected_helper_sha256": HELPER_SHA256,
            },
        )
        return config

    def collect_and_report(self, batches):
        config = self.financial_config()
        with tempfile.TemporaryDirectory(prefix="ha-audit-collector-") as temp_dir:
            collector = self.Collector(Path(temp_dir) / "intervals.sqlite", config)
            try:
                for batch in batches:
                    collector.ingest_audit(batch)
                day = datetime.fromisoformat(batches[0]["processing_start"]).astimezone(
                    ZoneInfo("Europe/Amsterdam")
                ).date()
                observation = collector.observations(str(day))
                return observation, self.report(self.tariffs, observation)
            finally:
                collector.close()

    async def test_real_state_events_model_parity_tariff_windows_and_finance(self):
        await self.start_runtime()

        self.now = BASE + timedelta(seconds=1)
        await self.set_counter(
            "real_import", 101, ("import", "1", 101)
        )
        self.now = BASE + timedelta(seconds=2)
        await self.set_counter(
            "real_export", 20.5, ("export", "1", 20.5)
        )
        self.now = BASE + timedelta(seconds=3)
        await self.set_counter(
            "real_import", 102, ("import", "1", 102)
        )
        self.now = BASE + timedelta(seconds=4)
        await self.set_counter(
            "real_export", 21, ("export", "1", 21)
        )

        await self.process(BASE + timedelta(seconds=4))
        self.assertEqual(self.packets, [])
        self.assertEqual(self.snapshots()[0], self.snapshots()[1])
        await self.process(BASE + timedelta(seconds=60))
        self.assertEqual(self.snapshots()[0], self.snapshots()[1])
        first = self.packets[-1]
        self.assertTrue(first["valid"])
        self.assertEqual(len(first["accepted_events"]), 4)
        observed, result = self.collect_and_report([first])
        self.assertEqual(observed["without"]["import_kwh"]["offpeak"], "2")
        self.assertEqual(result["status"], "ok")

        entities = self.config["entities"]
        self.now = BASE + timedelta(seconds=70)
        self.hass.states.async_set(
            entities["tariff"], "2", timestamp=self.now.timestamp()
        )
        await self.hass.async_block_till_done()
        self.now = BASE + timedelta(seconds=80)
        await self.set_counter("real_import", 103, ("import", "2", 1))
        await self.process(BASE + timedelta(seconds=120))
        self.assertEqual(self.snapshots()[0], self.snapshots()[1])
        transition = self.packets[-1]
        self.assertTrue(transition["valid"])
        blocked_observation, blocked = self.collect_and_report([first, transition])
        self.assertFalse(blocked_observation["coverage_confirmed"])
        self.assertIsNone(blocked_observation["without"])
        self.assertEqual(blocked["status"], "unavailable")
        self.assertIsNone(blocked["saving_eur"])

        self.now = BASE + timedelta(seconds=130)
        await self.set_counter("real_import", 104, ("import", "2", 2))
        await self.process(BASE + timedelta(seconds=180))
        normal = self.packets[-1]
        self.assertTrue(normal["valid"])
        self.assertEqual(normal["sequence"], 1)
        self.assertNotEqual(normal["generation"], transition["generation"])
        observed, result = self.collect_and_report([normal])
        self.assertEqual(observed["without"]["import_kwh"]["normal"], "1")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self.snapshots()[0], self.snapshots()[1])

        generation_before_restart = normal["generation"]
        await self.stop_runtime()
        self.now = BASE + timedelta(seconds=240)
        await self.start_runtime()
        self.assertNotEqual(
            generation_before_restart,
            self.handles[1]._stalman_audit.generation,
        )

    async def test_unavailable_source_fails_closed_without_changing_model(self):
        await self.start_runtime()
        entities = self.config["entities"]
        self.now = BASE + timedelta(seconds=1)
        with self.assertLogs("battery_sim_audited.stalman_audit", level="ERROR"):
            self.hass.states.async_set(
                entities["real_import"],
                "unavailable",
                {"unit_of_measurement": "kWh"},
                timestamp=self.now.timestamp(),
            )
            await self.hass.async_block_till_done()
        with self.assertLogs("battery_sim_audited.stalman_audit", level="ERROR"):
            await self.process(BASE + timedelta(seconds=60))

        self.assertEqual(self.snapshots()[0], self.snapshots()[1])
        self.assertEqual(len(self.packets), 1)
        self.assertFalse(self.packets[0]["valid"])
        observation, result = self.collect_and_report([self.packets[0]])
        self.assertFalse(observation["coverage_confirmed"])
        self.assertIsNone(observation["with"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["saving_eur"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    if not (args.source.parent / "const.py").is_file() or not (
        args.source.parent / "helpers.py"
    ).is_file():
        parser.error("--source must be inside the complete pinned integration directory")
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != SOURCE_SHA256:
        parser.error("--source does not match the pinned Battery Simulator initializer")
    BatteryRuntimeParityTests.source_path = args.source
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BatteryRuntimeParityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("PASS: real Home Assistant state events, upstream model parity and finance handoff.")


if __name__ == "__main__":
    main()
