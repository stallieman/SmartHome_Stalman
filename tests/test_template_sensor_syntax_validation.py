"""
Validate template sensor trigger-based syntax against HA 2026.10 requirements.

Ensures the fix uses correct Home Assistant template platform structure.
"""

import unittest
import yaml


class TemplateSensorSyntaxValidationTests(unittest.TestCase):
    """Verify template sensor YAML structure is valid for HA 2026.10."""

    def setUp(self):
        """Load the package YAML."""
        with open('config/packages/energie_historische_kosten.yaml', 'r') as f:
            self.config = yaml.safe_load(f)

    def test_template_section_exists(self):
        """Template section must exist and be a list."""
        self.assertIn('template', self.config)
        self.assertIsInstance(self.config['template'], list)
        self.assertGreater(len(self.config['template']), 0)

    def test_trigger_based_structure_present(self):
        """First template entry must use trigger-based syntax."""
        template = self.config['template'][0]
        
        # Must have trigger field
        self.assertIn('trigger', template)
        self.assertEqual(template['trigger'], 'state', 
                        'Trigger type must be "state" for HA 2026.10')

    def test_entity_id_field_required(self):
        """Trigger must have entity_id to specify dependency."""
        template = self.config['template'][0]
        
        self.assertIn('entity_id', template)
        self.assertEqual(
            template['entity_id'],
            'input_text.stalman_historical_importcosts_summary',
            'Entity ID must be the helper we depend on'
        )

    def test_sensors_section_structure(self):
        """Sensors section must be a dict with sensor key."""
        template = self.config['template'][0]
        
        self.assertIn('sensors', template)
        self.assertIsInstance(template['sensors'], dict)
        self.assertIn('stalman_historische_importkosten', template['sensors'])

    def test_sensor_has_required_fields(self):
        """Sensor definition must have required fields for HA 2026.10."""
        template = self.config['template'][0]
        sensor = template['sensors']['stalman_historische_importkosten']
        
        required_fields = [
            'name',
            'unique_id',
            'device_class',
            'unit_of_measurement',
            'availability',
            'state',
            'attributes',
        ]
        
        for field in required_fields:
            self.assertIn(field, sensor, 
                         f'Sensor must have "{field}" field for HA 2026.10')

    def test_sensor_name_matches_unique_id(self):
        """Sensor unique_id should match entity_id pattern."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertEqual(sensor['unique_id'], 'stalman_historische_importkosten')

    def test_device_class_is_monetary(self):
        """Device class should be 'monetary' for currency display."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertEqual(sensor['device_class'], 'monetary')

    def test_unit_of_measurement_is_eur(self):
        """Unit should be EUR."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertEqual(sensor['unit_of_measurement'], 'EUR')

    def test_availability_template_is_string(self):
        """Availability must be a template string."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertIsInstance(sensor['availability'], str)
        self.assertGreater(len(sensor['availability']), 0)

    def test_state_template_is_string(self):
        """State must be a template string."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertIsInstance(sensor['state'], str)
        self.assertGreater(len(sensor['state']), 0)

    def test_attributes_are_defined(self):
        """Attributes section must exist and contain templates."""
        sensor = self.config['template'][0]['sensors']['stalman_historische_importkosten']
        
        self.assertIn('attributes', sensor)
        self.assertIsInstance(sensor['attributes'], dict)
        self.assertGreater(len(sensor['attributes']), 0)

    def test_trigger_syntax_matches_ha_2026_10_docs(self):
        """
        Verify the complete structure matches HA 2026.10 template platform spec.
        
        According to Home Assistant documentation (2022.1+), trigger-based 
        templates have this structure:
        
        template:
          - trigger: state
            entity_id: sensor.something
            sensors:
              my_sensor:
                name: ...
                state: ...
        """
        template = self.config['template'][0]
        
        # Structure check
        self.assertEqual(template['trigger'], 'state')
        self.assertIsInstance(template['entity_id'], str)
        self.assertIsInstance(template['sensors'], dict)
        
        # Verify sensor is under sensors dict (not a list)
        for sensor_key, sensor_config in template['sensors'].items():
            self.assertIsInstance(sensor_config, dict)
            self.assertIn('state', sensor_config)
            # Should NOT have this old-style field
            self.assertNotIn('default_entity_id', sensor_config,
                           'Should not use old-style field with trigger syntax')

    def test_no_old_style_sensor_list(self):
        """Verify we're not mixing old and new syntax."""
        template = self.config['template'][0]
        
        # Old style would have "- sensor:" with list syntax
        # New style has "sensors:" with dict syntax
        self.assertNotIn('- sensor', str(template),
                        'Should not mix old-style "- sensor:" list syntax')
        
        self.assertIn('sensors', template,
                     'Should use new-style "sensors" dict')

    def test_no_old_style_default_entity_id(self):
        """Old-style packages used default_entity_id; new style doesn't need it."""
        template = self.config['template'][0]
        sensor = template['sensors']['stalman_historische_importkosten']
        
        # Trigger-based templates don't use default_entity_id
        self.assertNotIn('default_entity_id', sensor,
                        'Trigger-based templates do not use default_entity_id')


if __name__ == '__main__':
    unittest.main()
