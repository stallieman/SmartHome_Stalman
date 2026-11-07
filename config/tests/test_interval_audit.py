import importlib.util
from pathlib import Path
import unittest
from types import SimpleNamespace

path = Path(__file__).parents[1] / 'custom_components/battery_sim/interval_audit.py'
spec = importlib.util.spec_from_file_location('interval_audit', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntervalAuditTests(unittest.TestCase):
    def setUp(self):
        self.audit = module.IntervalAudit('battery')
        self.tariff = {'code': '1', 'last_changed': '2026-11-07T00:00:00+00:00'}
        self.audit.reading('import', 'p1_i', 10, 11, 'a', 'b')
        self.audit.reading('export', 'p1_e', 20, 21, 'a', 'b')
        self.audit.finish('2026-11-07T01:00:00+00:00', {'import': 10, 'export': 20}, {'import': 11, 'export': 21}, self.tariff)

    def finish(self, before, after, tariff=None):
        return self.audit.finish('2026-11-07T01:01:00+00:00', before, after, tariff or self.tariff)

    def test_records_actual_events_and_counters(self):
        self.audit.reading('import', 'p1_i', 11, 12, 'a', 'b')
        packet = self.finish({'import': 11, 'export': 21}, {'import': 11.5, 'export': 21})
        self.assertEqual(packet['measured_before'], {'import': 11, 'export': 21})
        self.assertEqual(packet['measured_after'], {'import': 12, 'export': 21})
        self.assertEqual(packet['accepted_events'][0]['entity'], 'p1_i')
        self.assertEqual(packet['tariff_after']['code'], '1')
        self.assertFalse(packet['financially_certified'])
        self.assertEqual(packet['reasons'], [])

    def test_extra_grid_charging_is_explicitly_unallocated(self):
        packet = self.finish({'import': 11, 'export': 21}, {'import': 12, 'export': 21})
        self.assertEqual(packet['extra_grid_import_kwh'], 1)
        self.assertIn('extra_grid_charging_unallocated', packet['reasons'])

    def test_diagnostic_extra_import_rounding_boundary(self):
        from decimal import Decimal
        for difference, flagged in [('0.000000001', False), ('0.000000001001', True)]:
            with self.subTest(difference=difference):
                audit = module.IntervalAudit('battery')
                audit.seed('import', 10)
                audit.seed('export', 20)
                audit.finish('2026-11-07T01:00:00+00:00', {'import': 10, 'export': 20}, {'import': 10, 'export': 20}, self.tariff)
                audit.reading('import', 'p1_i', 10, 11, 'a', 'b')
                packet = audit.finish('2026-11-07T01:01:00+00:00', {'import': 10, 'export': 20}, {'import': str(Decimal('11') + Decimal(difference)), 'export': 20}, self.tariff)
                self.assertEqual('extra_grid_charging_unallocated' in packet['reasons'], flagged)

    def test_tariff_transition_and_counter_reset_are_flagged(self):
        self.audit.reading('import', 'p1_i', 11, 1, 'a', 'b')
        tariff = {'code': '2', 'last_changed': '2026-11-07T01:00:30+00:00'}
        packet = self.finish({'import': 11, 'export': 21}, {'import': 11, 'export': 21}, tariff)
        self.assertIn('counter_reset_or_gap', packet['reasons'])
        self.assertIn('tariff_unverified_or_changed', packet['reasons'])

    def test_seed_unchanged_export_and_preserve_import_events(self):
        audit = module.IntervalAudit('battery')
        audit.seed('export', 21.0)
        audit.seed('import', 11.0)
        audit.finish('2026-11-07T01:00:00+00:00', {'import': 11, 'export': 21}, {'import': 11, 'export': 21}, self.tariff)
        audit.reading('import', 'p1_i', 11, 12, 'a', 'b')
        packet = audit.finish('2026-11-07T01:01:00+00:00', {'import': 11, 'export': 21}, {'import': 11.5, 'export': 21}, self.tariff)
        self.assertEqual(packet['measured_before'], {'import': 11, 'export': 21})
        self.assertEqual(packet['measured_after'], {'import': 12, 'export': 21})
        self.assertNotIn('missing_baseline', packet['reasons'])
        self.assertFalse(packet['financially_certified'])

    def test_seed_does_not_replace_processed_counter(self):
        self.audit.seed('export', 99)
        self.assertEqual(self.audit.last['export'], 21)

    def test_invalidated_baseline_is_not_reused(self):
        self.audit.invalidate('export', 'invalid_source_state')
        packet = self.finish({'import': 11, 'export': 21}, {'import': 11, 'export': 21})
        self.assertNotIn('export', packet['measured_after'])
        self.assertIn('invalid_source_state', packet['reasons'])
        self.assertIn('missing_baseline', packet['reasons'])

    def test_only_valid_non_restored_counters_are_seeded(self):
        def state(value, unit='kWh', restored=False):
            return SimpleNamespace(state=value, attributes={'unit_of_measurement': unit, 'restored': restored})
        self.assertEqual(module.valid_counter(state('1200', 'Wh')), 1.2)
        for item in (None, state('unknown'), state('nan'), state('-1'),
                     state('1', 'W'), state('1', restored=True)):
            self.assertIsNone(module.valid_counter(item))

    def test_missing_baseline_is_flagged(self):
        packet = module.IntervalAudit('battery').finish('2026-11-07T01:00:00+00:00', {}, {}, None)
        self.assertIn('missing_baseline', packet['reasons'])
        self.assertIn('missing_simulated_counter', packet['reasons'])

if __name__ == '__main__':
    unittest.main()
