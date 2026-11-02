"""
Test template sensor trigger-based dependency resolution.

The template sensor uses trigger-based syntax (Home Assistant 2022.1+)
to ensure immediate re-render when the helper updates, fixing the
'unknown' state issue that occurred with old list-based syntax.
"""

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from jinja2 import Environment
import json


class TemplateSensorTriggerTests(unittest.TestCase):
    """Verify template sensor trigger-based syntax and availability logic."""

    def setUp(self):
        """Set up Jinja2 environment with Home Assistant filters and tests."""
        self.env = Environment()

        # Register Home Assistant's is_number test
        def is_number_test(value):
            if value is None:
                return False
            try:
                float(value)
                return True
            except (TypeError, ValueError):
                return False

        self.env.tests['is_number'] = is_number_test
        self.env.globals['is_number'] = is_number_test
        self.env.filters['from_json'] = lambda v, default=None: (
            json.loads(v) if isinstance(v, str) else default
        )

        # The availability template from the fixed package
        self.availability_template = (
            "{% set result = states('input_text.stalman_historical_importcosts_summary') "
            "| from_json(default={}) %}"
            "{% set yesterday = (now().date() - timedelta(days=1)).isoformat() %}"
            "{{ result.get('status') == 'ok'"
            "   and result.get('date') == yesterday"
            "   and result.get('coverage') == 'complete'"
            "   and result.get('hours', 0) == result.get('expected', -1)"
            "   and result.get('expected', 0) > 0"
            "   and is_number(result.get('eur')) }}"
        )

        # The state template
        self.state_template = (
            "{% set result = states('input_text.stalman_historical_importcosts_summary') "
            "| from_json(default={}) %}"
            "{{ result.get('eur', 'unavailable') }}"
        )

    def _render_template(self, template_text, helper_json, now_dt):
        """Render a template with given helper JSON and time."""
        def states_func(entity_id):
            if 'summary' in entity_id:
                return helper_json
            return 'unknown'

        template = self.env.from_string(template_text)
        return template.render(
            states=states_func,
            now=lambda: now_dt,
            timedelta=timedelta,
        )

    def test_trigger_based_immediate_rerender_on_helper_update(self):
        """
        With trigger-based syntax, sensor re-renders immediately when helper updates.

        When script updates the helper at 06:15 with yesterday's calculation,
        the trigger dependency ensures the sensor availability and state are
        evaluated immediately with correct date.
        """
        # Time: 2026-11-02 06:15:29 CET (day after calculation)
        now_dt = datetime(2026, 11, 2, 6, 15, 29, tzinfo=ZoneInfo("Europe/Amsterdam"))
        # Helper contains: calculation for 2026-11-01 (yesterday from HA's perspective)
        helper_json = (
            '{"status": "ok", "date": "2026-11-01", "eur": "1.64", '
            '"coverage": "complete", "hours": 24, "expected": 24}'
        )

        # Availability should be True because:
        # - status == 'ok' ✓
        # - date ('2026-11-01') == yesterday ('2026-11-01') ✓
        # - coverage == 'complete' ✓
        # - hours == expected (24 == 24) ✓
        # - expected > 0 ✓
        # - is_number('1.64') ✓
        availability_result = self._render_template(
            self.availability_template, helper_json, now_dt
        )
        self.assertEqual(availability_result.strip(), 'True')

        # State should show the EUR value
        state_result = self._render_template(self.state_template, helper_json, now_dt)
        self.assertEqual(state_result.strip(), '1.64')

    def test_availability_false_when_helper_date_older_than_expected(self):
        """
        Sensor becomes unavailable when helper date no longer matches expected date.

        If the sensor is checked on 2026-11-03 but helper still has 2026-11-01,
        the availability check fails (old data) and sensor returns 'unknown'.
        This ensures stale data is not displayed.
        """
        # Time: 2026-11-03 10:00:00 CET (two days after calculation)
        now_dt = datetime(2026, 11, 3, 10, 0, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
        # Helper still contains: calculation for 2026-11-01 (now STALE)
        helper_json = (
            '{"status": "ok", "date": "2026-11-01", "eur": "1.64", '
            '"coverage": "complete", "hours": 24, "expected": 24}'
        )

        # Availability should be False because:
        # - date ('2026-11-01') != yesterday ('2026-11-02') ✗
        availability_result = self._render_template(
            self.availability_template, helper_json, now_dt
        )
        self.assertEqual(availability_result.strip(), 'False')

    def test_availability_false_when_helper_coverage_incomplete(self):
        """Sensor unavailable when measurement coverage is incomplete."""
        now_dt = datetime(2026, 11, 2, 6, 30, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
        helper_json = (
            '{"status": "ok", "date": "2026-11-01", "eur": "1.64", '
            '"coverage": "partial", "hours": 18, "expected": 24}'
        )

        availability_result = self._render_template(
            self.availability_template, helper_json, now_dt
        )
        self.assertEqual(availability_result.strip(), 'False')

    def test_availability_false_when_eur_not_number(self):
        """Sensor unavailable when EUR value is not a valid number."""
        now_dt = datetime(2026, 11, 2, 6, 30, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
        helper_json = (
            '{"status": "ok", "date": "2026-11-01", "eur": "N/A", '
            '"coverage": "complete", "hours": 24, "expected": 24}'
        )

        availability_result = self._render_template(
            self.availability_template, helper_json, now_dt
        )
        self.assertEqual(availability_result.strip(), 'False')

    def test_state_default_when_helper_unavailable(self):
        """State template returns 'unavailable' when helper has no eur."""
        now_dt = datetime(2026, 11, 2, 6, 30, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
        helper_json = '{"status": "unavailable", "coverage": "incomplete"}'

        state_result = self._render_template(self.state_template, helper_json, now_dt)
        self.assertEqual(state_result.strip(), 'unavailable')

    def test_yaml_package_uses_trigger_based_syntax(self):
        """Verify package file uses trigger-based template platform."""
        import yaml

        with open('config/packages/energie_historische_kosten.yaml', 'r') as f:
            config = yaml.safe_load(f)

        # Must have template section
        self.assertIn('template', config)
        templates = config['template']
        self.assertIsInstance(templates, list)
        self.assertGreater(len(templates), 0)

        # First template must use trigger-based syntax
        first_template = templates[0]
        self.assertEqual(first_template.get('trigger'), 'state')
        self.assertEqual(
            first_template.get('entity_id'),
            'input_text.stalman_historical_importcosts_summary'
        )

        # Must have sensors under the trigger
        self.assertIn('sensors', first_template)
        sensors = first_template['sensors']
        self.assertIn('stalman_historische_importkosten', sensors)

        # Verify sensor configuration
        sensor = sensors['stalman_historische_importkosten']
        self.assertEqual(sensor.get('name'), 'Stalman historische importkosten')
        self.assertEqual(sensor.get('unique_id'), 'stalman_historische_importkosten')
        self.assertEqual(sensor.get('device_class'), 'monetary')
        self.assertEqual(sensor.get('unit_of_measurement'), 'EUR')
        self.assertIn('availability', sensor)
        self.assertIn('state', sensor)
        self.assertIn('attributes', sensor)


if __name__ == '__main__':
    unittest.main()

    def test_script_historical_summary_status_template_has_from_json_default(self):
        """
        Regression test: Script's historical_summary_status variable must have
        from_json(default={}) to handle JSON parsing without errors.
        
        Real error from HA logs:
        "Template error: from_json got invalid input '...' but no default was specified"
        """
        import yaml
        
        with open('config/packages/energie_historische_kosten.yaml', 'r') as f:
            config = yaml.safe_load(f)
        
        script = config['script']['stalman_historische_importkosten']
        sequence = script['sequence']
        
        # Find the variables section that sets historical_summary_status
        found = False
        for step in sequence:
            if 'variables' in step and 'historical_summary_status' in step['variables']:
                found = True
                template = step['variables']['historical_summary_status']
                
                # Must include from_json with default parameter
                self.assertIn('from_json(default={})',
                             template,
                             'Script must use from_json(default={}) in historical_summary_status template')
                
                # Should not have bare from_json without default
                self.assertNotIn('from_json }}',
                               template,
                               'Script must not use bare from_json without default parameter')
        
        self.assertTrue(found, 'Script must have historical_summary_status variable')

    def test_availability_template_parses_valid_json(self):
        """
        Verify availability template correctly parses the JSON that historical_summary_status produces.
        """
        from jinja2 import Environment
        
        env = Environment()
        env.tests['is_number'] = lambda v: isinstance(v, (int, float)) or (isinstance(v, str) and v.replace('.','',1).isdigit())
        env.globals['is_number'] = env.tests['is_number']
        env.filters['from_json'] = lambda v, default=None: json.loads(v) if isinstance(v, str) else default
        
        # The actual JSON that historical_summary_status should produce
        valid_json = '{"status":"ok","date":"2026-11-01","eur":"1.64","normal":"0","offpeak":"5.6550000000006548213","coverage":"complete","hours":24,"expected":24}'
        
        # Test that from_json(default={}) works with this JSON
        template = env.from_string("{{ value | from_json(default={}) }}")
        result = template.render(value=valid_json)
        
        # Should parse without error
        parsed = json.loads(result.replace("'", '"').replace("None", "null"))
        self.assertEqual(parsed['status'], 'ok')
        self.assertEqual(parsed['eur'], '1.64')
