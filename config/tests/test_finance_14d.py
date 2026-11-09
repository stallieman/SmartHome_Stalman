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
from batch_contract import SOURCE_SHA, consume, consume_prefix
from collector import InvalidSample
from compare import scenario_2027_totals
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
        self.addCleanup(self.db.close)
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

    def chain(self, numbers):
        """Build actual adjacent counter boundaries; skipped numbers leave a real gap."""
        from decimal import Decimal
        first = self.now - timedelta(minutes=40)
        result = []
        for number in numbers:
            start = first + timedelta(minutes=number - 1)
            packet = self.packet('chain', start, duration=60)
            packet['sequence'] = number
            before = Decimal('10') + Decimal(number - 1)
            after = before + 1
            sim_before = Decimal('10') + Decimal(number - 1) / 2
            sim_after = sim_before + Decimal('0.5')
            packet['measured_before']['import'] = str(before)
            packet['measured_after']['import'] = str(after)
            packet['tariff_registers_before']['import']['1'] = str(before)
            packet['tariff_registers_after']['import']['1'] = str(after)
            packet['simulated_before']['import'] = format(sim_before, '.1f')
            packet['simulated_after']['import'] = format(sim_after, '.1f')
            packet['accepted_events'][0]['old']['counter'] = str(before)
            packet['accepted_events'][0]['new']['counter'] = str(after)
            result.append(packet)
        return result

    def test_missing_35_36_admits_only_valid_prefix_and_coverage(self):
        packets = self.chain(list(range(1, 35)) + [37, 38])
        for packet in packets:
            self.add(packet)
        result = self.result()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['valid_hours'], '0.57')
        self.assertEqual(result['coverage_percent'], '0.17')
        self.assertEqual(result['without_eur'], '9.84')
        self.assertEqual(result['with_eur'], '4.92')
        self.assertEqual(result['saving_eur'], '4.92')
        report, admitted = consume_prefix(self.policy, packets)
        self.assertEqual([p['sequence'] for p in admitted], list(range(1, 35)))
        self.assertEqual(report['observed_until'], packets[33]['processing_end'])

    def test_duplicate_sequence_invalidates_generation(self):
        packets = self.chain([1, 2, 2, 3])
        with self.assertRaises(InvalidSample):
            consume_prefix(self.policy, packets)
        for packet in packets:
            self.add(packet)
        self.assertEqual(self.result()['status'], 'unavailable')

    def test_prefix_keeps_all_normal_validation(self):
        for field in ('reset', 'tariff', 'battery', 'identity'):
            with self.subTest(field=field):
                packets = self.chain([1, 2, 4])
                if field == 'reset':
                    packets[1]['accepted_events'][0]['new']['reset'] = 'reset'
                elif field == 'tariff':
                    packets[1]['tariff_after']['code'] = '2'
                elif field == 'battery':
                    packets[1]['simulated_before']['import'] = '999'
                else:
                    packets[1]['helper_sha256'] = 'wrong'
                with self.assertRaises(InvalidSample):
                    consume_prefix(self.policy, packets)

    def test_configuration_change_in_suffix_rejects_generation(self):
        for packet in self.chain([1, 2, 4]):
            self.add(packet, 'other' if packet['sequence'] == 4 else None)
        self.assertEqual(self.result()['status'], 'unavailable')

    def test_complete_chain_has_identical_unrounded_totals(self):
        packets = self.chain([1, 2, 3, 4])
        prior = consume(self.policy, packets)
        actual, admitted = consume_prefix(self.policy, packets)
        self.assertEqual(actual, prior)
        self.assertEqual(scenario_2027_totals(self.config, actual), scenario_2027_totals(self.config, prior))
        self.assertEqual(admitted, packets)

    def test_audit_disabled_is_unavailable(self):
        self.policy['audit']['enabled'] = False
        self.assertEqual(self.result()['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
