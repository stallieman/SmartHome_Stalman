import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'energy_finance'))
from compare import report, scenario_2027_report


class Scenario2027Tests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'energy_finance/tariffs.json').read_text())
        self.observation = {
            'coverage_confirmed': True, 'paired_grid_deltas_confirmed': True,
            'scope': 'window', 'start': '2026-11-07', 'end': '2026-11-08',
            'measured_from': '2026-11-07T10:00:00+01:00',
            'observed_until': '2026-11-07T11:00:00+01:00',
            'coverage_kind': 'contiguous_partial_day',
            'without': {'import_kwh': {'normal': '10', 'offpeak': '5'}, 'export_kwh': '3'},
            'with': {'import_kwh': {'normal': '7', 'offpeak': '4'}, 'export_kwh': '2'},
        }

    def test_costs_discount_export_and_actual_window(self):
        original = copy.deepcopy(self.config)
        result = scenario_2027_report(self.config, self.observation)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['classification'], 'Indicatieve simulatie met 2027-aannames')
        self.assertEqual((result['without_eur'], result['with_eur'], result['saving_eur']), ('4.36', '3.20', '1.16'))
        self.assertEqual(result['measured_from'], self.observation['measured_from'])
        self.assertEqual(result['observed_until'], self.observation['observed_until'])
        self.assertEqual(self.config, original)

    def test_regular_2026_netting_remains_blocked(self):
        result = report(self.config, self.observation)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['reason'], 'Annual netting cannot be calculated as a daily saving')

    def test_unverified_or_incomplete_input_fails_closed(self):
        for key in ('coverage_confirmed', 'paired_grid_deltas_confirmed'):
            obs = copy.deepcopy(self.observation); obs[key] = False
            self.assertEqual(scenario_2027_report(self.config, obs)['status'], 'unavailable')
        for key in ('measured_from', 'observed_until'):
            obs = copy.deepcopy(self.observation); obs.pop(key)
            self.assertEqual(scenario_2027_report(self.config, obs)['status'], 'unavailable')
        obs = copy.deepcopy(self.observation); obs['with']['import_kwh']['normal'] = '-1'
        self.assertEqual(scenario_2027_report(self.config, obs)['status'], 'unavailable')
        obs = copy.deepcopy(self.observation); obs['scope'] = 'billing'
        self.assertEqual(scenario_2027_report(self.config, obs)['status'], 'unavailable')

    def test_missing_or_inconsistent_tariff_is_unavailable(self):
        config = copy.deepcopy(self.config); config['plans'][1]['export_fee_cash_per_kwh'] = None
        self.assertEqual(scenario_2027_report(config, self.observation)['status'], 'unavailable')
        config = copy.deepcopy(self.config); config['plans'][0]['import']['normal']['quoted_total'] = '0.50'
        self.assertEqual(scenario_2027_report(config, self.observation)['status'], 'unavailable')

    def test_distinct_output_when_cost_increases(self):
        obs = copy.deepcopy(self.observation)
        obs['without'], obs['with'] = obs['with'], obs['without']
        self.assertEqual(scenario_2027_report(self.config, obs)['saving_eur'], '-1.16')


if __name__ == '__main__':
    unittest.main()
