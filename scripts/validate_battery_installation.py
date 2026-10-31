"""Local-only HA config-entry, YAML transport, restart and rollback acceptance test."""
import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import MappingProxyType
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_battery_runtime_parity import SOURCE_FILES, load_prepare_patch

ENTRY = "isolated-marstek-installation"
BASE = datetime(2027, 1, 2, 8, tzinfo=timezone.utc)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def install(root, source, audited):
    destination = root / "custom_components/battery_sim"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source.parent, destination, ignore=shutil.ignore_patterns("__pycache__"))
    if audited:
        (destination / "__init__.py").write_text(load_prepare_patch().transform(source.read_bytes()))
        shutil.copyfile(ROOT / "proposals/battery_sim_audit/stalman_audit.py", destination / "stalman_audit.py")
    finance = root / "energy_finance"
    finance.mkdir(exist_ok=True)
    for name in ("collector.py", "batch_contract.py", "compare.py", "collector.json", "tariffs.json"):
        shutil.copyfile(ROOT / "config/energy_finance" / name, finance / name)
    policy = json.loads((finance / "collector.json").read_text())
    policy["audit"].update(enabled=audited, battery_id=ENTRY)
    (finance / "collector.json").write_text(json.dumps(policy))
    packages = {}
    if audited:
        for name in ("energie_thuisbatterij", "energie_intervalcollector", "energie_audit_adapter"):
            text = (ROOT / "config/packages" / f"{name}.yaml").read_text()
            packages[name] = yaml.safe_load(text.replace("/config/", f"{root}/"))
    config = {"homeassistant": {"name": "Isolated local installation", "time_zone": "Europe/Amsterdam",
                              "latitude": 0, "longitude": 0, "elevation": 0,
                              "unit_system": "metric", "packages": packages}}
    (root / "configuration.yaml").write_text(yaml.safe_dump(config))


async def stage(root, audited):
    from homeassistant import bootstrap, config as ha_config, loader
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant
    from homeassistant.const import __version__

    check(__version__ == "2026.10.4", "Requires Home Assistant 2026.10.4")
    from homeassistant.util import dt as dt_util

    checkpoint = root / "test_run.json"
    run_index = json.loads(checkpoint.read_text()) if checkpoint.exists() else 0
    checkpoint.write_text(json.dumps(run_index + 1))
    base = BASE + timedelta(minutes=10 * run_index)
    now = base
    hass = HomeAssistant(str(root))
    loader.async_setup(hass)
    config = json.loads((root / "energy_finance/collector.json").read_text())
    entities = config["entities"]
    data = {
        "name": "Marstek Venus E 5.12kWh 3nd gen", "size_kwh": 5.12,
        "max_charge_rate_kw": 2.5, "max_discharge_rate_kw": 0.8,
        "charge_efficiency": 0.91, "discharge_efficiency": 0.91,
        "update_frequency": 60,
        "input_list": [{"sensor_id": entities[f"real_{role}"], "sensor_type": role.title(),
                        "simulated_sensor": f"simulated_sensor.p1_meter_energie_{role}",
                        "tariff_type": "No tariff information"} for role in ("import", "export")],
    }
    received = []
    hass.bus.async_listen("battery_sim_stalman_audit_batch", lambda event: received.append(copy.deepcopy(event.data)))
    import_start, export_start = 100 + run_index * .5, 20 + run_index * .25
    initial = {"real_import": import_start, "real_export": export_start, "real_import_1": import_start,
               "real_import_2": 0, "real_export_1": export_start, "real_export_2": 0, "tariff": "1"}
    with (patch.object(dt_util, "utcnow", side_effect=lambda: now),
          patch.object(dt_util, "now", side_effect=lambda zone=None: now.astimezone(zone or dt_util.DEFAULT_TIME_ZONE))):
        try:
            for role, value in initial.items():
                hass.states.async_set(entities[role], str(value),
                                      {} if role == "tariff" else {"unit_of_measurement": "kWh"},
                                      timestamp=now.timestamp())
            loaded = await bootstrap.async_from_config_dict(await ha_config.async_hass_config_yaml(hass), hass)
            check(loaded is hass, "HA configuration bootstrap failed")
            entries = hass.config_entries.async_entries("battery_sim")
            if not entries:
                entry = ConfigEntry(version=1, minor_version=1, domain="battery_sim", title=data["name"],
                                    data=data, options={}, source="user", unique_id=ENTRY, entry_id=ENTRY,
                                    discovery_keys=MappingProxyType({}), subentries_data=None)
                await hass.config_entries.async_add(entry)
            else:
                entry = entries[0]
            if entry.state != ConfigEntryState.LOADED:
                check(await hass.config_entries.async_setup(entry.entry_id), "Battery config-entry setup failed")
            await hass.async_start()
            await hass.async_block_till_done()
            handle = hass.data["battery_sim"][entry.entry_id]
            check(entry.state == ConfigEntryState.LOADED, "Config entry not loaded")
            check(any(s.entity_id.startswith("sensor.") and "battery" in s.entity_id for s in hass.states.async_all()),
                  "No simulator platform sensors loaded")
            check(bool(getattr(handle, "_stalman_audit", None)) == audited, "Unexpected audit load state")
            check(hass.config_entries.async_get_entry(entry.entry_id).data == data, "Battery configuration changed")
            for key, value in {"_battery_size": 5.12, "_max_charge_rate": 2.5,
                               "_max_discharge_rate": .8, "_battery_charge_efficiency": .91,
                               "_battery_discharge_efficiency": .91, "_update_frequency": 60}.items():
                check(getattr(handle, key) == value, f"Marstek parameter not applied: {key}")
            initial_charge = handle._charge_state

            async def settle():
                await hass.async_block_till_done()

            async def process(seconds):
                nonlocal now
                now = base + timedelta(seconds=seconds)
                handle.async_periodic_update(now)
                await settle()

            for seconds, role, value in ((10, "import", import_start + .25), (20, "export", export_start + .125),
                                         (30, "import", import_start + .5), (40, "export", export_start + .25)):
                now = base + timedelta(seconds=seconds)
                for key in (f"real_{role}", f"real_{role}_1"):
                    hass.states.async_set(entities[key], str(value), {"unit_of_measurement": "kWh"},
                                          timestamp=now.timestamp())
                await settle()
            await process(60)
            snapshot = {key: copy.deepcopy(getattr(handle, key)) for key in (
                "_sensors", "_charge_state", "_accumulated_import_reading", "_accumulated_export_reading",
                "_stored_energy_value")}
            if audited:
                check(len(received) == 1 and received[0]["sequence"] == 1, "First startup batch lost")
                check(received[0]["valid"], "Startup audit batch invalid")
                db = root / "energy_finance/intervals.sqlite"
                check(db.exists(), "YAML adapter did not reach SQLite")
                with sqlite3.connect(db) as conn:
                    count = conn.execute("SELECT COUNT(*) FROM audit_packets_v1 WHERE generation=?",
                                         (received[0]["generation"],)).fetchone()[0]
                check(count == 1, "Expected one durable startup packet")
                await hass.services.async_call(
                    "automation", "trigger",
                    {"entity_id": "automation.stalman_financiele_meetintervallen",
                     "variables": {"trigger": {"id": "sample"}}}, blocking=True)
                await settle()
                with sqlite3.connect(db) as conn:
                    for source in ("measured_p1", "simulated_marstek"):
                        row = conn.execute(
                            "SELECT state, reason FROM source_observations_v2 WHERE source=? ORDER BY ts DESC LIMIT 1",
                            (source,)).fetchone()
                        check(row is not None and row[0] is not None,
                              f"Native snapshot source unavailable: {source}: {row}")
                observation_path = root / "energy_finance/observations.json"
                observation = json.loads(observation_path.read_text())
                check(observation.get("coverage_confirmed") is True, f"Transport not certified: {observation}")
                check(Decimal(observation["without"]["import_kwh"]["offpeak"]) == Decimal(".5"), "P1 delta mismatch")
                await hass.services.async_call("homeassistant", "update_entity",
                                               {"entity_id": "sensor.stalman_financiele_vergelijking"}, blocking=True)
                await settle()
                state = hass.states.get("sensor.stalman_financiele_vergelijking")
                check(state is not None and state.state == "unavailable", "Unconfirmed contract released money")
                # Exercise successful pricing only with an explicitly synthetic local contract.
                tariff_path = root / "energy_finance/tariffs.json"
                actual_tariffs = tariff_path.read_text()
                synthetic = json.loads(actual_tariffs)
                plan = copy.deepcopy(synthetic["plans"][0])
                plan.update(id="synthetic-installation-test-only", valid_from="2027-01-01",
                            valid_until="2028-01-01", confirmed=True, validity_confirmed=True,
                            vat_basis_confirmed=True, cash_basis_confirmed=True,
                            export_credit_cash_per_kwh=".08", export_fee_cash_per_kwh=".06")
                synthetic["plans"] = [plan]
                tariff_path.write_text(json.dumps(synthetic))
                await hass.services.async_call("homeassistant", "update_entity",
                                               {"entity_id": "sensor.stalman_financiele_vergelijking"}, blocking=True)
                await settle()
                state = hass.states.get("sensor.stalman_financiele_vergelijking")
                check(state.state == "ok" and state.attributes["scope"] == "window", "Finance CLI did not price test window")
                def expected_cost(scenario):
                    quantities = observation[scenario]
                    return (Decimal(quantities["import_kwh"]["offpeak"]) * Decimal(".289284")
                            + Decimal(quantities["import_kwh"]["normal"]) * Decimal(".292551")
                            + Decimal(quantities["export_kwh"]) * (Decimal(".06") - Decimal(".08")))
                from decimal import ROUND_HALF_UP
                expected_saving = (expected_cost("without") - expected_cost("with")).quantize(
                    Decimal(".01"), rounding=ROUND_HALF_UP)
                check(Decimal(state.attributes["saving_eur"]) == expected_saving,
                      "Financial sensor does not match transported counter deltas")
                for entity in ("sensor.stalman_meetvenster_zonder", "sensor.stalman_meetvenster_met",
                               "sensor.stalman_meetvenster_verschil"):
                    check(hass.states.get(entity) is not None and
                          hass.states.get(entity).state not in ("unknown", "unavailable"),
                          f"Window template unavailable: {entity}")
                tariff_path.write_text(actual_tariffs)
                # Replay a burst through the actual queued automation, not the collector API.
                first = copy.deepcopy(received[0])
                for _ in range(8):
                    hass.bus.async_fire("battery_sim_stalman_audit_batch", first)
                await settle()
                with sqlite3.connect(db) as conn:
                    check(conn.execute("SELECT COUNT(*) FROM audit_packets_v1 WHERE generation=?",
                                       (first["generation"],)).fetchone()[0] == 1, "Duplicate packet counted twice")
                # Lose a real processing packet, then deliver it late through the same adapter.
                adapter = "automation.stalman_atomair_simulatiebewijs_ontvangen"
                check(hass.states.get(adapter) is not None, "Audit automation not registered")
                await hass.services.async_call("automation", "turn_off", {"entity_id": adapter}, blocking=True)
                await process(90)
                withheld = copy.deepcopy(received[-1])
                await hass.services.async_call("automation", "turn_on", {"entity_id": adapter}, blocking=True)
                await process(120)
                check(not json.loads(observation_path.read_text())["coverage_confirmed"], "Missing sequence was ignored")
                hass.bus.async_fire("battery_sim_stalman_audit_batch", withheld)
                await settle()
                check(json.loads(observation_path.read_text())["coverage_confirmed"], "Late packet failed to repair contiguous chain")
                # Stopping audit publication preserves only a labelled historical window.
                previous_end = json.loads(observation_path.read_text())["observed_until"]
                await hass.services.async_call("homeassistant", "update_entity",
                                               {"entity_id": "sensor.stalman_financiele_vergelijking"}, blocking=True)
                await settle()
                check(json.loads(observation_path.read_text())["observed_until"] == previous_end,
                      "No-event period invented new coverage")
                check(hass.states.get("sensor.stalman_batterijbesparing_vandaag").state == "unavailable",
                      "Historical window exposed as current daily saving")
                # Force a CLI failure; existing valid output must be invalidated.
                invalid = copy.deepcopy(received[-1])
                invalid["sequence"] = 0
                hass.bus.async_fire("battery_sim_stalman_audit_batch", invalid)
                await settle()
                check(not json.loads(observation_path.read_text())["coverage_confirmed"], "CLI failure left certified output")
                # Disable approval: continuing simulation must not authorize finance.
                policy_path = root / "energy_finance/collector.json"
                policy = json.loads(policy_path.read_text())
                policy["audit"]["enabled"] = False
                policy_path.write_text(json.dumps(policy))
                await process(180)
                check(not json.loads(observation_path.read_text())["coverage_confirmed"], "Disabled audit released data")
                policy["audit"]["enabled"] = True
                policy_path.write_text(json.dumps(policy))
            else:
                check(not received, "Audit still active after rollback")
            return {"snapshot": snapshot, "entry_id": entry.entry_id,
                    "initial_charge": initial_charge, "final_charge": handle._charge_state,
                    "generation": received[0]["generation"] if received else None}
        finally:
            await hass.async_stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--audited", action="store_true")
    args = parser.parse_args()
    if args.stage:
        result = asyncio.run(stage(args.stage, args.audited))
        (args.stage / "result.json").write_text(json.dumps(result, default=str))
        return
    check(args.source is not None, "--source is required")
    pinned = {**SOURCE_FILES, "sensor.py": "c6a137075d962c43fc88246ba078b81ce98269dbe2f7ae0379ba0cddad129724"}
    for name, expected in pinned.items():
        check(hashlib.sha256((args.source.parent / name).read_bytes()).hexdigest() == expected,
              f"Unpinned source: {name}")
    with tempfile.TemporaryDirectory(prefix="battery-installation-") as temp:
        root = Path(temp)
        baseline, audited = root / "baseline", root / "audited"
        baseline.mkdir()
        audited.mkdir()
        def run(path, enabled):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--stage", str(path),
                                     *(["--audited"] if enabled else [])], capture_output=True, text=True, timeout=150)
            if result.returncode:
                print(result.stdout[-3000:])
                print(result.stderr[-12000:])
                raise AssertionError(f"HA stage failed: {path.name}")
            return json.loads((path / "result.json").read_text())
        install(baseline, args.source, False)
        original = run(baseline, False)
        install(audited, args.source, True)
        instrumented = run(audited, True)
        check(original["snapshot"] == instrumented["snapshot"], "Audited model differs from original")
        reference = root / "restart-reference"
        shutil.copytree(audited, reference)
        install(reference, args.source, False)
        original_restart = run(reference, False)
        restarted = run(audited, True)
        check(restarted["generation"] != instrumented["generation"], "Restart reused audit generation")
        check(restarted["snapshot"] == original_restart["snapshot"], "Audit changed upstream restore behaviour")
        check(restarted["initial_charge"] == original_restart["initial_charge"], "Audit changed restored energy")
        check(restarted["initial_charge"] == round(instrumented["final_charge"], 3),
              "Restore differs from upstream three-decimal sensor precision")
        backup = root / "backup"
        shutil.copytree(audited, backup)
        with sqlite3.connect(f"file:{backup / 'energy_finance/intervals.sqlite'}?mode=ro", uri=True) as conn:
            check(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Backup SQLite is inconsistent")
        # Compare the same saved runtime state under original code in two independent restores.
        restored = root / "restored"
        shutil.copytree(backup, restored)
        for path in (audited, restored):
            install(path, args.source, False)
        rollback = run(audited, False)
        control = run(restored, False)
        check(rollback["snapshot"] == control["snapshot"], "Rollback does not reproduce restored original model")
        check(rollback["initial_charge"] == round(restarted["final_charge"], 3),
              "Rollback differs from upstream restored sensor precision")
        check(rollback["entry_id"] == original["entry_id"], "Rollback replaced battery binding")
        check(not (audited / "custom_components/battery_sim/stalman_audit.py").exists(), "Helper left after rollback")
        check((audited / "custom_components/battery_sim/__init__.py").read_bytes() == args.source.read_bytes(),
              "Rollback initializer is not byte-identical to original")
        print("PASS: HA config-entry/platform startup; Marstek parameters; YAML -> queued automation -> shell -> SQLite -> finance sensor; duplicate/disabled policy; restart; restored rollback.")


if __name__ == "__main__":
    main()
