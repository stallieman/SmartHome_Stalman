import copy
import asyncio
import threading
from unittest.mock import patch
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('audit_producer', ROOT / 'custom_components/battery_sim/audit_producer.py')
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)
sys.path.insert(0, str(ROOT / 'energy_finance'))
from batch_contract import consume, SOURCE_SHA
from collector import InvalidSample

T0 = '2026-11-07T10:00:00+00:00'
T1 = '2026-11-07T10:01:00+00:00'
T2 = '2026-11-07T10:02:00+00:00'


def state(value, reset=None, unit='kWh', restored=False):
    return SimpleNamespace(state=str(value), attributes={'unit_of_measurement': unit, 'last_reset': reset, 'restored': restored},
                           last_updated=datetime.fromisoformat(T0), last_changed=datetime.fromisoformat(T0))


def states(import_total='10', export_total='20'):
    return {'sensor.p1_meter_energie_import': state(import_total), 'sensor.p1_meter_energie_export': state(export_total),
            'sensor.p1_meter_energie_import_tarief_1': state(import_total), 'sensor.p1_meter_energie_import_tarief_2': state(0),
            'sensor.p1_meter_energie_export_tarief_1': state(export_total), 'sensor.p1_meter_energie_export_tarief_2': state(0),
            'sensor.p1_meter_tarief': state(1)}


def diag(start, end, old, new, simold, simnew):
    return {'processing_start': start, 'processing_end': end, 'reasons': [],
            'measured_before': {'import': old, 'export': 20}, 'measured_after': {'import': new, 'export': 20},
            'simulated_before': {'import': simold, 'export': 20}, 'simulated_after': {'import': simnew, 'export': 20},
            'accepted_events': [{'role': 'import', 'entity': producer.SOURCE_ENTITIES['import'], 'old': old, 'new': new,
                                 'old_at': start, 'new_at': end, 'old_reset': None, 'new_reset': None}]}


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.source_path = ROOT / 'custom_components/battery_sim/__init__.py'
        self.p = producer.AuditProducer('battery', self.source_path)
        self.b0 = producer.capture(states(), producer.SOURCE_ENTITIES, T1)
        self.b1 = producer.capture(states('11'), producer.SOURCE_ENTITIES, T2)
        self.p.finish({'reasons': ['missing_baseline']}, self.b0)

    def test_produces_packet_accepted_by_existing_consumer(self):
        packet = self.p.finish(diag(T1, T2, 10, 11, 10, 10.5), self.b1)
        self.assertIsNotNone(packet)
        packet.update(upstream_sha256=producer.digest(self.source_path), helper_sha256=producer.helper_digest())
        config = {'audit': {'enabled': True, 'battery_id': 'battery', 'expected_helper_sha256': producer.helper_digest()},
                  'mapping_confirmed': True, 'tariff_mapping': {'1': 'offpeak', '2': 'normal'},
                  'entities': {'real_import': producer.SOURCE_ENTITIES['import'], 'real_export': producer.SOURCE_ENTITIES['export']}}
        result = consume(config, [packet])
        self.assertTrue(result['paired_grid_deltas_confirmed'])
        self.assertEqual(result['with']['import_kwh']['offpeak'], '0.5')

    def test_config_pins_actual_code_and_rejects_wrong_identity(self):
        config = json.loads((ROOT / 'energy_finance/collector.json').read_text())
        self.assertEqual(SOURCE_SHA, producer.digest(self.source_path))
        self.assertEqual(config['audit']['expected_helper_sha256'], producer.helper_digest())
        packet = self.p.finish(diag(T1, T2, 10, 11, 10, 10.5), self.b1)
        packet['upstream_sha256'] = producer.digest(self.source_path)
        packet['helper_sha256'] = 'wrong'
        config['audit']['battery_id'] = 'battery'
        with self.assertRaises(InvalidSample):
            consume(config, [packet])

    def test_import_rounding_boundary_at_producer_and_consumer(self):
        config = json.loads((ROOT / 'energy_finance/collector.json').read_text())
        config['audit']['battery_id'] = 'battery'
        for extra, accepted in [('0.000000000999', True), ('0.000000001', True),
                                ('0.000000001001', False), ('0.000001', False)]:
            with self.subTest(extra=extra):
                from decimal import Decimal
                candidate = str(Decimal('11') + Decimal(extra))
                p = producer.AuditProducer('battery', self.source_path)
                p.finish({'reasons': ['missing_baseline']}, self.b0)
                packet = p.finish(diag(T1, T2, 10, 11, '10', candidate), self.b1)
                self.assertEqual(packet is not None, accepted)
                # Test consumer independently, including cases the producer rejects.
                baseline = self.p.finish(diag(T1, T2, 10, 11, 10, 10.5), self.b1) if self.p.last_packet is None else copy.deepcopy(self.p.last_packet)
                baseline['simulated_after']['import'] = candidate
                baseline.update(upstream_sha256=producer.digest(self.source_path), helper_sha256=producer.helper_digest())
                if accepted:
                    self.assertTrue(consume(config, [baseline])['paired_grid_deltas_confirmed'])
                else:
                    with self.assertRaisesRegex(InvalidSample, 'additional_simulated_grid_charging'):
                        consume(config, [baseline])

    def test_observed_float_rounding_is_accepted(self):
        end = producer.capture(states('10.006'), producer.SOURCE_ENTITIES, T2)
        packet = self.p.finish(diag(T1, T2, 10, 10.006, '26557.78493643298', '26557.790936432983'), end)
        self.assertIsNotNone(packet)

    def test_boundary_mismatch_rejected(self):
        packet = self.p.finish(diag(T0, T2, 10, 11, 10, 10.5), self.b1)
        self.assertIsNone(packet)

    def test_missing_restored_and_inconsistent_registers_rejected(self):
        for value in (None, state(10, restored=True), state('unknown')):
            s = states()
            s['sensor.p1_meter_energie_export_tarief_1'] = value
            self.assertIsNone(producer.capture(s, producer.SOURCE_ENTITIES, T1))
        s = states(); s['sensor.p1_meter_energie_export_tarief_1'] = state(19)
        self.assertIsNone(producer.capture(s, producer.SOURCE_ENTITIES, T1))
        self.assertIsNone(producer.capture(states(), {'import': 'wrong'}, T1))

    def test_unallocated_extra_and_reset_rejected(self):
        self.assertIsNone(self.p.finish(diag(T1, T2, 10, 11, 10, 12), self.b1))
        self.p.finish({'reasons': ['missing_baseline']}, self.b0)
        bad = diag(T1, T2, 10, 11, 10, 10.5)
        bad['accepted_events'][0]['new_reset'] = 'reset'
        self.assertIsNone(self.p.finish(bad, self.b1))

    def test_discontinuity_and_tariff_transition_rejected(self):
        bad = copy.deepcopy(self.b1); bad['tariff']['code'] = '2'
        self.assertIsNone(self.p.finish(diag(T1, T2, 10, 11, 10, 10.5), bad))
        self.p.finish({'reasons': ['missing_baseline']}, self.b0)
        bad_diag = diag(T1, T2, 10, 11, 10, 10.5)
        bad_diag['accepted_events'][0]['old'] = 9
        self.assertIsNone(self.p.finish(bad_diag, self.b1))

class AsyncPublicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_hashing_runs_in_executor_each_time_and_failure_never_publishes(self):
        events = []
        loop_thread = threading.get_ident()
        threads = []
        class Hass:
            bus = SimpleNamespace(async_fire=lambda name, packet: events.append((name, packet)))
            async def async_add_executor_job(self, func, *args):
                result = []
                def run():
                    try:
                        result.append((True, func(*args)))
                    except Exception as exc:
                        result.append((False, exc))
                worker = threading.Thread(target=run)
                worker.start()
                worker.join()
                if not result[0][0]:
                    raise result[0][1]
                return result[0][1]
        def hash_files(path):
            threads.append(threading.get_ident())
            if len(threads) == 2:
                raise OSError('unreadable code')
            return ('source-hash', 'helper-hash')
        lock = asyncio.Lock()
        with patch.object(producer, 'calculate_digests', hash_files):
            await producer.async_publish_packet(Hass(), lock, 'source', {'sequence': 1})
            with self.assertRaises(OSError):
                await producer.async_publish_packet(Hass(), lock, 'source', {'sequence': 2})
        self.assertEqual(len(threads), 2)
        self.assertTrue(all(t != loop_thread for t in threads))
        self.assertEqual(events, [('battery_sim_stalman_audit_batch', {
            'sequence': 1, 'upstream_sha256': 'source-hash', 'helper_sha256': 'helper-hash'})])


if __name__ == '__main__':
    unittest.main()
