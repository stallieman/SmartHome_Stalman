"""Synthetic fixtures and mocked transports only; never contact HA/OpenAI/Telegram."""
import copy
from datetime import date, datetime
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ai_daily', ROOT / 'config/ai_analyst/daily.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def config():
    value = json.loads((ROOT / 'config/ai_analyst/config.example.json').read_text())
    value['sensors'] = value['sensors'][:1]
    value['sensors'][0].update(share_with_ai=True, share_with_telegram=True)
    return value


def summary():
    return {'schema_version': 1, 'date': '2026-10-30', 'timezone': 'Europe/Amsterdam', 'sensors': [{
        'id': 'grid_import', 'label': 'Netafname', 'unit': 'kWh', 'kind': 'total_increasing',
        'value': 12.0, 'quality': {'status': 'ok', 'expected_hours': 24, 'valid_hours': 24},
        'comparison_7d': {'complete_days': 7, 'mean': 8.0, 'median': 8.0, 'change_pct': 50.0},
        'comparison_30d': {'complete_days': 30, 'mean': 10.0, 'median': 10.0, 'change_pct': 20.0}}]}


def ai_response(findings=None, usage=True):
    findings = findings if findings is not None else [{
        'sensor_id': 'grid_import', 'pattern': 'above_7d', 'suggestion': 'check_schedule'}]
    result = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'findings': findings})}}]}
    if usage:
        result['usage'] = {'prompt_tokens': 1000, 'completion_tokens': 100}
    return result


class ConfigurationTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(value))
            return d.load_config(path)

    def test_example_requires_explicit_sharing(self):
        cfg = d.load_config(ROOT / 'config/ai_analyst/config.example.json')
        self.assertFalse(any(s['share_with_ai'] or s['share_with_telegram'] for s in cfg['sensors']))

    def test_valid_configuration(self):
        self.assertEqual(self.load(config())['timezone'], 'Europe/Amsterdam')

    def test_missing_and_invalid_json(self):
        with self.assertRaises(d.ConfigError):
            d.load_config('/not/a/real/config.json')

    def test_invalid_configurations(self):
        cases = []
        for key, value in [('timezone', 'UTC'), ('ha_url', 'https://user:secret@ha.local'),
                           ('ha_url', 'http://ha.local/path'), ('ha_url', 'http://ha.local/?secret=x'),
                           ('ha_url', 'http://ha.local:wrong'), ('ha_url', None), ('api_key', 'not-real')]:
            cfg = config()
            cfg[key] = value
            cases.append(cfg)
        for key, value in [('model', 'other-model'), ('monthly_budget_usd', '.51'),
                           ('monthly_budget_usd', 'NaN'), ('max_input_tokens', True), ('max_output_tokens', 5000)]:
            cfg = config()
            cfg['ai'][key] = value
            cases.append(cfg)
        for key, value in [('share_with_ai', 'true'), ('share_with_telegram', None),
                           ('unit', 'EUR'), ('entity_id', 'sensor.marstek_test'),
                           ('entity_id', 'light.kitchen'), ('label', 'a\nb'), ('kind', 'arbitrary')]:
            cfg = config()
            cfg['sensors'][0][key] = value
            cases.append(cfg)
        cfg = config()
        cfg['sensors'].append(copy.deepcopy(cfg['sensors'][0]))
        cases.append(cfg)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(d.ConfigError):
                self.load(value)


class PrivacyTests(unittest.TestCase):
    def test_projection_uses_explicit_consent_and_drops_attributes(self):
        cfg, data = config(), summary()
        data['sensors'][0]['attributes'] = {'token': 'never-send'}
        data['sensors'][0]['entity_id'] = 'sensor.private_entity'
        private = copy.deepcopy(data['sensors'][0])
        private['id'] = 'private'
        private['label'] = 'private room'
        data['sensors'].append(private)
        output = json.dumps(d.external_summary(data, cfg))
        for unwanted in ('private', 'never-send', 'attributes', 'entity_id'):
            self.assertNotIn(unwanted, output)
        cfg['sensors'][0]['share_with_ai'] = False
        self.assertEqual(d.external_summary(data, cfg)['sensors'], [])

    def test_telegram_has_separate_consent(self):
        cfg, data = config(), summary()
        cfg['sensors'][0]['share_with_telegram'] = False
        findings = [{'sensor_id': 'grid_import', 'pattern': 'above_7d', 'suggestion': 'monitor'}]
        text = d.render_report(data, cfg, findings, 'test')
        self.assertNotIn('Netafname', text)
        self.assertNotIn('12', text)

    def test_unsupported_ai_conclusion_is_rejected(self):
        shared = d.external_summary(summary(), config())
        for findings in ([{'sensor_id': 'private', 'pattern': 'above_7d', 'suggestion': 'monitor'}],
                         [{'sensor_id': 'grid_import', 'pattern': 'below_7d', 'suggestion': 'monitor'}],
                         [{'sensor_id': 'grid_import', 'pattern': 'above_7d', 'suggestion': 'turn_off'}],
                         [{'sensor_id': 'grid_import', 'pattern': 'above_7d', 'suggestion': 'check_coverage'}],
                         [{'sensor_id': [], 'pattern': 'above_7d', 'suggestion': 'monitor'}]):
            with self.subTest(findings=findings), self.assertRaises(ValueError):
                d.validate_findings({'findings': findings}, shared)

    def test_zero_baseline_does_not_invent_percentage(self):
        data = summary()['sensors'][0]
        data['comparison_7d']['mean'] = 0
        self.assertIn('above_7d', d.candidates_for(data))

    def test_missing_or_incomplete_does_not_make_patterns(self):
        sensor = summary()['sensors'][0]
        sensor['quality']['status'] = 'incomplete'
        self.assertEqual(d.candidates_for(sensor), ['insufficient_data'])
        sensor['quality']['status'] = 'ok'
        sensor['comparison_7d']['complete_days'] = 6
        sensor['comparison_30d']['complete_days'] = 29
        self.assertEqual(d.candidates_for(sensor), ['insufficient_data'])

    def test_render_is_plain_text_and_utf16_bounded(self):
        text = d.clipped('😀' * 5000)
        self.assertLessEqual(len(text.encode('utf-16-le')) // 2, 3900)
        cfg = config()
        findings = [{'sensor_id': 'grid_import', 'pattern': 'above_7d', 'suggestion': 'monitor'}]
        text = d.render_report(summary(), cfg, findings, 'reason')
        self.assertIn('50%', text)
        self.assertIn('geen oorzaak', text)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.data = summary()
        self.state = {'version': 1, 'ai_days': {}, 'reports': {}}
        self.day = date(2026, 10, 31)
        self.save = Mock()
        self.transport = Mock(return_value=ai_response())
        self.env = patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-openai-key'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def call(self):
        return d.analyse(self.data, self.cfg, self.state, self.save, self.day, self.transport)

    def test_reserves_before_request_and_records_usage(self):
        def transport(*args):
            self.assertEqual(self.state['ai_days']['2026-10-31']['status'], 'reserved')
            self.assertTrue(self.save.called)
            self.assertEqual(args[1]['model'], 'gpt-4.1-mini')
            self.assertFalse(args[1]['store'])
            self.assertEqual(args[1]['max_completion_tokens'], 600)
            self.assertNotIn('tools', args[1])
            return ai_response()
        self.transport.side_effect = transport
        findings, _ = self.call()
        self.assertEqual(len(findings), 1)
        entry = self.state['ai_days']['2026-10-31']
        self.assertEqual(entry['status'], 'success')
        self.assertEqual(Decimal(entry['cost_usd']), Decimal('0.00056'))
        self.assertEqual(entry['usage']['prompt_tokens'], 1000)

    def test_success_cache_reuses_without_new_cost(self):
        self.call()
        self.call()
        self.transport.assert_called_once()

    def test_only_one_attempt_per_execution_calendar_day(self):
        self.call()
        self.data['date'] = '2026-10-29'
        self.assertEqual(self.call()[0], [])
        self.transport.assert_called_once()

    def test_timeout_keeps_reservation_and_does_not_retry(self):
        self.transport.side_effect = d.DeliveryError('synthetic timeout')
        self.assertEqual(self.call()[0], [])
        cost = self.state['ai_days']['2026-10-31']['cost_usd']
        self.assertGreater(Decimal(cost), 0)
        self.call()
        self.transport.assert_called_once()

    def test_crash_reservation_blocks_retry(self):
        self.state['ai_days']['2026-10-31'] = {'status': 'reserved', 'cost_usd': '.002'}
        self.call()
        self.transport.assert_not_called()

    def test_no_usage_retains_full_reservation(self):
        self.transport.return_value = ai_response(usage=False)
        self.call()
        entry = self.state['ai_days']['2026-10-31']
        self.assertEqual(entry['cost_usd'], entry['reserved_usd'])

    def test_budget_blocks_before_call_and_rolls_by_amsterdam_month(self):
        self.state['ai_days']['2026-10-01'] = {'status': 'failed', 'cost_usd': '.49999'}
        self.assertIn('maandbudget', self.call()[1])
        self.transport.assert_not_called()
        self.day = date(2026, 11, 1)
        self.call()
        self.transport.assert_called_once()

    def test_token_limit_blocks_before_call(self):
        self.cfg['ai']['max_input_tokens'] = 128
        self.assertIn('tokenlimiet', self.call()[1])
        self.transport.assert_not_called()

    def test_no_complete_sensor_day_avoids_ai_cost(self):
        self.data['sensors'][0]['quality']['status'] = 'incomplete'
        self.data['sensors'][0]['value'] = None
        self.assertIn('geen volledige meetdag', self.call()[1])
        self.transport.assert_not_called()

    def test_disabled_ai_does_not_reuse_cached_narrative(self):
        self.call()
        self.cfg['ai']['enabled'] = False
        self.assertEqual(self.call()[0], [])
        self.transport.assert_called_once()

    def test_default_four_sensor_payload_fits_input_budget(self):
        cfg = json.loads((ROOT / 'config/ai_analyst/config.example.json').read_text())
        data = summary()
        data['sensors'] = []
        for configured in cfg['sensors']:
            configured['share_with_ai'] = True
            sensor = copy.deepcopy(summary()['sensors'][0])
            sensor['id'] = configured['id']
            sensor['label'] = configured['label']
            data['sensors'].append(sensor)
        body = d.request_body(d.external_summary(data, cfg), cfg)
        self.assertLessEqual(len(d.json_bytes(body)) + 1024, cfg['ai']['max_input_tokens'])

    def test_no_key_or_no_consent_does_not_call(self):
        with patch.dict(os.environ, {}, clear=True):
            self.call()
        self.cfg['sensors'][0]['share_with_ai'] = False
        self.call()
        self.transport.assert_not_called()

    def test_invalid_response_falls_back_but_accounts_for_usage(self):
        self.transport.return_value = ai_response([{'sensor_id': 'grid_import', 'pattern': 'below_7d', 'suggestion': 'monitor'}])
        self.assertEqual(self.call()[0], [])
        entry = self.state['ai_days']['2026-10-31']
        self.assertEqual(entry['status'], 'failed')
        self.assertEqual(Decimal(entry['cost_usd']), Decimal('.00056'))

    def test_truncated_response_falls_back(self):
        response = ai_response()
        response['choices'][0]['finish_reason'] = 'length'
        self.transport.return_value = response
        self.assertEqual(self.call()[0], [])

    def test_impossible_usage_never_refunds_reservation(self):
        self.transport.return_value = ai_response()
        self.transport.return_value['usage']['prompt_tokens'] = 999999
        self.call()
        entry = self.state['ai_days']['2026-10-31']
        self.assertEqual(entry['cost_usd'], entry['reserved_usd'])

    def test_consent_change_invalidates_cached_findings(self):
        self.call()
        self.cfg['sensors'][0]['share_with_ai'] = False
        findings, _ = self.call()
        self.assertEqual(findings, [])
        self.transport.assert_called_once()


class PersistenceAndRunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.cfg = config()
        self.client = MagicMock()
        self.factory = Mock(return_value=self.client)
        self.collector = Mock(return_value=summary())
        self.ai = Mock(return_value=ai_response())
        self.telegram = Mock(return_value={'ok': True, 'result': {'message_id': 123}})
        self.env = patch.dict(os.environ, {
            'HA_TOKEN': 'synthetic-ha-token', 'OPENAI_API_KEY': 'synthetic-openai-key',
            'TELEGRAM_BOT_TOKEN': '123456:synthetic', 'TELEGRAM_CHAT_ID': '-12345'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_report(self, **kwargs):
        return d.run(self.cfg, self.path, date(2026, 10, 30),
                     datetime(2026, 10, 31, 6, 15, tzinfo=d.TZ),
                     client_factory=self.factory, collector=self.collector,
                     ai_transport=self.ai, telegram_transport=self.telegram, **kwargs)

    def test_end_to_end_mocked_and_repeat_is_noop(self):
        self.assertIn('bevestigd', self.run_report())
        self.assertTrue((self.path / 'summary-2026-10-30.json').exists())
        self.assertIn('geen dubbele', self.run_report())
        self.ai.assert_called_once()
        self.telegram.assert_called_once()
        self.factory.assert_called_once()
        self.assertEqual((self.path / 'state.json').stat().st_mode & 0o777, 0o600)
        text = self.telegram.call_args.args[1]['text']
        self.assertIn('Netafname', text)
        self.assertNotIn('parse_mode', self.telegram.call_args.args[1])

    def test_concurrent_runs_share_one_ai_and_delivery(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.run_report) for _ in range(2)]
            results = [future.result(timeout=5) for future in futures]
        self.ai.assert_called_once()
        self.telegram.assert_called_once()
        self.assertTrue(any('geen dubbele' in result for result in results))

    def test_local_only_calls_no_external_services(self):
        self.assertIn('niet aangeroepen', self.run_report(local_only=True))
        self.ai.assert_not_called()
        self.telegram.assert_not_called()

    def test_disabled_telegram_avoids_pointless_ai_cost(self):
        self.cfg['telegram']['enabled'] = False
        self.run_report()
        self.ai.assert_not_called()
        self.telegram.assert_not_called()

    def test_missing_telegram_config_fails_before_ai(self):
        with patch.dict(os.environ, {'HA_TOKEN': 'test'}, clear=True), self.assertRaises(d.ConfigError):
            self.run_report()
        self.ai.assert_not_called()
        self.factory.assert_not_called()

    def test_telegram_requires_explicit_consent(self):
        self.cfg['sensors'][0]['share_with_telegram'] = False
        with self.assertRaises(d.ConfigError):
            self.run_report()
        self.factory.assert_not_called()

    def test_ambiguous_telegram_failure_never_duplicates(self):
        self.telegram.side_effect = d.DeliveryError('timeout')
        with self.assertRaises(d.DeliveryError):
            self.run_report()
        self.assertIn('geen dubbele', self.run_report())
        self.telegram.assert_called_once()
        self.ai.assert_called_once()

    def test_explicit_telegram_rejection_can_be_retried_without_new_ai(self):
        self.telegram.side_effect = [d.DeliveryError('rejected', uncertain=False), {'ok': True, 'result': {'message_id': 1}}]
        with self.assertRaises(d.DeliveryError):
            self.run_report()
        self.run_report()
        self.assertEqual(self.telegram.call_count, 2)
        self.ai.assert_called_once()

    def test_ha_failure_produces_unavailable_not_zero(self):
        self.collector.side_effect = RuntimeError('synthetic unavailable')
        self.run_report(local_only=True)
        data = json.loads((self.path / 'summary-2026-10-30.json').read_text())
        self.assertIsNone(data['sensors'][0]['value'])
        self.assertEqual(data['sensors'][0]['quality']['status'], 'unavailable')

    def test_corrupt_state_fails_closed(self):
        (self.path / 'state.json').write_text('{broken')
        with self.assertRaises(d.ConfigError):
            self.run_report()
        self.ai.assert_not_called()

    def test_invalid_decimal_state_fails_closed(self):
        (self.path / 'state.json').write_text(json.dumps({'version': 1, 'ai_days': {
            '2026-10-31': {'status': 'reserved', 'cost_usd': 'not-a-cost'}}, 'reports': {}}))
        with self.assertRaises(d.ConfigError):
            self.run_report()
        self.ai.assert_not_called()

    def test_ha_outage_sends_fallback_without_ai_cost(self):
        self.collector.side_effect = RuntimeError('synthetic source unavailable')
        self.run_report()
        self.ai.assert_not_called()
        self.telegram.assert_called_once()
        self.assertIn('niet beschikbaar', self.telegram.call_args.args[1]['text'])

    def test_lost_state_is_not_a_fresh_budget(self):
        (self.path / 'summary-2026-10-29.json').write_text('{}')
        with self.assertRaises(d.ConfigError):
            self.run_report()
        self.ai.assert_not_called()

    def test_existing_reserved_state_survives_restart(self):
        d.atomic_json(self.path / 'state.json', {'version': 1, 'ai_days': {
            '2026-10-31': {'status': 'reserved', 'cost_usd': '.01'}}, 'reports': {}})
        self.run_report()
        self.ai.assert_not_called()
        self.telegram.assert_called_once()

    def test_state_contains_no_tokens(self):
        self.run_report()
        content = (self.path / 'state.json').read_text()
        self.assertNotIn('synthetic-', content)
        self.assertIn('cost_usd', content)

    def test_today_is_rejected(self):
        with self.assertRaises(d.ConfigError):
            d.run(self.cfg, self.path, date(2026, 10, 31), datetime(2026, 10, 31, tzinfo=d.TZ))

    def test_http_errors_never_leak_url_or_body(self):
        from urllib.error import HTTPError
        opener = Mock()
        opener.open.side_effect = HTTPError('https://secret-in-path', 401, 'private response', {}, None)
        with patch.object(d, 'build_opener', return_value=opener):
            with self.assertRaises(d.DeliveryError) as raised:
                d.http_json('https://secret-in-path', {})
        self.assertNotIn('secret', str(raised.exception))
        self.assertNotIn('private', str(raised.exception))
        self.assertFalse(raised.exception.uncertain)

    def test_incomplete_http_response_is_sanitized_and_ambiguous(self):
        from http.client import IncompleteRead
        opener = Mock()
        opener.open.side_effect = IncompleteRead(b'private-body', 100)
        with patch.object(d, 'build_opener', return_value=opener), self.assertRaises(d.DeliveryError) as raised:
            d.http_json('https://not-contacted.invalid', {})
        self.assertTrue(raised.exception.uncertain)
        self.assertNotIn('private', str(raised.exception))

    def test_redirects_not_followed(self):
        self.assertIsNone(d.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere'))

    def test_telegram_rejected_response_and_missing_confirmation(self):
        for response, uncertain in [({'ok': False}, False), ({'ok': True}, True)]:
            with self.subTest(response=response), self.assertRaises(d.DeliveryError) as raised:
                d.send_telegram('synthetic', Mock(return_value=response))
            self.assertEqual(raised.exception.uncertain, uncertain)


class SystemdTests(unittest.TestCase):
    def test_units_use_isolated_account_and_persistent_amsterdam_timer(self):
        import configparser
        service = configparser.ConfigParser(interpolation=None, strict=False)
        service.read(ROOT / 'systemd/stalman-ai-analyst.service')
        unit = service['Service']
        self.assertEqual(unit['User'], 'stalman-ai')
        self.assertEqual(unit['StateDirectoryMode'], '0700')
        self.assertEqual(unit['ProtectSystem'], 'strict')
        self.assertEqual(unit['NoNewPrivileges'], 'true')
        self.assertEqual(unit['EnvironmentFile'], '/etc/stalman-ai-analyst.env')
        self.assertIn('--state-dir /var/lib/stalman-ai-analyst', unit['ExecStart'])
        timer = configparser.ConfigParser(interpolation=None)
        timer.read(ROOT / 'systemd/stalman-ai-analyst.timer')
        self.assertEqual(timer['Timer']['Persistent'], 'true')
        self.assertEqual(timer['Timer']['OnCalendar'], '*-*-* 06:15:00 Europe/Amsterdam')


if __name__ == '__main__':
    unittest.main()
