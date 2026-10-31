"""All observations in this file are synthetic; no live HA connection."""
import copy
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT / 'config/energy_finance/collector.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
spec = importlib.util.spec_from_file_location('comparison', ROOT / 'config/energy_finance/compare.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'intervals.sqlite'
        self.config = json.loads((ROOT / 'config/energy_finance/collector.json').read_text())
        self.config.update(mapping_confirmed=True, pairing_confirmed=True,
                           tariff_mapping={'1': 'offpeak', '2': 'normal'})
        self.config['max_power_kw'] = dict.fromkeys(('real_import', 'real_export', 'sim_import', 'sim_export'), '20')
        self.collector = c.Collector(self.db, self.config)
        self.time = datetime(2027, 1, 2, 0, 0, tzinfo=c.TZ)

    def tearDown(self):
        self.collector.close()
        self.tmp.cleanup()

    def sample(self, seconds=0, step=0):
        now = self.time + timedelta(seconds=seconds)
        values = {'real_import': 100 + c.Decimal('.05') * step,
                  'real_export': 20 + c.Decimal('.01') * step,
                  'real_import_1': 100 + c.Decimal('.05') * step, 'real_import_2': 0,
                  'real_export_1': 20 + c.Decimal('.01') * step, 'real_export_2': 0,
                  'sim_import': 100 + c.Decimal('.04') * step,
                  'sim_export': 20 + c.Decimal('.005') * step}
        states = {self.config['entities'][role]: {'state': str(value), 'unit': 'kWh',
                  'last_reported': now.isoformat(), 'last_reset': '2026-12-01T00:00:00+01:00',
                  'restored': False} for role, value in values.items()}
        states[self.config['entities']['tariff']] = {'state': '1', 'last_reported': now.isoformat(),
                  'last_changed': (self.time - timedelta(days=1)).isoformat(), 'restored': False}
        return {'captured_at': now.isoformat(), 'session': 'boot-one', 'states': states}

    def change(self, sample, role, key, value):
        sample['states'][self.config['entities'][role]][key] = value
        return sample

    def seed(self):
        self.collector.ingest(self.sample())

    def observations(self):
        return self.collector.observations('2027-01-02')

    def test_paired_deltas_and_tariff(self):
        self.seed()
        self.collector.ingest(self.sample(30, 1))
        result = self.observations()
        self.assertTrue(result['coverage_confirmed'])
        self.assertEqual(result['without']['import_kwh'], {'normal': '0', 'offpeak': '0.05'})
        self.assertEqual(result['with']['import_kwh']['offpeak'], '0.04')
        self.assertEqual(result['with']['export_kwh'], '0.005')

    def test_duplicate_does_not_add_energy(self):
        self.seed()
        s = self.sample(30, 1)
        self.collector.ingest(s)
        self.assertEqual(self.collector.ingest(s)['status'], 'duplicate')
        self.assertEqual(self.observations()['with']['import_kwh']['offpeak'], '0.04')

    def test_conflicting_duplicate_taints_day_durably(self):
        self.seed()
        s = self.sample(30, 1)
        self.collector.ingest(s)
        s['session'] = 'different'
        with self.assertRaises(c.InvalidSample):
            self.collector.ingest(s)
        self.collector.ingest(self.sample(60, 2))
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_process_restart_preserves_baseline(self):
        self.seed()
        self.collector.close()
        self.collector = c.Collector(self.db, self.config)
        self.collector.ingest(self.sample(30, 1))
        self.assertTrue(self.observations()['coverage_confirmed'])

    def test_ha_restart_does_not_bridge(self):
        self.seed()
        s = self.sample(30, 1)
        s['session'] = 'boot-two'
        self.assertEqual(self.collector.ingest(s)['reason'], 'ha_restart')
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_missing_interval(self):
        self.seed()
        self.assertEqual(self.collector.ingest(self.sample(120, 4))['reason'], 'missing_interval')
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_unavailable_never_becomes_zero(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'state', 'unavailable')
        self.collector.ingest(s)
        self.collector.ingest(self.sample(60, 2))
        result = self.observations()
        self.assertFalse(result['coverage_confirmed'])
        self.assertIsNone(result['with'])

    def test_reset_decrease(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'state', '0')
        self.assertEqual(self.collector.ingest(s)['reason'], 'counter_reset_or_decrease')

    def test_reset_metadata_even_if_counter_grew(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'last_reset', '2027-01-02T00:00:15+01:00')
        self.assertEqual(self.collector.ingest(s)['reason'], 'reset_metadata_changed')

    def test_tariff_change_is_not_prorated(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'tariff', 'state', '2')
        self.assertEqual(self.collector.ingest(s)['reason'], 'tariff_transition')

    def test_tariff_switch_and_back_is_detected(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'tariff', 'last_changed',
                        (self.time + timedelta(seconds=15)).isoformat())
        self.assertEqual(self.collector.ingest(s)['reason'], 'tariff_transition')

    def test_inactive_real_register_crosschecks_tariff(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'real_import_2', 'state', '.01')
        s = self.change(s, 'real_import', 'state', '100.06')
        self.assertEqual(self.collector.ingest(s)['reason'], 'inactive_tariff_counter_changed')

    def test_stale_source(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'last_reported',
                        (self.time - timedelta(minutes=10)).isoformat())
        self.assertEqual(self.collector.ingest(s)['reason'], 'stale_or_future_source')

    def test_repeated_old_report_is_not_a_measured_zero(self):
        self.seed()
        s = self.sample(5, 0)
        for value in s['states'].values():
            value['last_reported'] = self.time.isoformat()
        self.assertEqual(self.collector.ingest(s)['reason'], 'source_not_reported_in_interval')
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_missing_session_state_is_rejected(self):
        s = self.sample()
        s['session'] = 'unknown'
        self.assertEqual(self.collector.ingest(s)['reason'], 'missing_ha_session')

    def test_source_skew(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'last_reported', self.time.isoformat())
        self.assertEqual(self.collector.ingest(s)['reason'], 'source_timestamp_skew')

    def test_p1_sums_must_match(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'real_import', 'state', '110')
        self.assertEqual(self.collector.ingest(s)['reason'], 'p1_total_does_not_match_tariff_counters')

    def test_unit_validation(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'unit', 'Wh')
        self.assertEqual(self.collector.ingest(s)['reason'], 'wrong_unit')

    def test_restored_state_rejected(self):
        s = self.change(self.sample(), 'sim_import', 'restored', True)
        self.assertEqual(self.collector.ingest(s)['reason'], 'restored_or_unverified_state')

    def test_out_of_order_rejected(self):
        self.seed()
        with self.assertRaises(c.InvalidSample):
            self.collector.ingest(self.sample(-30))

    def test_mapping_requires_confirmation(self):
        self.config['mapping_confirmed'] = False
        with self.assertRaises(c.InvalidSample):
            c.Collector(Path(self.tmp.name) / 'other.sqlite', self.config)

    def test_pairing_confirmation_required_for_finance(self):
        self.seed()
        self.collector.config['pairing_confirmed'] = False
        self.collector.ingest(self.sample(30, 1))
        self.assertFalse(self.observations()['paired_grid_deltas_confirmed'])

    def test_partial_installation_day_is_explicit_opt_in(self):
        self.collector.ingest(self.sample(10))
        self.collector.ingest(self.sample(40, 1))
        self.assertFalse(self.observations()['coverage_confirmed'])
        self.collector.config['allow_partial_first_day'] = True
        self.assertEqual(self.observations()['coverage_kind'], 'contiguous_partial_day')
        self.assertTrue(self.observations()['coverage_confirmed'])

    def test_midnight_not_interpolated(self):
        self.collector.ingest(self.sample(-10))
        self.assertEqual(self.collector.ingest(self.sample(20, 1))['reason'], 'midnight_boundary_not_sampled')
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_jump_rejected(self):
        self.seed()
        s = self.change(self.sample(30, 1), 'sim_import', 'state', '200')
        self.assertEqual(self.collector.ingest(s)['reason'], 'implausible_counter_jump')

    def test_configuration_change_breaks_chain(self):
        self.seed()
        self.collector.close()
        self.config['max_interval_seconds'] = 46
        self.collector = c.Collector(self.db, self.config)
        self.assertEqual(self.collector.ingest(self.sample(30, 1))['reason'], 'configuration_changed')
        self.assertFalse(self.observations()['coverage_confirmed'])

    def test_true_zero_delta_is_valid(self):
        self.seed()
        self.collector.ingest(self.sample(30, 0))
        self.assertEqual(self.observations()['with']['import_kwh']['offpeak'], '0.00')

    def test_atomic_export(self):
        p = Path(self.tmp.name) / 'observations.json'
        c.atomic_json(p, {'old': True})
        c.atomic_json(p, {'coverage_confirmed': False, 'with': None})
        self.assertIsNone(json.loads(p.read_text())['with'])
        self.assertEqual(list(Path(self.tmp.name).glob('.observations*')), [])

    def test_cli_failure_invalidates_old_report(self):
        config = Path(self.tmp.name) / 'config.json'
        config.write_text(json.dumps(self.config))
        output = Path(self.tmp.name) / 'observations.json'
        output.write_text('{"coverage_confirmed":true}')
        result = subprocess.run([sys.executable, str(ROOT / 'config/energy_finance/collector.py'),
                                 '--config', str(config), '--database', str(self.db), '--output', str(output),
                                 '--sample-url', '%7B%7D'], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(output.read_text())['coverage_confirmed'])

    def test_amsterdam_dst_midnight_bounds(self):
        self.time = datetime(2027, 10, 31, tzinfo=c.TZ)
        self.seed()
        self.collector.ingest(self.sample(30, 1))
        result = self.collector.observations('2027-10-31')
        self.assertTrue(result['coverage_confirmed'])
        self.assertEqual(result['end'], '2027-11-01')

    def test_collector_to_finance_with_confirmed_synthetic_contract(self):
        self.seed()
        self.collector.ingest(self.sample(30, 1))
        rate = {'quoted_total': '.242', 'quote_includes_vat': True, 'quote_includes_discount': False,
                'delivery_ex_vat': '.10', 'energy_tax_ex_vat': '.10'}
        config = {'netting_ends': '2027-01-01', 'plans': [{
            'id': 'test-only', 'valid_from': '2027-01-01', 'valid_until': '2028-01-01',
            'confirmed': True, 'cash_basis_confirmed': True, 'vat_fraction': '.21',
            'delivery_discount_fraction': '.1', 'import': {'normal': rate, 'offpeak': rate},
            'export_credit_cash_per_kwh': '.08', 'export_fee_cash_per_kwh': '.06'}]}
        result = f.report(config, self.observations())
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['coverage_kind'], 'from_midnight')

    def test_explicit_partial_segment_is_labelled_by_finance(self):
        self.collector.config['allow_partial_first_day'] = True
        self.collector.ingest(self.sample(10))
        self.collector.ingest(self.sample(40, 1))
        observation = self.observations()
        cfg = json.loads((ROOT / 'config/energy_finance/tariffs.json').read_text())
        result = f.report(cfg, observation)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('plan', result['reason'])
        # Unlabelled partial periods must fail before tariff calculation.
        del observation['coverage_kind']
        self.assertIn('Unmarked', f.report(cfg, observation)['reason'])

    def test_valid_collected_input_reaches_finance_validation(self):
        self.seed()
        self.collector.ingest(self.sample(30, 1))
        observation = self.observations()
        cfg = json.loads((ROOT / 'config/energy_finance/tariffs.json').read_text())
        result = f.report(cfg, observation)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('plan', result['reason'])  # Missing contract, not missing collector data.


if __name__ == '__main__':
    unittest.main()
