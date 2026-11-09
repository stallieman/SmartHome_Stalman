import copy
import hashlib
import json
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'energy_finance'))
from batch_contract import SOURCE_SHA
from collector import encoded
from compare import scenario_2027_14d_report


class RollingScenarioTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'energy_finance/tariffs.json').read_text())
        self.policy = json.loads((ROOT / 'energy_finance/collector.json').read_text())
        self.policy['audit'].update(enabled=True, battery_id='battery', expected_helper_sha256='helper')
        self.fingerprint = hashlib.sha256(encoded(self.policy).encode()).hexdigest()
        self.now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('CREATE TABLE audit_packets_v1 (generation TEXT, sequence INTEGER, payload TEXT, config_hash TEXT, end_ts TEXT); CREATE TABLE audit_faults_v1 (generation TEXT);')

    def packet(self, generation, start, duration=3600, delta='1', simulated='0.5'):
        end = start + timedelta(seconds=duration)
        return {'producer': 'stalman_audit_v1', 'upstream_sha256': SOURCE_SHA, 'helper_sha256': 'helper',
                'battery_id': 'battery', 'valid': True, 'generation': generation, 'sequence': 1,
                'processing_start': start.isoformat(), 'processing_end': end.isoformat(),
                'sources': {'import': self.policy['entities']['real_import'], 'export': self.policy['entities']['real_export']},
                'tariff_before': {'code': '1', 'last_changed': (start-timedelta(hours=1)).isoformat()},
                'tariff_after': {'code': '1', 'last_changed': (start-timedelta(hours=1)).isoformat()},
                'tariff_registers_before': {'import': {'1': '10', '2': '0'}, 'export': {'1': '20', '2': '0'}},
                'tariff_registers_after': {'import': {'1': str(10+float(delta)), '2': '0'}, 'export': {'1': '20', '2': '0'}},
                'measured_before': {'import': '10', 'export': '20'},
                'measured_after': {'import': str(10+float(delta)), 'export': '20'},
                'simulated_before': {'import': '10', 'export': '20'},
                'simulated_after': {'import': str(10+float(simulated)), 'export': '20'},
                'accepted_events': [{'role': 'import', 'old': {'counter': '10', 'at': start.isoformat(), 'reset': None},
                                     'new': {'counter': str(10+float(delta)), 'at': end.isoformat(), 'reset': None}}]}

    def add(self, packet, fingerprint=None):
        self.db.execute('INSERT INTO audit_packets_v1 VALUES (?,?,?,?,?)',
                        (packet['generation'], packet['sequence'], json.dumps(packet), fingerprint or self.fingerprint, packet['processing_end']))

    def result(self):
        return scenario_2027_14d_report(self.config, self.policy, self.db, self.now)

    def test_sums_unrounded_costs_and_reports_coverage(self):
        # Each packet saves 0.00144642 EUR; four together round to one cent.
        for i in range(4):
            self.add(self.packet(str(i), self.now-timedelta(hours=4-i), delta='0.01', simulated='0.005'))
        result = self.result()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['valid_hours'], '4.00')
        self.assertEqual(result['coverage_percent'], '1.19')
        self.assertEqual(result['saving_eur'], '0.01')
        self.assertEqual((result['without_eur'], result['with_eur']), ('0.01', '0.01'))

    def test_overlap_rejects_both_and_boundary_is_not_interpolated(self):
        self.add(self.packet('a', self.now-timedelta(hours=4)))
        self.add(self.packet('b', self.now-timedelta(hours=3, minutes=30)))
        self.add(self.packet('c', self.now-timedelta(hours=2)))
        self.add(self.packet('boundary', self.now-timedelta(hours=336, minutes=30)))
        result = self.result()
        self.assertEqual(result['valid_hours'], '1.00')
        self.assertEqual(result['coverage_percent'], '0.30')

    def test_invalid_configuration_fault_and_tariff_are_excluded(self):
        self.add(self.packet('old', self.now-timedelta(hours=4)), 'different')
        self.add(self.packet('fault', self.now-timedelta(hours=3)))
        self.db.execute('INSERT INTO audit_faults_v1 VALUES (?)', ('fault',))
        bad = self.packet('tariff', self.now-timedelta(hours=2))
        bad['tariff_after']['code'] = '2'
        self.add(bad)
        result = self.result()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['valid_hours'], '0.00')
        self.assertEqual(result['coverage_percent'], '0.00')

    def test_missing_sequence_rejects_entire_generation(self):
        p = self.packet('missing', self.now-timedelta(hours=1))
        p['sequence'] = 2
        self.add(p)
        self.assertEqual(self.result()['status'], 'unavailable')

    def test_audit_disabled_is_unavailable(self):
        self.policy['audit']['enabled'] = False
        self.assertEqual(self.result()['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
