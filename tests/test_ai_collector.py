"""Synthetic read-only collector tests: no credentials, network or installed websocket needed."""
import copy
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ai_ha', ROOT / 'config/ai_analyst/ha.py')
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)
spec = importlib.util.spec_from_file_location('ai_daily_integration', ROOT / 'config/ai_analyst/daily.py')
daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daily)
TZ = ZoneInfo('Europe/Amsterdam')
UTC = dt.timezone.utc


def sensor(alias='energy', kind='total_increasing'):
    return {'id': alias, 'entity_id': 'sensor.local_' + alias,
            'statistic_id': 'sensor.history_' + alias, 'label': 'Lokale meting',
            'unit': 'kWh' if kind == 'total_increasing' else '°C',
            'kind': kind, 'share_with_ai': True}


def bounds(day):
    return tuple(int(dt.datetime.combine(d, dt.time(), TZ).timestamp() * 1000)
                 for d in (day, day + dt.timedelta(days=1)))


class SyntheticClient:
    def __init__(self, sensors, target):
        self.calls = []
        self.failures = {}
        self.metadata = [{'statistic_id': s['statistic_id'], 'unit_of_measurement': s['unit'],
                          'has_sum': s['kind'] == 'total_increasing',
                          'has_mean': s['kind'] == 'measurement'} for s in sensors]
        self.states = [{'entity_id': s['entity_id'], 'state': '123',
                        'attributes': {'unit_of_measurement': s['unit'], 'secret': 'DO_NOT_COPY'}}
                       for s in sensors]
        self.data = {}
        for s in sensors:
            rows = []
            for offset in range(30, -1, -1):
                start, end = bounds(target - dt.timedelta(days=offset))
                for timestamp in range(start, end, ha.HOUR_MS):
                    row = {'start': timestamp, 'end': timestamp + ha.HOUR_MS}
                    row.update({'change': 1.0, 'sum': 987654321.0} if s['kind'] == 'total_increasing'
                               else {'mean': 10.0, 'min': 8.0, 'max': 12.0})
                    rows.append(row)
            self.data[s['statistic_id']] = rows

    def command(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind in self.failures:
            raise self.failures[kind]
        if kind == 'get_states':
            return self.states
        if kind == 'recorder/list_statistic_ids':
            return self.metadata
        if kind == 'recorder/statistics_during_period':
            return {key: self.data[key] for key in kwargs['statistic_ids'] if key in self.data}
        raise AssertionError('Unexpected command')


class ProtocolTests(unittest.TestCase):
    def socket(self, frames, status=101):
        sock = Mock()
        sock.getstatus.return_value = status
        sock.recv.side_effect = [json.dumps(frame) if not isinstance(frame, str) else frame for frame in frames]
        return sock

    def connect(self, sock):
        factory = Mock(return_value=sock)
        return patch.dict(sys.modules, {'websocket': types.SimpleNamespace(create_connection=factory)}), factory

    def assert_safe(self, exception):
        self.assertNotIn('SENSITIVE', str(exception))
        self.assertNotIn('private.example', str(exception))

    def test_handshake_and_read_command(self):
        sock = self.socket([{'type': 'auth_required'}, {'type': 'auth_ok'},
                            {'type': 'result', 'id': 1, 'success': True, 'result': []}])
        context, factory = self.connect(sock)
        with context, ha.HAClient('https://private.example/prefix/', 'SENSITIVE') as client:
            self.assertEqual(client.command('get_states'), [])
        factory.assert_called_once_with('wss://private.example/prefix/api/websocket',
                                        timeout=30, redirect_limit=0, suppress_origin=True)
        self.assertEqual([json.loads(c.args[0]) for c in sock.send.call_args_list],
                         [{'type': 'auth', 'access_token': 'SENSITIVE'}, {'type': 'get_states', 'id': 1}])
        sock.close.assert_called_once()

    def test_lazy_import(self):
        with patch.dict(sys.modules, {'websocket': None}):
            client = ha.HAClient('http://localhost:8123', 'synthetic')
            with self.assertRaises(ha.HAError) as caught:
                client.__enter__()
            self.assertIsInstance(caught.exception, RuntimeError)
            self.assertIn('websocket-client>=1.8,<2', str(caught.exception))
            result = ha.collect({'timezone': 'Europe/Amsterdam', 'sensors': []},
                                SyntheticClient([], dt.date(2026, 1, 1)), dt.date(2026, 1, 1))
            self.assertEqual(result['sensors'], [])

    def test_redirect_never_receives_token(self):
        sock = self.socket([], status=302)
        context, _ = self.connect(sock)
        with context, self.assertRaises(ha.HAError):
            with ha.HAClient('https://private.example', 'SENSITIVE'):
                pass
        sock.send.assert_not_called()
        sock.close.assert_called_once()

    def test_auth_failures_and_malformed_frames_are_sanitized(self):
        scenarios = [[], ['SENSITIVE invalid'], [[]], [{'type': 'auth_ok'}],
                     [{'type': 'auth_required'}, {'type': 'auth_invalid', 'message': 'SENSITIVE'}],
                     [{'type': 'auth_required'}, {'type': 'event', 'message': 'SENSITIVE'}]]
        for frames in scenarios:
            with self.subTest(frames=frames):
                sock = self.socket(frames)
                context, _ = self.connect(sock)
                with context, self.assertRaises(ha.HAError) as caught:
                    ha.HAClient('https://private.example', 'SENSITIVE').__enter__()
                self.assert_safe(caught.exception)
                sock.close.assert_called_once()

    def test_connection_factory_error_never_exposes_provider_message(self):
        factory = Mock(side_effect=RuntimeError('SENSITIVE private.example provider response'))
        with patch.dict(sys.modules, {'websocket': types.SimpleNamespace(create_connection=factory)}):
            with self.assertRaises(ha.HASourceError) as caught:
                ha.HAClient('https://private.example', 'SENSITIVE').__enter__()
        self.assert_safe(caught.exception)

    def test_transport_and_close_failures_are_sanitized(self):
        sock = self.socket([{'type': 'auth_required'}])
        sock.send.side_effect = RuntimeError('SENSITIVE private.example')
        sock.close.side_effect = RuntimeError('SENSITIVE')
        context, _ = self.connect(sock)
        with context, self.assertRaises(ha.HASourceError) as caught:
            ha.HAClient('https://private.example', 'SENSITIVE').__enter__()
        self.assert_safe(caught.exception)

    def test_disallowed_commands_and_payload_overrides_send_nothing(self):
        client = ha.HAClient('http://localhost', 'synthetic')
        client._socket = Mock()
        for command, kwargs in [('call_service', {'domain': 'light'}), ('subscribe_events', {}),
                                ('get_states', {'id': 8}), ('get_states', {'type': 'call_service'}),
                                ('recorder/statistics_during_period', {'period': 'day'}),
                                ('recorder/list_statistic_ids', {'statistic_type': []}),
                                ('recorder/list_statistic_ids', {'statistic_ids': ['sensor.synthetic']})]:
            with self.subTest(command=command, kwargs=kwargs), self.assertRaises(ha.HAError):
                client.command(command, **kwargs)
        client._socket.send.assert_not_called()

    def test_results_must_match_id_type_and_boolean_success(self):
        for response in [{'type': 'event'}, {'type': 'result', 'id': 2, 'success': True},
                         {'type': 'result', 'id': True, 'success': True},
                         {'type': 'result', 'id': 1, 'success': 'yes'},
                         {'type': 'result', 'id': 1, 'success': True}]:
            with self.subTest(response=response):
                client = ha.HAClient('http://localhost', 'synthetic')
                client._socket = self.socket([response])
                with self.assertRaises(ha.HAError):
                    client.command('get_states')

    def test_source_error_does_not_dump_response(self):
        client = ha.HAClient('http://localhost', 'synthetic')
        client._socket = self.socket([{'type': 'result', 'id': 1, 'success': False,
                                      'error': {'message': 'SENSITIVE private.example'}}])
        with self.assertRaises(ha.HASourceError) as caught:
            client.command('get_states')
        self.assert_safe(caught.exception)

    def test_unsafe_urls_and_timeouts_are_rejected(self):
        for url in ['ftp://localhost', 'https://user:password@localhost', 'http://localhost/?token=SENSITIVE',
                    'http://localhost/#secret', 'https://localhost:bad', 'http://',
                    'https://localhost\\@elsewhere', 'http://local host', None]:
            with self.subTest(url=url), self.assertRaises(ha.HAError):
                ha.HAClient(url, 'SENSITIVE')
        for timeout in [True, 0, -1, math.inf, '30']:
            with self.subTest(timeout=timeout), self.assertRaises(ha.HAError):
                ha.HAClient('http://localhost', 'synthetic', timeout=timeout)

    def test_connection_required_and_reentry_rejected(self):
        client = ha.HAClient('http://localhost', 'synthetic')
        with self.assertRaises(ha.HAError):
            client.command('get_states')
        client._socket = Mock()
        with self.assertRaises(ha.HAError):
            client.__enter__()

    def test_valid_statistics_request_and_sequential_ids(self):
        client = ha.HAClient('http://localhost', 'synthetic')
        client._socket = self.socket([{'type': 'result', 'id': i, 'success': True, 'result': {}}
                                      for i in (1, 2)])
        kwargs = {'start_time': '2026-01-01T00:00:00Z', 'end_time': '2026-01-02T00:00:00Z',
                  'statistic_ids': ['sensor.synthetic'], 'period': 'hour', 'types': ['change']}
        client.command('recorder/statistics_during_period', **kwargs)
        client.command('recorder/list_statistic_ids')
        self.assertEqual([json.loads(c.args[0]) for c in client._socket.send.call_args_list],
                         [{'id': 1, 'type': 'recorder/statistics_during_period', **kwargs},
                          {'id': 2, 'type': 'recorder/list_statistic_ids'}])
        for field, value in [('start_time', '2026-01-01'), ('end_time', '2025-01-01T00:00:00Z'),
                             ('types', ['sum']), ('types', [[]]), ('statistic_ids', []), ('period', 'day')]:
            with self.subTest(field=field, value=value), self.assertRaises(ha.HAError):
                client.command('recorder/statistics_during_period', **{**kwargs, field: value})


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.target = dt.date(2026, 2, 15)
        self.sensors = [sensor()]
        self.reset_client()

    def reset_client(self):
        self.config = {'timezone': 'Europe/Amsterdam', 'sensors': self.sensors}
        self.client = SyntheticClient(self.sensors, self.target)
        self.rows = self.client.data[self.sensors[0]['statistic_id']]

    def report(self):
        result = ha.collect(self.config, self.client, self.target)
        json.dumps(result, allow_nan=False)
        return result

    def item(self):
        return self.report()['sensors'][0]

    def test_complete_counter_uses_changes_not_lifetime_sum(self):
        item = self.item()
        self.assertEqual(item['value'], 24.0)
        self.assertIs(type(item['value']), float)
        self.assertEqual(item['quality']['status'], 'ok')
        self.assertEqual(item['quality']['valid_hours'], 24)
        self.assertEqual(item['comparison_7d']['mean'], 24.0)
        self.assertEqual(item['comparison_30d']['complete_days'], 30)
        self.assertEqual(item['comparison_30d']['change_pct'], 0.0)
        self.assertFalse(item['anomaly']['is_anomaly'])

    def test_request_covers_31_calendar_days_using_utc(self):
        report = self.report()
        kind, kwargs = self.client.calls[-1]
        self.assertEqual(kind, 'recorder/statistics_during_period')
        self.assertEqual(kwargs, {'start_time': '2026-01-15T23:00:00Z',
                                 'end_time': '2026-02-15T23:00:00Z', 'statistic_ids': ['sensor.history_energy'],
                                 'period': 'hour', 'types': ['change']})
        self.assertEqual(report['period'], {'start': '2026-02-14T23:00:00Z', 'end': '2026-02-15T23:00:00Z'})

    def test_dst_days_have_23_or_25_distinct_utc_buckets(self):
        for target, hours in [(dt.date(2026, 3, 29), 23), (dt.date(2026, 10, 25), 25)]:
            with self.subTest(target=target):
                self.target = target
                self.reset_client()
                item = self.item()
                self.assertEqual(item['value'], float(hours))
                self.assertEqual(item['quality']['expected_hours'], hours)
                self.assertEqual(item['quality']['valid_hours'], hours)

    def test_dst_baseline_uses_calendar_days_not_24h_windows(self):
        for target, total in [(dt.date(2026, 3, 30), 167), (dt.date(2026, 10, 26), 169)]:
            with self.subTest(target=target):
                self.target = target
                self.reset_client()
                self.assertAlmostEqual(self.item()['comparison_7d']['mean'], total / 7)

    def test_zero_is_complete_but_missing_is_not_zero(self):
        for row in self.rows:
            row['change'] = 0
        item = self.item()
        self.assertEqual(item['value'], 0.0)
        self.assertEqual(item['quality']['status'], 'ok')
        self.assertIsNone(item['comparison_7d']['change_pct'])
        self.rows.pop()
        item = self.item()
        self.assertIsNone(item['value'])
        self.assertEqual(item['quality']['valid_hours'], 23)
        self.assertEqual(item['comparison_7d']['complete_days'], 7)

    def test_invalid_numbers_and_negative_resets_are_rejected(self):
        for value in [None, True, False, float('nan'), float('inf'), -float('inf'), '1.0', -0.1, 10 ** 400]:
            with self.subTest(value=repr(value)):
                self.reset_client()
                self.rows[-1]['change'] = value
                item = self.item()
                self.assertIsNone(item['value'])
                self.assertEqual(item['quality']['valid_hours'], 23)
                self.assertNotEqual(item['quality']['status'], 'ok')

    def test_duplicate_invalidates_bucket_not_doubled_or_overwritten(self):
        self.rows.append(copy.deepcopy(self.rows[-1]))
        self.rows.append(copy.deepcopy(self.rows[-1]))
        item = self.item()
        self.assertIsNone(item['value'])
        self.assertEqual(item['quality']['valid_hours'], 23)
        self.assertEqual(item['quality']['counts']['duplicate_bucket'], 2)

    def test_invalid_end_and_unaligned_or_outside_timestamps(self):
        cases = [('end', self.rows[-1]['end'] - 1), ('start', self.rows[-1]['start'] + 1),
                 ('start', self.rows[0]['start'] - ha.HOUR_MS), ('start', True),
                 ('start', '2026-02-15T10:00:00Z'), ('end', None)]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                self.reset_client()
                self.rows[-1][key] = value
                self.assertIsNone(self.item()['value'])

    def test_metadata_units_capabilities_and_missing_metadata(self):
        for change, expected in [({'unit_of_measurement': 'Wh'}, 'metadata_wrong_unit'),
                                 ({'has_sum': False}, 'unsupported_statistics'),
                                 ({'has_sum': 1}, 'unsupported_statistics')]:
            with self.subTest(change=change):
                self.reset_client()
                self.client.metadata[0].update(change)
                item = self.item()
                self.assertEqual(item['quality']['reason'], expected)
                self.assertEqual(item['quality']['status'], 'unavailable')
                self.assertIsNone(item['value'])
        self.client.metadata = []
        self.assertEqual(self.item()['quality']['reason'], 'metadata_missing')

    def test_duplicate_metadata_is_unavailable(self):
        self.client.metadata *= 2
        self.assertEqual(self.item()['quality']['reason'], 'duplicate_metadata')

    def test_current_and_bucket_wrong_units(self):
        self.client.states[0]['attributes']['unit_of_measurement'] = 'Wh'
        self.assertEqual(self.item()['quality']['reason'], 'current_wrong_unit')
        self.reset_client()
        self.rows[-1]['unit_of_measurement'] = 'Wh'
        item = self.item()
        self.assertIsNone(item['value'])
        self.assertIn('wrong_unit', item['quality']['reason'])

    def test_unavailable_current_does_not_block_valid_history(self):
        for state in ['unknown', 'unavailable', None]:
            with self.subTest(state=state):
                self.client.states[0].update(state=state, attributes={'unit_of_measurement': 'stale-unit'})
                item = self.item()
                self.assertEqual(item['value'], 24.0)
                self.assertEqual(item['quality']['current_status'], 'unavailable')
        self.client.states = []
        self.assertEqual(self.item()['value'], 24.0)
        self.assertEqual(self.item()['quality']['current_status'], 'missing')

    def test_current_source_error_preserves_history_and_historical_error_does_not_fallback(self):
        self.client.failures['get_states'] = RuntimeError('SENSITIVE provider response')
        item = self.item()
        self.assertEqual(item['value'], 24.0)
        self.assertEqual(item['quality']['current_status'], 'source_error')
        self.client.failures['recorder/statistics_during_period'] = ha.HASourceError('SENSITIVE')
        item = self.item()
        self.assertIsNone(item['value'])
        self.assertEqual(item['quality']['reason'], 'statistics_source_error')
        self.assertNotIn('SENSITIVE', json.dumps(item))

    def test_metadata_source_error_is_per_sensor(self):
        self.client.failures['recorder/list_statistic_ids'] = RuntimeError('SENSITIVE')
        self.assertEqual(self.item()['quality']['reason'], 'metadata_source_error')

    def test_protocol_errors_abort_instead_of_becoming_source_errors(self):
        self.client.failures['get_states'] = ha.HAError('Protocol failure')
        with self.assertRaises(ha.HAError):
            self.report()
        self.client.failures.clear()
        self.client.metadata = {'unexpected': 'shape'}
        with self.assertRaises(ha.HAError):
            self.report()

    def test_baselines_exclude_target_and_require_all_days(self):
        for row in self.rows[-24:]:
            row['change'] = 3
        item = self.item()
        for count in (7, 30):
            comparison = item[f'comparison_{count}d']
            self.assertEqual(comparison['complete_days'], count)
            self.assertEqual(comparison['mean'], 24.0)
            self.assertEqual(comparison['median'], 24.0)
            self.assertEqual(comparison['change_pct'], 200.0)
        self.assertTrue(item['anomaly']['is_anomaly'])
        del self.rows[-25]
        item = self.item()
        for count in (7, 30):
            comparison = item[f'comparison_{count}d']
            self.assertEqual(comparison['complete_days'], count - 1)
            self.assertIsNone(comparison['mean'])
            self.assertIsNone(comparison['median'])
            self.assertIsNone(comparison['change_pct'])
            self.assertEqual(comparison['reason'], 'incomplete_baseline')
        self.assertIsNone(item['anomaly']['is_anomaly'])

    def test_comparison_median_is_distinct_from_mean_and_zero_baseline_has_no_percentage(self):
        for row in self.rows:
            row['change'] = 0
        for row in self.rows[-48:-24]:
            row['change'] = 7
        item = self.item()
        self.assertEqual(item['comparison_7d']['mean'], 24.0)
        self.assertEqual(item['comparison_7d']['median'], 0.0)
        self.assertEqual(item['comparison_7d']['change_pct'], -100.0)
        for row in self.rows:
            row['change'] = 0 if row['start'] < bounds(self.target)[0] else 1
        item = self.item()
        self.assertEqual(item['value'], 24.0)
        self.assertIsNone(item['comparison_7d']['change_pct'])

    def test_old_baseline_gap_only_blocks_30_days(self):
        self.rows.pop(0)
        item = self.item()
        self.assertEqual(item['comparison_7d']['complete_days'], 7)
        self.assertEqual(item['comparison_30d']['complete_days'], 29)
        self.assertIsNone(item['comparison_30d']['mean'])
        self.assertEqual(item['value'], 24.0)

    def test_measurement_hour_weighted_mean_and_extrema(self):
        self.sensors = [sensor('temperature', 'measurement')]
        self.target = dt.date(2026, 10, 25)
        self.reset_client()
        self.rows[-1].update(mean=35.0, min=30.0, max=40.0)
        item = self.item()
        self.assertEqual(item['value'], 11.0)
        self.assertEqual(item['min'], 8.0)
        self.assertEqual(item['max'], 40.0)
        self.assertEqual(item['quality']['expected_hours'], 25)
        self.assertEqual(self.client.calls[-1][1]['types'], ['mean', 'min', 'max'])
        self.rows[-1]['mean'] = 50
        self.assertIsNone(self.item()['value'])

    def test_measurement_requires_all_three_finite_fields_and_capability(self):
        self.sensors = [sensor('temperature', 'measurement')]
        for field in ['mean', 'min', 'max']:
            for value in [None, True, math.nan, math.inf, '3']:
                with self.subTest(field=field, value=value):
                    self.reset_client()
                    self.rows[-1][field] = value
                    self.assertIsNone(self.item()['value'])
        self.reset_client()
        self.client.metadata[0]['has_mean'] = False
        self.assertEqual(self.item()['quality']['reason'], 'unsupported_statistics')

    def test_mixed_kinds_and_failure_isolation(self):
        self.sensors = [sensor(), sensor('temperature', 'measurement')]
        self.reset_client()
        self.rows.pop()
        report = self.report()
        self.assertIsNone(report['sensors'][0]['value'])
        self.assertEqual(report['sensors'][1]['value'], 10.0)
        requests = [kwargs for kind, kwargs in self.client.calls if kind == 'recorder/statistics_during_period']
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]['types'], ['change'])
        self.assertEqual(requests[1]['types'], ['mean', 'min', 'max'])

    def test_historical_source_error_only_affects_requested_kind(self):
        self.sensors = [sensor(), sensor('temperature', 'measurement')]
        self.reset_client()
        original = self.client.command

        def command(kind, **kwargs):
            if kind == 'recorder/statistics_during_period' and kwargs['types'] == ['change']:
                raise ha.HASourceError('SENSITIVE')
            return original(kind, **kwargs)

        self.client.command = command
        items = self.report()['sensors']
        self.assertEqual(items[0]['quality']['reason'], 'statistics_source_error')
        self.assertEqual(items[1]['value'], 10.0)

    def test_missing_id_and_malformed_rows_are_per_sensor(self):
        for value in [[], None, {}, [{'not': 'a bucket'}]]:
            with self.subTest(value=value):
                self.client.data[self.sensors[0]['statistic_id']] = value
                item = self.item()
                self.assertIsNone(item['value'])
                self.assertEqual(item['quality']['valid_hours'], 0)
        del self.client.data[self.sensors[0]['statistic_id']]
        self.assertIsNone(self.item()['value'])

    def test_no_raw_attributes_entity_ids_or_secrets_and_config_is_unchanged(self):
        before = copy.deepcopy(self.config)
        self.sensors[0]['share_with_ai'] = False
        before['sensors'][0]['share_with_ai'] = False
        report = self.report()
        raw = json.dumps(report)
        for forbidden in ['DO_NOT_COPY', 'sensor.local_', 'sensor.history_', 'attributes', 'access_token']:
            self.assertNotIn(forbidden, raw)
        self.assertEqual(self.config, before)
        self.assertFalse(report['sensors'][0]['share_with_ai'])
        self.assertTrue(any('bewijzen geen' in text for text in report['limitations']))

    def test_current_missing_unit_is_explicit_without_inventing_historical_gap(self):
        self.client.states[0]['attributes'] = {}
        item = self.item()
        self.assertEqual(item['quality']['current_status'], 'unit_missing')
        self.assertEqual(item['value'], 24.0)

    def test_numerical_overflow_is_json_safe(self):
        for row in self.rows:
            row['change'] = 1e308
        self.assertIsNone(self.item()['value'])
        self.sensors = [sensor('temperature', 'measurement')]
        self.reset_client()
        for row in self.rows:
            row.update(mean=1e308, min=1e308, max=1e308)
        item = self.item()
        self.assertTrue(math.isfinite(item['comparison_30d']['median']))
        self.assertTrue(math.isfinite(item['value']))

    def test_sharing_flag_requires_explicit_boolean(self):
        for value in [None, 0, 1, 'false', 'true']:
            with self.subTest(value=value):
                self.sensors[0]['share_with_ai'] = value
                with self.assertRaises(ha.HAError):
                    self.report()
        del self.sensors[0]['share_with_ai']
        with self.assertRaises(ha.HAError):
            self.report()
        for value in (True, False):
            self.sensors[0]['share_with_ai'] = value
            self.assertIs(self.item()['share_with_ai'], value)

    def test_error_classes_are_runtime_errors_for_pipeline_fallback(self):
        self.assertTrue(issubclass(ha.HAError, RuntimeError))
        self.assertTrue(issubclass(ha.HASourceError, ha.HAError))
        self.assertTrue(issubclass(ha.HASourceError, RuntimeError))

    def test_invalid_config_is_sanitized(self):
        for field, value in [('timezone', 'SENSITIVE'), ('sensors', None)]:
            with self.subTest(field=field), self.assertRaises(ha.HAError) as caught:
                ha.collect({**self.config, field: value}, self.client, self.target)
            self.assertNotIn('SENSITIVE', str(caught.exception))
        self.sensors[0]['kind'] = 'service'
        with self.assertRaises(ha.HAError):
            self.report()
        with self.assertRaises(ha.HAError):
            ha.collect(self.config, self.client, dt.datetime(2026, 1, 1))


class IntegrationHAClient(SyntheticClient):
    """Only the HA transport is fake; collection and orchestration remain real."""

    def __enter__(self):
        self.opened = True
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False


class DailyCollectorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'config/ai_analyst/config.example.json').read_text())
        self.config['sensors'] = self.config['sensors'][:1]
        # Production defaults remain private; this synthetic fixture opts in explicitly.
        self.config['sensors'][0].update(share_with_ai=True, share_with_telegram=True)
        self.target = dt.date(2026, 2, 15)
        self.directory = ROOT / ('.ai-collector-integration-' + uuid.uuid4().hex)
        self.directory.mkdir(mode=0o700)
        self.addCleanup(shutil.rmtree, self.directory)
        self.env = patch.dict(os.environ, {
            'HA_TOKEN': 'synthetic-ha-token', 'OPENAI_API_KEY': 'synthetic-openai-key',
            'TELEGRAM_BOT_TOKEN': '123456:synthetic', 'TELEGRAM_CHAT_ID': '-12345'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.finding = 'above_7d'
        self.ai = Mock(side_effect=self.ai_response)
        self.telegram = Mock(return_value={'ok': True, 'result': {'message_id': 123}})
        self.make_client()

    def make_client(self):
        self.client = IntegrationHAClient(self.config['sensors'], self.target)
        self.factory = Mock(return_value=self.client)
        self.rows = self.client.data[self.config['sensors'][0]['statistic_id']]

    def ai_response(self, url, payload, headers):
        self.assertEqual(url, 'https://api.openai.com/v1/chat/completions')
        self.assertEqual(headers, {'Authorization': 'Bearer synthetic-openai-key'})
        shared = json.loads(payload['messages'][1]['content'])
        self.assertEqual(shared['date'], self.target.isoformat())
        self.assertIn(self.finding, shared['sensors'][0]['allowed_patterns'])
        suggestion = 'check_coverage' if self.finding == 'insufficient_data' else 'monitor'
        findings = [{'sensor_id': self.config['sensors'][0]['id'],
                     'pattern': self.finding, 'suggestion': suggestion}]
        return {'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'findings': findings})}}],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 100}}

    def run_report(self):
        now = dt.datetime.combine(self.target + dt.timedelta(days=1), dt.time(6, 15), TZ)
        status = daily.run(self.config, self.directory, self.target, now,
                           client_factory=self.factory, collector=ha.collect,
                           ai_transport=self.ai, telegram_transport=self.telegram)
        self.assertIn('bevestigd', status)
        self.factory.assert_called_once_with(self.config['ha_url'], 'synthetic-ha-token')
        self.assertTrue(self.client.opened)
        self.assertTrue(self.client.closed)
        summary = json.loads((self.directory / f'summary-{self.target.isoformat()}.json').read_text())
        self.telegram.assert_called_once()
        telegram_url, telegram_payload = self.telegram.call_args.args
        self.assertEqual(telegram_url, 'https://api.telegram.org/bot123456:synthetic/sendMessage')
        self.assertEqual(telegram_payload['chat_id'], '-12345')
        self.assertNotIn('parse_mode', telegram_payload)
        text = telegram_payload['text']
        for private in ('synthetic-ha-token', 'synthetic-openai-key', 'sensor.', 'DO_NOT_COPY'):
            self.assertNotIn(private, text)
        self.assertIn('geen bewijs van continue sensorwerking', text)
        return summary['sensors'][0], text

    def test_complete_day_real_collector_comparisons_render_and_reach_ai(self):
        for row in self.rows[-24:]:
            row['change'] = 2
        item, text = self.run_report()
        self.assertEqual(item['value'], 48.0)
        self.assertEqual(item['quality']['status'], 'ok')
        for days in (7, 30):
            comparison = item[f'comparison_{days}d']
            self.assertEqual(comparison['complete_days'], days)
            self.assertEqual(comparison['mean'], 24.0)
            self.assertEqual(comparison['median'], 24.0)
            self.assertEqual(comparison['change_pct'], 100.0)
            self.assertIn(f'Vorige {days} dagen gemiddeld: 24; verschil 100%', text)
        self.assertIn('Netafname: 48 kWh', text)
        self.assertIn('hoger dan het gemiddelde van de voorgaande zeven dagen', text)
        self.ai.assert_called_once()
        shared = json.loads(self.ai.call_args.args[1]['messages'][1]['content'])
        shared_item = shared['sensors'][0]
        self.assertEqual(shared_item['value'], 48.0)
        self.assertEqual(shared_item['quality']['valid_hours'], 24)
        self.assertEqual(shared_item['comparison_7d']['change_pct'], 100.0)
        self.assertEqual(shared_item['comparison_30d']['change_pct'], 100.0)
        raw = json.dumps(shared)
        for private in ('entity_id', 'statistic_id', 'attributes', 'sensor.', 'DO_NOT_COPY'):
            self.assertNotIn(private, raw)
        state = json.loads((self.directory / 'state.json').read_text())
        self.assertEqual(state['reports'][self.target.isoformat()]['telegram'], 'sent')
        self.assertEqual(state['ai_days']['2026-02-16']['status'], 'success')

    def assert_dst_day(self, target, hours, percentage):
        self.target = target
        self.make_client()
        self.finding = 'stable_7d'
        item, text = self.run_report()
        self.assertEqual(item['value'], float(hours))
        self.assertEqual(item['quality']['expected_hours'], hours)
        self.assertEqual(item['quality']['valid_hours'], hours)
        self.assertIn(f'Netafname: {hours} kWh', text)
        for days in (7, 30):
            self.assertIn(f'Vorige {days} dagen gemiddeld: 24; verschil {percentage}%', text)
            self.assertEqual(item[f'comparison_{days}d']['complete_days'], days)
        self.ai.assert_called_once()
        shared = json.loads(self.ai.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(shared['sensors'][0]['quality']['expected_hours'], hours)
        self.assertEqual(shared['sensors'][0]['value'], float(hours))
        summary = json.loads((self.directory / f'summary-{self.target.isoformat()}.json').read_text())
        start = dt.datetime.fromisoformat(summary['period']['start'])
        end = dt.datetime.fromisoformat(summary['period']['end'])
        self.assertEqual((end - start).total_seconds(), hours * 3600)

    def test_spring_dst_23_hours_survives_real_pipeline(self):
        self.assert_dst_day(dt.date(2026, 3, 29), 23, '-4,167')

    def test_autumn_dst_25_hours_survives_real_pipeline(self):
        self.assert_dst_day(dt.date(2026, 10, 25), 25, '4,167')

    def test_incomplete_target_does_not_render_partial_sum_or_delta(self):
        self.rows.pop()
        item, text = self.run_report()
        self.assertIsNone(item['value'])
        self.assertEqual(item['quality']['status'], 'incomplete')
        self.assertEqual(item['quality']['valid_hours'], 23)
        self.assertIn('Netafname: niet beschikbaar kWh', text)
        self.assertIn('Onvoldoende geldige statistiekdekking; geen conclusie.', text)
        for days in (7, 30):
            self.assertEqual(item[f'comparison_{days}d']['complete_days'], days)
            self.assertIsNone(item[f'comparison_{days}d']['change_pct'])
            # Historical means are known, but no target delta can be inferred.
            self.assertIn(f'Vorige {days} dagen gemiddeld: 24; geen procentvergelijking', text)
        for fabricated in ('Netafname: 23', 'Netafname: 0', 'verschil ', '%'):
            self.assertNotIn(fabricated, text)
        self.ai.assert_not_called()

    def test_incomplete_baseline_does_not_render_fictitious_comparisons(self):
        for row in self.rows[-24:]:
            row['change'] = 2
        del self.rows[-25]
        self.finding = 'insufficient_data'
        item, text = self.run_report()
        self.assertEqual(item['value'], 48.0)
        self.assertIn('Netafname: 48 kWh', text)
        for days in (7, 30):
            comparison = item[f'comparison_{days}d']
            self.assertEqual(comparison['complete_days'], days - 1)
            self.assertIsNone(comparison['mean'])
            self.assertIsNone(comparison['change_pct'])
            self.assertIn(f'Vorige {days} dagen: onvoldoende dekking ({days - 1}/{days} volledig).', text)
        self.assertNotIn('gemiddeld:', text)
        self.assertNotIn('%', text)
        self.assertIn('Controleer beschikbaarheid en statistiekdekking', text)
        self.ai.assert_called_once()
        shared = json.loads(self.ai.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(shared['sensors'][0]['allowed_patterns'], ['insufficient_data'])

    def test_historical_source_failure_renders_unavailable_not_zero(self):
        self.client.failures['recorder/statistics_during_period'] = ha.HASourceError('synthetic source failure')
        item, text = self.run_report()
        self.assertIsNone(item['value'])
        self.assertEqual(item['quality']['status'], 'unavailable')
        self.assertEqual(item['quality']['reason'], 'statistics_source_error')
        self.assertIn('Netafname: niet beschikbaar kWh', text)
        for days in (7, 30):
            self.assertEqual(item[f'comparison_{days}d']['complete_days'], 0)
            self.assertIsNone(item[f'comparison_{days}d']['mean'])
            self.assertIsNone(item[f'comparison_{days}d']['change_pct'])
            self.assertIn(f'Vorige {days} dagen: onvoldoende dekking (0/{days} volledig).', text)
        for fabricated in ('Netafname: 0', 'gemiddeld:', 'verschil ', '%', 'synthetic source failure'):
            self.assertNotIn(fabricated, text)
        self.ai.assert_not_called()


if __name__ == '__main__':
    unittest.main()
