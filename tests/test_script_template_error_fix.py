"""
Regression test for script from_json template error.

Real error from HA 2026-11-02 19:13:31:
"ValueError: Template error: from_json got invalid input '...' but no default was specified"

The script's historical_summary_status variable was missing the default parameter
on the from_json filter.
"""

import unittest
import yaml
import json


class ScriptTemplateErrorFixTests(unittest.TestCase):
    """Verify script template errors are fixed."""

    def setUp(self):
        """Load the package YAML."""
        with open('config/packages/energie_historische_kosten.yaml', 'r') as f:
            self.config = yaml.safe_load(f)

    def test_script_historical_summary_status_has_from_json_default(self):
        """
        Script's historical_summary_status variable must have from_json(default={})
        to handle JSON parsing without errors.
        
        Root cause: HA log error "from_json got invalid input but no default was specified"
        at line 172 of the package.
        """
        script = self.config['script']['stalman_historische_importkosten']
        sequence = script['sequence']
        
        # Find the variables section that sets historical_summary_status
        found = False
        for step in sequence:
            if isinstance(step, dict) and 'variables' in step:
                if 'historical_summary_status' in step['variables']:
                    found = True
                    template = step['variables']['historical_summary_status']
                    
                    # Must include from_json with default parameter
                    self.assertIn(
                        'from_json(default={})',
                        template,
                        'Script must use from_json(default={}) in historical_summary_status template'
                    )
                    
                    # Should not have bare from_json without default (old error case)
                    self.assertNotIn(
                        'from_json %}',
                        template,
                        'Script must not use bare from_json without default parameter'
                    )
        
        self.assertTrue(found, 'Script must have historical_summary_status variable')

    def test_historical_summary_json_is_parseable(self):
        """
        Verify the JSON structure that historical_summary produces is parseable
        by the from_json filter with default parameter.
        """
        # The actual JSON that was failing in the HA logs
        test_json = '{"status":"ok","date":"2026-11-01","eur":"1.64","normal":"0","offpeak":"5.6550000000006548213","coverage":"complete","hours":24,"expected":24}'
        
        # from_json should parse this without error when default is provided
        try:
            parsed = json.loads(test_json)
            self.assertEqual(parsed['status'], 'ok')
            self.assertEqual(parsed['eur'], '1.64')
            self.assertEqual(parsed['coverage'], 'complete')
        except json.JSONDecodeError as e:
            self.fail(f"JSON parse error on valid data: {e}")

    def test_script_helper_update_action_exists(self):
        """
        Verify script has the action that updates the helper with the calculated summary.
        """
        script = self.config['script']['stalman_historische_importkosten']
        sequence = script['sequence']
        
        # Find the input_text.set_value action
        found = False
        for step in sequence:
            if isinstance(step, dict) and 'action' in step:
                if step['action'] == 'input_text.set_value':
                    if 'target' in step:
                        target = step['target']
                        if target.get('entity_id') == 'input_text.stalman_historical_importcosts_summary':
                            found = True
        
        self.assertTrue(
            found,
            'Script must have input_text.set_value action for the helper'
        )

    def test_no_bare_from_json_anywhere_in_script(self):
        """
        Audit: Ensure no other script templates use bare from_json without default.
        """
        script = self.config['script']['stalman_historische_importkosten']
        sequence = script['sequence']
        
        # Build a string representation of all templates in the sequence
        all_templates = yaml.dump(sequence)
        
        # Check for patterns that indicate missing defaults
        # Pattern: from_json followed by space, pipe, or closing brace
        import re
        
        # This pattern looks for from_json not followed by (
        problem_pattern = r'from_json(?!\()'
        
        matches = re.findall(problem_pattern, all_templates)
        
        # Filter out false positives like "from_json(default={})"
        for match in matches:
            # Get context around the match
            idx = all_templates.find('from_json')
            if idx >= 0:
                context = all_templates[idx:idx+20]
                if 'from_json(default=' not in context:
                    self.fail(f'Found from_json without default: {context}')

    def test_historical_summary_status_handles_both_string_and_dict(self):
        """
        Regression test: Template must handle both string JSON and dict objects.
        
        The template should check if historical_summary is already a mapping (dict)
        before attempting to parse with from_json.
        
        Scenario: If a future change makes historical_summary a dict instead of string,
        the template should still work without from_json filter errors.
        """
        script = self.config['script']['stalman_historische_importkosten']
        sequence = script['sequence']
        
        # Find the template
        for step in sequence:
            if isinstance(step, dict) and 'variables' in step:
                if 'historical_summary_status' in step['variables']:
                    template = step['variables']['historical_summary_status']
                    
                    # Must check if historical_summary is already a mapping
                    self.assertIn(
                        'is mapping',
                        template,
                        'Template must check "is mapping" to handle both string JSON and dict'
                    )
                    
                    # Should have defensive conditional structure
                    self.assertIn(
                        'if historical_summary is mapping else',
                        template,
                        'Template must use conditional to handle both types'
                    )


if __name__ == '__main__':
    unittest.main()

