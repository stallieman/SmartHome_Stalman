"""Synthetic, source-aware regression tests; no network or production observations."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'config/energy_finance/collector.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location('finance', ROOT / 'config/energy_finance/compare.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class SourceCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'intervals.sqlite'
        self.config = json.loads((ROOT / 'config/energy_finance/collector.json').read_text())
        self.collector = c.Collector(self.path, self.config)
        self.time = datetime(2027, 1, 2, 8, 0, tzinfo=c.TZ)

    def tearDown(self):
        self.collector.close()
        self.tmp.cleanup()

    def sample(self, seconds=0):
        now = self.time + timedelta(seconds=seconds)
        last_sim = (seconds // 60) * 60 - 2
        real = c.Decimal('100') + c.Decimal(seconds // 10) * c.Decimal('.001')
        sim = c.Decimal('98') + c.Decimal(seconds // 60) * c.Decimal('.004')
        values = {'real_import': real, 'real_import_1': real, 'real_import_2': '0',
                  'real_export': '20', 'real_export_1': '20', 'real_export_2': '0',
                  'sim_import': sim, 'sim_export': '20', 'tariff': '1'}
        states = {}
        for role, value in values.items():
            at = now if role in ('real_import', 'real_import_1') else self.time + timedelta(seconds=last_sim) if role == 'sim_import' else self.time - timedelta(hours=9)
            states[self.config['entities'][role]] = {'state': str(value), 'unit': 'kWh',
                'last_reported': at.isoformat(), 'last_updated': at.isoformat(),
                'last_changed': at.isoformat(), 'last_reset': '2026-12-01T00:00:00+01:00', 'restored': False}
        return {'captured_at': now.isoformat(), 'session': 'boot-one', 'states': states}

    def change(self, sample, role, **values):
        sample['states'][self.config['entities'][role]].update(values)
        return sample

    def seed(self):
        return self.collector.ingest(self.sample())

    def last(self, source):
        status, reason, state, delta = self.collector.db.execute(
            'SELECT status,reason,state,change_data FROM source_observations_v2 WHERE source=? ORDER BY ts DESC LIMIT 1',
            (source,)).fetchone()
        return status, reason, json.loads(state) if state else None, json.loads(delta) if delta else None

    def test_old_unchanged_export_is_not_a_source_failure(self):
        self.seed()
        result = self.collector.ingest(self.sample(10))
        self.assertEqual(result['sources']['measured_p1']['status'], 'counter_changed')
        self.assertEqual(result['sources']['simulated_marstek']['status'], 'unchanged_observation')
        self.assertTrue(result['sources']['measured_p1']['recent_activity_observed'])
        self.assertIsNone(self.last('simulated_marstek')[3]['observed_counter_deltas'])

    def test_slow_simulator_and_fast_p1_have_independent_records(self):
        self.seed()
        for seconds in range(10, 71, 10):
            self.collector.ingest(self.sample(seconds))
        rows = self.collector.db.execute('SELECT source,status FROM source_observations_v2').fetchall()
        self.assertEqual(sum(s == 'measured_p1' and status == 'counter_changed' for s, status in rows), 7)
        self.assertEqual(sum(s == 'simulated_marstek' and status == 'counter_changed' for s, status in rows), 1)
        self.assertEqual(self.last('simulated_marstek')[0], 'unchanged_observation')

    def test_confirmed_mapping_is_attached_to_raw_tariff_code(self):
        self.seed()
        self.collector.ingest(self.sample(10))
        self.assertEqual(self.last('measured_p1')[3]['tariff_code'], '1')
        self.assertEqual(self.last('measured_p1')[3]['tariff_mapping'], {'1': 'offpeak', '2': 'normal'})

    def test_tariff_transition_2_to_1_keeps_confirmed_tariff_mapping(self):
        first = self.sample()
        first['states'][self.config['entities']['tariff']].update(
            state='2',
            last_reported=self.time.isoformat(),
            last_updated=self.time.isoformat(),
            last_changed=self.time.isoformat(),
        )
        self.collector.ingest(first)
        second = self.sample(10)
        second['states'][self.config['entities']['tariff']].update(
            state='1',
            last_reported=(self.time + timedelta(seconds=10)).isoformat(),
            last_updated=(self.time + timedelta(seconds=10)).isoformat(),
            last_changed=(self.time + timedelta(seconds=10)).isoformat(),
        )
        result = self.collector.ingest(second)
        self.assertEqual(result['sources']['measured_p1']['status'], 'counter_changed')
        measured = self.last('measured_p1')[3]
        self.assertEqual(measured['tariff_code'], '1')
        self.assertEqual(measured['tariff_mapping'], {'1': 'offpeak', '2': 'normal'})

    def test_manual_pairing_flag_cannot_enable_finance(self):
        self.config['pairing_confirmed'] = True
        self.seed()
        self.collector.ingest(self.sample(10))
        export = self.collector.observations('2027-01-02')
        self.assertFalse(export['coverage_confirmed'])
        self.assertFalse(export['paired_grid_deltas_confirmed'])
        self.assertIsNone(export['with'])
        cfg = json.loads((ROOT / 'config/energy_finance/tariffs.json').read_text())
        self.assertIsNone(f.report(cfg, export)['saving_eur'])

    def test_equal_timestamps_are_not_processing_evidence(self):
        self.seed()
        sample = self.sample(10)
        for state in sample['states'].values():
            state['last_reported'] = sample['captured_at']
            state['last_updated'] = sample['captured_at']
        self.collector.ingest(sample)
        self.assertFalse(self.collector.observations('2027-01-02')['paired_grid_deltas_confirmed'])

    def test_all_stable_counters_are_unverified_not_confirmed_zero(self):
        first = self.sample()
        self.collector.ingest(first)
        later = copy.deepcopy(first)
        later['captured_at'] = (self.time + timedelta(seconds=10)).isoformat()
        result = self.collector.ingest(later)
        for source in c.GROUPS:
            self.assertEqual(result['sources'][source]['status'], 'unchanged_observation')
            self.assertIsNone(self.last(source)[3]['observed_counter_deltas'])
            self.assertFalse(self.last(source)[3]['certified_processed_window'])

    def test_inactive_tariff_code_does_not_need_heartbeat(self):
        self.seed()
        self.collector.ingest(self.sample(10))
        self.assertIsNone(self.last('measured_p1')[1])

    def test_old_activity_is_diagnostic_not_missing_data(self):
        self.seed()
        for seconds in range(10, 161, 10):
            sample = self.sample(seconds)
            self.change(sample, 'sim_import', state='98', last_reported=(self.time-timedelta(seconds=2)).isoformat(),
                        last_updated=(self.time-timedelta(seconds=2)).isoformat())
            result = self.collector.ingest(sample)
        self.assertEqual(result['sources']['simulated_marstek']['status'], 'unchanged_observation')
        self.assertFalse(result['sources']['simulated_marstek']['recent_activity_observed'])

    def test_unavailable_p1_does_not_drop_simulator_data(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'real_import', state='unavailable'))
        self.assertEqual(self.last('measured_p1')[0], 'unavailable')
        self.assertEqual(self.last('simulated_marstek')[0], 'unchanged_observation')
        self.collector.ingest(self.sample(20))
        self.assertEqual(self.last('measured_p1')[1], 'baseline_after_missing_source')
        self.assertIsNone(self.last('measured_p1')[3])

    def test_missing_simulator_does_not_drop_p1(self):
        self.seed()
        sample = self.sample(10)
        del sample['states'][self.config['entities']['sim_export']]
        self.collector.ingest(sample)
        self.assertEqual(self.last('simulated_marstek')[0], 'unavailable')
        self.assertEqual(self.last('measured_p1')[0], 'counter_changed')
        self.assertIsNone(self.last('simulated_marstek')[2])

    def test_simulator_reset_does_not_reset_real_baseline(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'sim_import', state='0'))
        self.assertEqual(self.last('simulated_marstek')[1], 'counter_reset_or_decrease')
        self.assertEqual(self.last('measured_p1')[0], 'counter_changed')

    def test_reset_metadata_starts_new_source_baseline(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'sim_import', last_reset='2027-01-02T08:00:01+01:00'))
        self.assertEqual(self.last('simulated_marstek')[1], 'reset_metadata_changed')
        self.assertIsNone(self.last('simulated_marstek')[3])

    def test_missing_observation_interval(self):
        self.seed()
        result = self.collector.ingest(self.sample(20))
        for source in c.GROUPS:
            self.assertEqual(result['sources'][source]['reason'], 'missing_observation_interval')
            self.assertIsNone(self.last(source)[3])

    def test_process_restart_keeps_baselines(self):
        self.seed()
        self.collector.close()
        self.collector = c.Collector(self.path, self.config)
        self.collector.ingest(self.sample(10))
        self.assertEqual(self.last('measured_p1')[3]['observed_counter_deltas']['real_import'], '0.001')

    def test_ha_restart_breaks_both_source_windows(self):
        self.seed()
        sample = self.sample(10)
        sample['session'] = 'new-boot'
        result = self.collector.ingest(sample)
        self.assertTrue(all(s['reason'] == 'ha_restart' for s in result['sources'].values()))

    def test_duplicate_is_idempotent(self):
        self.seed()
        sample = self.sample(10)
        self.collector.ingest(sample)
        self.assertEqual(self.collector.ingest(sample)['status'], 'duplicate')
        self.assertEqual(self.collector.db.execute('SELECT COUNT(*) FROM snapshots_v2').fetchone()[0], 2)

    def test_conflicting_duplicate_is_durable_fault(self):
        self.seed()
        altered = self.sample()
        altered['session'] = 'different'
        with self.assertRaises(c.InvalidSample):
            self.collector.ingest(altered)
        self.assertEqual(self.collector.db.execute('SELECT COUNT(*) FROM faults_v2').fetchone()[0], 1)

    def test_out_of_order_rejected(self):
        self.seed()
        with self.assertRaises(c.InvalidSample):
            self.collector.ingest(self.sample(-10))

    def test_timestamp_regression_detected_per_source(self):
        self.seed()
        stamp = (self.time-timedelta(minutes=1)).isoformat()
        self.collector.ingest(self.change(self.sample(10), 'sim_import', last_reported=stamp, last_updated=stamp))
        self.assertEqual(self.last('simulated_marstek')[1], 'source_timestamp_regressed')
        self.assertEqual(self.last('measured_p1')[0], 'counter_changed')

    def test_bad_units_and_restored_states_remain_invalid(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'sim_import', unit='Wh'))
        self.assertEqual(self.last('simulated_marstek')[1], 'wrong_unit')
        self.collector.ingest(self.change(self.sample(20), 'sim_import', restored=True))
        self.assertEqual(self.last('simulated_marstek')[1], 'restored_or_unverified_state')

    def test_p1_sum_check_kept(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'real_import_1', state='90'))
        self.assertEqual(self.last('measured_p1')[1], 'p1_total_does_not_match_tariff_counters')

    def test_invalid_numbers_are_not_zero(self):
        for value in ['NaN', 'Infinity', '-1', 'unknown']:
            sample = self.change(self.sample(), 'sim_import', state=value)
            with self.assertRaises(c.InvalidSample):
                c.read_source(sample, self.config, 'simulated_marstek')

    def test_future_source_timestamp_is_not_accepted(self):
        self.seed()
        sample = self.change(self.sample(10), 'sim_import', last_reported=(self.time+timedelta(minutes=1)).isoformat())
        self.collector.ingest(sample)
        self.assertEqual(self.last('simulated_marstek')[1], 'invalid_or_future_source_timestamp')

    def test_reset_recovery_does_not_reuse_old_baseline(self):
        self.seed()
        self.collector.ingest(self.change(self.sample(10), 'sim_import', state='0'))
        at = (self.time+timedelta(seconds=20)).isoformat()
        self.collector.ingest(self.change(self.sample(20), 'sim_import', state='.001', last_updated=at, last_reported=at))
        self.assertEqual(self.last('simulated_marstek')[3]['observed_counter_deltas']['sim_import'], '0.001')
        self.assertFalse(self.collector.observations('2027-01-02')['coverage_confirmed'])

    def test_untrusted_source_window_field_does_not_enable_pairing(self):
        sample = self.sample()
        sample['processed_p1_window'] = {'confirmed': True, 'start': 0, 'end': 1}
        self.collector.ingest(sample)
        self.assertFalse(self.collector.observations('2027-01-02')['paired_grid_deltas_confirmed'])

    def test_partial_transaction_rolls_back_both_sources(self):
        self.collector.db.execute("CREATE TRIGGER fail_sim BEFORE INSERT ON source_observations_v2 WHEN NEW.source='simulated_marstek' BEGIN SELECT RAISE(ABORT,'test interruption'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.seed()
        self.assertEqual(self.collector.db.execute('SELECT COUNT(*) FROM source_observations_v2').fetchone()[0], 0)
        self.assertEqual(self.collector.db.execute('SELECT COUNT(*) FROM snapshots_v2').fetchone()[0], 0)

    def test_v1_journal_is_not_deleted_or_promoted(self):
        self.collector.db.execute('CREATE TABLE samples(ts TEXT,payload TEXT,valid INTEGER,reason TEXT,config_hash TEXT)')
        self.collector.db.execute("INSERT INTO samples VALUES ('old','preserve',1,'','old')")
        self.collector.db.commit()
        self.collector.close()
        self.collector = c.Collector(self.path, self.config)
        self.assertEqual(self.collector.db.execute('SELECT payload FROM samples').fetchone()[0], 'preserve')
        self.assertFalse(self.collector.observations('2027-01-02')['coverage_confirmed'])

    def test_configuration_change_records_discontinuity(self):
        self.seed()
        self.collector.close()
        self.config['max_observation_gap_seconds'] = 26
        self.collector = c.Collector(self.path, self.config)
        result = self.collector.ingest(self.sample(10))
        self.assertTrue(all(s['reason'] == 'configuration_changed' for s in result['sources'].values()))

    def test_cli_invalidates_previous_financial_report(self):
        config = Path(self.tmp.name) / 'config.json'
        config.write_text(json.dumps(self.config))
        output = Path(self.tmp.name) / 'observations.json'
        output.write_text('{"coverage_confirmed":true}')
        result = subprocess.run([sys.executable, str(ROOT / 'config/energy_finance/collector.py'),
                                 '--config', str(config), '--database', str(self.path), '--output', str(output),
                                 '--sample-url', '%7B%7D'], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(output.read_text())['coverage_confirmed'])

    def test_demonstrable_improvement_over_6fa804e(self):
        old = types.ModuleType('old_collector')
        exec(subprocess.check_output(['git', 'show', '6fa804e:config/energy_finance/collector.py'], text=True), old.__dict__)
        config = json.loads(subprocess.check_output(['git', 'show', '6fa804e:config/energy_finance/collector.json'], text=True))
        config.update(mapping_confirmed=True, pairing_confirmed=True, tariff_mapping={'1':'offpeak','2':'normal'})
        config['max_power_kw'] = dict.fromkeys(('real_import','real_export','sim_import','sim_export'), '20')
        with self.assertRaisesRegex(old.InvalidSample, 'stale_or_future_source'):
            old.validate(self.sample(), config)
        self.seed()
        result = self.collector.ingest(self.sample(10))
        self.assertEqual(result['sources']['measured_p1']['status'], 'counter_changed')
        self.assertEqual(result['sources']['simulated_marstek']['status'], 'unchanged_observation')
        self.assertFalse(self.collector.observations('2027-01-02')['paired_grid_deltas_confirmed'])

    def test_finance_and_collector_tariff_mappings_match(self):
        finance_config = json.loads((ROOT / 'config/energy_finance/tariffs.json').read_text())
        self.assertTrue(self.config['mapping_confirmed'])
        self.assertEqual(self.config['tariff_mapping'], {'1': 'offpeak', '2': 'normal'})
        self.assertTrue(finance_config['p1_tariff_mapping']['confirmed'])
        self.assertEqual(finance_config['p1_tariff_mapping']['codes'], self.config['tariff_mapping'])


if __name__ == '__main__':
    unittest.main()
