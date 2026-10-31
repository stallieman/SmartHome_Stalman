"""Synthetic test data only; no tariffs or daily observations for production."""
import importlib.util
import copy
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('finance', Path(__file__).resolve().parents[1] / 'config/energy_finance/compare.py')
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class FinanceTests(unittest.TestCase):
    def setUp(self):
        rate = {'quoted_total': '.363', 'quote_includes_vat': True,
                'quote_includes_discount': False, 'delivery_ex_vat': '.20', 'energy_tax_ex_vat': '.10'}
        self.plan = {'id': 'synthetic', 'valid_from': '2025-01-01', 'valid_until': '2029-01-01',
                     'confirmed': True, 'cash_basis_confirmed': True, 'vat_fraction': '.21',
                     'delivery_discount_fraction': '.10', 'import': {'normal': rate, 'offpeak': copy.deepcopy(rate)},
                     'export_credit_cash_per_kwh': '.08', 'export_fee_cash_per_kwh': '.06'}
        self.config = {'netting_ends': '2027-01-01', 'plans': [self.plan]}
        self.obs = {'scope': 'day', 'start': '2027-01-02', 'end': '2027-01-03',
                    'observed_until': '2027-01-02T12:00:00+01:00',
                    'coverage_confirmed': True, 'paired_grid_deltas_confirmed': True,
                    'without': {'import_kwh': {'normal': '10', 'offpeak': '0'}, 'export_kwh': '8'},
                    'with': {'import_kwh': {'normal': '8', 'offpeak': '0'}, 'export_kwh': '5'}}

    def result(self):
        return f.report(self.config, self.obs)

    def blocked(self):
        self.assertEqual(self.result()['status'], 'unavailable')
        self.assertIsNone(self.result()['saving_eur'])

    def test_discount_only_on_delivery(self):
        self.assertEqual(f.effective_rates(self.plan)['normal'], f.Decimal('.3388'))
        self.assertNotEqual(f.effective_rates(self.plan)['normal'], f.Decimal('.363') * f.Decimal('.9'))

    def test_post_netting_cost_and_losses(self):
        # Import reduction 2 kWh, export reduction 3: loss is already represented.
        r = self.result()
        self.assertEqual(r['without_eur'], '3.23')
        self.assertEqual(r['with_eur'], '2.61')
        self.assertEqual(r['saving_eur'], '0.62')

    def test_different_tariffs(self):
        self.plan['import']['offpeak'].update(delivery_ex_vat='.10', quoted_total='.242')
        self.obs['with']['import_kwh'] = {'normal': '0', 'offpeak': '8'}
        self.assertEqual(self.result()['with_eur'], '1.74')

    def test_already_discounted_quote(self):
        for r in self.plan['import'].values():
            r.update(quoted_total='.3388', quote_includes_discount=True)
        self.assertEqual(self.result()['status'], 'ok')

    def test_ex_vat_quote(self):
        for r in self.plan['import'].values():
            r.update(quoted_total='.30', quote_includes_vat=False)
        self.assertEqual(self.result()['status'], 'ok')

    def test_negative_saving_allowed(self):
        self.obs['with']['import_kwh']['normal'] = '15'
        self.assertLess(f.number(self.result()['saving_eur']), 0)

    def test_zero_rates_are_valid_when_confirmed(self):
        for r in self.plan['import'].values():
            r.update(quoted_total='0', delivery_ex_vat='0', energy_tax_ex_vat='0')
        self.plan.update(export_credit_cash_per_kwh='0', export_fee_cash_per_kwh='0')
        self.assertEqual(self.result()['saving_eur'], '0.00')

    def test_missing_tax(self):
        self.plan['import']['normal']['energy_tax_ex_vat'] = None
        self.blocked()

    def test_unknown_vat(self):
        self.plan['import']['normal']['quote_includes_vat'] = None
        self.blocked()

    def test_rate_reconciliation(self):
        self.plan['import']['normal']['quoted_total'] = '.123'
        self.blocked()

    def test_unconfirmed(self):
        self.plan['confirmed'] = False
        self.blocked()

    def test_cash_basis_required(self):
        self.plan['cash_basis_confirmed'] = False
        self.blocked()

    def test_unknown_period(self):
        self.plan['valid_until'] = None
        self.blocked()

    def test_overlapping_plans(self):
        self.config['plans'].append(copy.deepcopy(self.plan))
        self.blocked()

    def test_missing_simulated_tariff_split(self):
        del self.obs['with']['import_kwh']['offpeak']
        self.blocked()

    def test_incomplete_or_unpaired(self):
        for key in ['coverage_confirmed', 'paired_grid_deltas_confirmed']:
            with self.subTest(key=key):
                old = self.obs[key]
                self.obs[key] = False
                self.blocked()
                self.obs[key] = old

    def test_invalid_readings(self):
        for value in ['NaN', 'Infinity', '-1', None, 'unavailable']:
            with self.subTest(value=value):
                self.obs['with']['export_kwh'] = value
                self.blocked()

    def test_no_daily_netting(self):
        self.obs.update(start='2026-05-01', end='2026-05-02', observed_until='2026-05-01T12:00:00+02:00')
        self.blocked()

    def annual(self):
        self.obs.update(start='2025-01-01', end='2026-01-01', scope='billing', billing_period_complete=True, observed_until='2026-01-01T00:00:00+01:00')
        for s in ['without', 'with']:
            self.obs[s].update(netted_import_kwh={'normal': self.obs[s]['export_kwh'], 'offpeak': '0'},
                               export_charges_confirmed=True, export_charges_eur='10')

    def test_annual_netting(self):
        self.annual()
        # 2 kWh vs 3 kWh net import; battery losses can hurt under netting.
        r = self.result()
        self.assertEqual(r['without_eur'], '10.68')
        self.assertEqual(r['with_eur'], '11.02')
        self.assertEqual(r['saving_eur'], '-0.34')

    def test_only_surplus_export_compensated(self):
        self.annual()
        self.obs['without'].update(export_kwh='12', netted_import_kwh={'normal': '10', 'offpeak': '0'})
        self.assertEqual(self.result()['without_eur'], '9.84')

    def test_incomplete_allocation(self):
        self.annual()
        self.obs['with']['netted_import_kwh']['normal'] = '0'
        self.blocked()

    def test_no_implicit_zero_return_costs(self):
        self.annual()
        self.obs['with']['export_charges_confirmed'] = False
        self.blocked()

    def test_boundary_must_be_split(self):
        self.annual()
        self.obs.update(start='2026-06-01', end='2027-06-01')
        self.blocked()

    def test_boundary_configurable(self):
        self.config['netting_ends'] = '2028-01-01'
        self.blocked()

    def test_supplied_export_difference_only_after_confirmation(self):
        self.plan.update(export_credit_cash_per_kwh='.08343', export_fee_cash_per_kwh='.08092')
        r = f.calculate(self.config, self.obs)
        self.assertEqual(f.number(r['without_export_credit_eur']), f.Decimal('.67'))
        self.assertEqual(f.number(r['without_export_costs_eur']), f.Decimal('.65'))
        self.plan['cash_basis_confirmed'] = False
        self.blocked()

    def test_missing_timestamp(self):
        del self.obs['observed_until']
        self.blocked()

    def test_production_config_is_blocked(self):
        import json
        cfg = Path(__file__).resolve().parents[1] / 'config/energy_finance/tariffs.json'
        result = f.report(json.loads(cfg.read_text()), self.obs)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['saving_eur'])

    def test_year_reference_does_not_create_observations(self):
        self.config['historical_reference_only'] = {'import_kwh': 3133, 'export_kwh': 2366}
        self.assertEqual(self.result()['saving_eur'], '0.62')


if __name__ == '__main__':
    unittest.main()
