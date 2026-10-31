"""Tests of audit transport/contract, not a reimplementation of battery physics.
The reference processing callback below stands in for the unmodified model.
"""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'config/energy_finance'))
from collector import Collector, InvalidSample
from batch_contract import consume
from compare import report

spec = importlib.util.spec_from_file_location('audit_proposal', ROOT / 'proposals/battery_sim_audit/stalman_audit.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
spec = importlib.util.spec_from_file_location('patch_proposal', ROOT / 'proposals/battery_sim_audit/prepare_patch.py')
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)
BASE = datetime(2027, 1, 2, 8, 0, tzinfo=timezone.utc)

class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return BASE.astimezone(tz or timezone.utc)


def state(value, at=BASE, unit='kWh'):
    return SimpleNamespace(state=str(value), attributes={'unit_of_measurement': unit}, last_updated=at,
                           last_changed=BASE-timedelta(hours=1))

class Handle:
    def __init__(self):
        self._entry_id = 'test-battery'
        self._inputs = [{'sensor_type': 'Import', 'sensor_id': 'sensor.p1_meter_energie_import', 'simulated_sensor': 'sim_i'},
                        {'sensor_type': 'Export', 'sensor_id': 'sensor.p1_meter_energie_export', 'simulated_sensor': 'sim_e'}]
        self.states = {self._inputs[0]['sensor_id']: state(100), self._inputs[1]['sensor_id']: state(20),
                       'sensor.p1_meter_tarief': state('1')}
        for role, total in [('import',100),('export',20)]:
            for code in ('1','2'):
                self.states['sensor.p1_meter_energie_'+role+'_tarief_'+code]=state(total if code=='1' else 0)
        self.packets = []
        self._hass = SimpleNamespace(states=SimpleNamespace(get=self.states.get),
                                    bus=SimpleNamespace(async_fire=lambda name, packet: self.packets.append(packet)))
        self._last_battery_update_time = BASE.timestamp()
        self._accumulated_import_reading = 0.0
        self._accumulated_export_reading = 0.0
        self._sensors = {'sim_i': 98.0, 'sim_e': 20.0}
        self.calls = {'read': 0, 'process': 0, 'reset': 0}
        self.next_time = BASE + timedelta(seconds=60)
        self.output = {'import': 8, 'export': 1}
        self.defer = False
        self.fail = False

    @a.audit_tracking
    def tracking(self):
        return 'tracked'

    @a.audit_reading
    def reading(self, event):
        self.calls['read'] += 1
        old, new = event.data['old_state'], event.data['new_state']
        if old is None or new is None or new.state == 'unavailable':
            return
        delta = float(new.state)-float(old.state)
        if event.data['entity_id'].endswith('import'):
            self._accumulated_import_reading += delta
        else:
            self._accumulated_export_reading += delta
        return 'original-read-result'

    @a.audit_processing
    def processing(self):
        self.calls['process'] += 1
        if self.fail:
            raise RuntimeError('original calculation failed')
        if self.defer:
            return 'deferred'
        self._sensors['sim_i'] += self.output['import']
        self._sensors['sim_e'] += self.output['export']
        self._last_battery_update_time = self.next_time.timestamp()
        self._accumulated_import_reading = 0.0
        self._accumulated_export_reading = 0.0
        return 'original-processing-result'

    @a.audit_reset
    def reset(self):
        self.calls['reset'] += 1
        return 'reset'

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(a, 'datetime', Clock)
        self.clock.start()
        self.h = Handle()
        self.assertEqual(self.h.tracking(), 'tracked')
        self.config = json.loads((ROOT / 'config/energy_finance/collector.json').read_text())
        self.config.update(audit={'enabled':True,'battery_id':'test-battery',
                                  'expected_helper_sha256':a.HELPER_SHA256})
        rate = {'quoted_total':'.363','quote_includes_vat':True,'quote_includes_discount':False,
                'delivery_ex_vat':'.20','energy_tax_ex_vat':'.10'}
        self.tariffs = {'netting_ends':'2027-01-01','plans':[{'id':'synthetic', 'valid_from':'2027-01-01',
            'valid_until':'2028-01-01','confirmed':True,'cash_basis_confirmed':True,
            'vat_fraction':'.21','delivery_discount_fraction':'.10',
            'import':{'normal':rate,'offpeak':copy.deepcopy(rate)},
            'export_credit_cash_per_kwh':'.08','export_fee_cash_per_kwh':'.06'}]}

    def tearDown(self):
        self.clock.stop()

    def reading(self, role, value, second):
        entity = self.h._inputs[0 if role == 'import' else 1]['sensor_id']
        old = self.h.states[entity]
        new = state(value, BASE+timedelta(seconds=second))
        self.h.states[entity] = new
        if str(value) != 'unavailable':
            code=self.h.states['sensor.p1_meter_tarief'].state
            register='sensor.p1_meter_energie_'+role+'_tarief_'+code
            try:
                self.h.states[register]=state(float(self.h.states[register].state)+float(value)-float(old.state),BASE+timedelta(seconds=second))
            except ValueError:pass
        return self.h.reading(SimpleNamespace(data={'entity_id':entity,'old_state':old,'new_state':new}))

    def batch(self):
        self.reading('import', 110, 10)
        self.reading('export', 23, 20)
        self.h.processing()
        return self.h.packets[-1]

    def test_exact_consumed_readings_and_atomic_outputs(self):
        batch = self.batch()
        self.assertTrue(batch['valid'])
        self.assertEqual(batch['measured_before'], {'import':'100','export':'20'})
        self.assertEqual(batch['measured_after'], {'import':'110','export':'23'})
        self.assertEqual(batch['simulated_after'], {'import':'106.0','export':'21.0'})
        self.assertEqual(len(batch['accepted_events']), 2)

    def test_original_called_once_and_return_values_unchanged(self):
        self.assertEqual(self.reading('import',110,10), 'original-read-result')
        self.assertEqual(self.h.processing(), 'original-processing-result')
        self.assertEqual(self.h.calls['read'],1)
        self.assertEqual(self.h.calls['process'],1)
        self.assertEqual(self.h._sensors['sim_i'],106)

    def test_delayed_processing_does_not_emit_premature_batch(self):
        self.reading('import',110,10)
        self.h.defer = True
        self.h.processing()
        self.assertEqual(self.h.packets,[])
        self.h.defer = False
        self.h.next_time = BASE+timedelta(seconds=120)
        self.h.processing()
        self.assertEqual(self.h.packets[0]['measured_after']['import'],'110')
        self.assertEqual(self.h.packets[0]['sequence'],1)

    def test_different_update_frequencies(self):
        for i in range(1,6):
            self.reading('import',100+i,i*10)
        self.h.processing()
        self.assertEqual(len(self.h.packets),1)
        self.assertEqual(len(self.h.packets[0]['accepted_events']),5)

    def test_missing_source_event_taints_generation(self):
        self.h.states[self.h._inputs[0]['sensor_id']] = state(105)
        self.reading('import',110,10)
        self.h.processing()
        self.assertFalse(self.h.packets[-1]['valid'])

    def test_unavailable_source_is_not_zero(self):
        self.reading('import','unavailable',10)
        self.h.processing()
        self.assertFalse(self.h.packets[-1]['valid'])

    def test_counter_reset_taints_generation(self):
        self.reading('import',0,10)
        self.h.processing()
        self.assertFalse(self.h.packets[-1]['valid'])

    def test_simulator_reset_does_not_change_original_reset(self):
        self.assertEqual(self.h.reset(),'reset')
        self.assertEqual(self.h.calls['reset'],1)
        self.batch()
        self.assertFalse(self.h.packets[-1]['valid'])

    def test_original_exception_propagates_and_invalidates_audit(self):
        self.h.fail=True
        with self.assertRaisesRegex(RuntimeError,'original calculation failed'):
            self.h.processing()
        self.assertFalse(self.h._stalman_audit.valid)

    def test_generation_changes_on_restart_anchor(self):
        first=self.h._stalman_audit.generation
        self.h.tracking()
        self.assertNotEqual(first,self.h._stalman_audit.generation)

    def test_proof_reaches_financial_kernel(self):
        observation=consume(self.config,[self.batch()])
        result=report(self.tariffs,observation)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['scope'],'window')
        self.assertEqual(result['saving_eur'],'0.64')
        self.assertEqual(result['coverage_kind'],'contiguous_partial_day')

    def test_loss_is_in_grid_deltas_not_applied_again(self):
        # Reference outputs include loss: 3 charged, 2.4843 returned to the home (0.91^2).
        self.h.output={'import':5-2.4843,'export':0}
        self.reading('import',105,10)
        self.reading('export',23,20)
        self.h.processing()
        result=report(self.tariffs,consume(self.config,self.h.packets))
        self.assertEqual(result['saving_eur'],'0.78')

    def test_tariff_change_is_rejected_not_prorated(self):
        batch=self.batch()
        batch['tariff_after']={'code':'2','last_changed':(BASE+timedelta(seconds=15)).isoformat()}
        with self.assertRaisesRegex(InvalidSample,'ambiguous_tariff'):
            consume(self.config,[batch])

    def test_normal_and_offpeak_windows(self):
        tariffs = json.loads((ROOT / 'config/energy_finance/tariffs.json').read_text())
        self.assertEqual(tariffs['p1_tariff_mapping']['codes'], self.config['tariff_mapping'])
        batch=self.batch()
        for code,key in [('1','offpeak'),('2','normal')]:
            with self.subTest(code=code):
                batch['tariff_before']['code']=code
                batch['tariff_after']['code']=code
                if code == '2':
                    for reg_key in ['tariff_registers_before','tariff_registers_after']:
                        for role in ['import','export']:
                            reg=batch[reg_key][role]; reg['1'],reg['2']=reg['2'],reg['1']
                o=consume(self.config,[batch])
                self.assertEqual(o['without']['import_kwh'][key],'10')

    def test_new_day_boundary_blocked(self):
        batch=self.batch()
        batch['processing_end']=(BASE+timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(InvalidSample,'day_boundary'):
            consume(self.config,[batch])

    def test_skipped_batch_and_restart_rejected(self):
        first=self.batch()
        second=copy.deepcopy(first)
        second.update(sequence=3,processing_start=first['processing_end'],processing_end=(BASE+timedelta(seconds=120)).isoformat())
        with self.assertRaisesRegex(InvalidSample,'missing_or_duplicate'):
            consume(self.config,[first,second])
        second['sequence']=2
        second['generation']='new-boot'
        with self.assertRaisesRegex(InvalidSample,'generation_changed'):
            consume(self.config,[first,second])

    def test_before_2027_window_is_not_daily_saldering(self):
        batch=self.batch()
        self.tariffs['netting_ends']='2028-01-01'
        result=report(self.tariffs,consume(self.config,[batch]))
        self.assertEqual(result['status'],'unavailable')
        self.assertIsNone(result['saving_eur'])

    def test_collector_journal_idempotency_and_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            collector=Collector(Path(tmp)/'audit.sqlite',self.config)
            try:
                batch=self.batch()
                collector.ingest_audit(batch)
                self.assertEqual(collector.ingest_audit(batch)['status'],'duplicate_audit')
                result=collector.observations('2027-01-02')
                self.assertTrue(result['coverage_confirmed'])
                changed=copy.deepcopy(batch)
                changed['valid']=False
                with self.assertRaises(InvalidSample):collector.ingest_audit(changed)
                self.assertFalse(collector.observations('2027-01-02')['coverage_confirmed'])
            finally:collector.close()

    def test_delayed_out_of_order_delivery_recovers_without_double_counting(self):
        first=copy.deepcopy(self.batch())
        self.reading('import',111,70)
        self.reading('export',24,80)
        self.h.next_time=BASE+timedelta(seconds=120)
        self.h.output={'import':.8,'export':0}
        self.h.processing()
        second=copy.deepcopy(self.h.packets[-1])
        with tempfile.TemporaryDirectory() as tmp:
            collector=Collector(Path(tmp)/'audit.sqlite',self.config)
            try:
                collector.ingest_audit(second)
                self.assertFalse(collector.observations('2027-01-02')['coverage_confirmed'])
                collector.ingest_audit(first)
                result=collector.observations('2027-01-02')
                self.assertTrue(result['coverage_confirmed'])
                self.assertEqual(result['without']['import_kwh']['offpeak'],'11')
                self.assertEqual(collector.ingest_audit(second)['status'],'duplicate_audit')
            finally:collector.close()

    def test_reset_metadata_change_with_same_counter_is_invalid(self):
        entity=self.h._inputs[0]['sensor_id']
        old=self.h.states[entity]
        new=state(100,BASE+timedelta(seconds=10))
        new.attributes['last_reset']='new-generation'
        self.h.states[entity]=new
        self.h.reading(SimpleNamespace(data={'entity_id':entity,'old_state':old,'new_state':new}))
        self.h.processing()
        self.assertFalse(self.h.packets[-1]['valid'])

    def test_new_window_after_reset_has_new_generation_and_no_bridge(self):
        first_generation=self.h._stalman_audit.generation
        self.h.reset()
        first=self.batch()
        self.assertFalse(first['valid'])
        self.assertNotEqual(first_generation,self.h._stalman_audit.generation)
        self.reading('import',111,70)
        self.h.next_time=BASE+timedelta(seconds=120)
        self.h.output={'import':.8,'export':0}
        self.h.processing()
        second=self.h.packets[-1]
        self.assertEqual(second['sequence'],1)
        self.assertEqual(second['measured_before']['import'],'110')
        self.assertTrue(second['valid'])
        result=consume(self.config,[second])
        self.assertEqual(result['without']['import_kwh']['offpeak'],'1')

    def test_new_window_after_tariff_transition_is_explicit(self):
        self.reading('import',110,10)
        tariff=state('2')
        tariff.last_changed=BASE+timedelta(seconds=30)
        self.h.states['sensor.p1_meter_tarief']=tariff
        self.h.processing()
        first=self.h.packets[-1]
        with self.assertRaises(InvalidSample):consume(self.config,[first])
        self.reading('import',111,70)
        self.h.next_time=BASE+timedelta(seconds=120)
        self.h.output={'import':.8,'export':0}
        self.h.processing()
        # Exact P1 registers, rather than timestamp proximity, identify the normal-tariff input.
        second=self.h.packets[-1]
        self.assertEqual(second['sequence'],1)
        self.assertEqual(consume(self.config,[second])['without']['import_kwh']['normal'],'1')

    def test_register_mismatch_cannot_be_fixed_by_timestamp_nearness(self):
        batch=self.batch()
        batch['tariff_registers_after']['import']['1']='109'
        with self.assertRaisesRegex(InvalidSample,'identify_consumed_end'):
            consume(self.config,[batch])

    def test_mixed_import_registers_block_prorating(self):
        batch=self.batch()
        batch['tariff_registers_after']['import']={'1':'107','2':'3'}
        with self.assertRaisesRegex(InvalidSample,'mixed_tariff'):
            consume(self.config,[batch])

    def test_additional_simulated_grid_charging_is_not_assigned_by_time(self):
        batch=self.batch()
        batch['simulated_after']['import']='109'
        with self.assertRaisesRegex(InvalidSample,'additional_simulated_grid_charging'):
            consume(self.config,[batch])

    def test_new_day_reanchors_without_pricing_cross_midnight_batch(self):
        self.reading('import',111,86410)
        self.h.next_time=BASE+timedelta(days=1,seconds=60)
        self.h.processing()
        with self.assertRaisesRegex(InvalidSample,'day_boundary'):
            consume(self.config,[self.h.packets[-1]])
        self.reading('import',112,86470)
        self.h.output={'import':.8,'export':0}
        self.h.next_time=BASE+timedelta(days=1,seconds=120)
        self.h.processing()
        fresh=self.h.packets[-1]
        self.assertEqual(fresh['sequence'],1)
        result=consume(self.config,[fresh])
        self.assertEqual(result['start'],'2027-01-03')
        self.assertEqual(result['without']['import_kwh']['offpeak'],'1')

    def test_unaudited_solar_cap_input_does_not_get_certificate(self):
        self.h._solar_entity_id='sensor.example_solar_cap'
        self.assertEqual(self.h.tracking(),'tracked')
        self.assertIsNone(self.h._stalman_audit)
        self.reading('import',110,10)
        self.assertEqual(self.h.processing(),'original-processing-result')
        self.assertEqual(self.h.packets,[])

    def test_default_config_does_not_authorize_proposed_producer(self):
        config=json.loads((ROOT/'config/energy_finance/collector.json').read_text())
        with self.assertRaisesRegex(InvalidSample,'not_approved'):
            consume(config,[self.batch()])

    def test_patch_refuses_unknown_source(self):
        with self.assertRaisesRegex(ValueError,'Unsupported source'):
            prep.transform(b'class Different: pass\n')

if __name__=='__main__':unittest.main()
