"""
Test suite for energy dashboard updates.

Validates that dashboard changes:
1. Use correct Dutch currency notation (€ X,XX)
2. Remove outdated financial entities from display
3. Show "Nog niet beschikbaar" for unsupported calculations
4. Maintain all energy graphs and sensor displays
"""

import unittest
import yaml


class DashboardEnergyUpdateTests(unittest.TestCase):
    """Verify dashboard updates are correctly applied."""

    def setUp(self):
        """Load the dashboard YAML."""
        with open('config/dashboards/energie_thuisbatterij.yaml', 'r') as f:
            self.dashboard = yaml.safe_load(f)

    def test_dashboard_structure_valid(self):
        """Dashboard must have 3 views: Overzicht, Simulatie, Analyse."""
        views = self.dashboard.get('views', [])
        view_titles = [v.get('title') for v in views]
        
        self.assertIn('Overzicht', view_titles, 'Missing Overzicht view')
        self.assertIn('Simulatie', view_titles, 'Missing Simulatie view')
        self.assertIn('Analyse', view_titles, 'Missing Analyse view')

    def test_dutch_currency_format_on_overview(self):
        """
        Overview tab must use Dutch currency notation: € X,XX.
        Not: X.XX € or similar.
        """
        overzicht = next((v for v in self.dashboard['views'] if v['title'] == 'Overzicht'), None)
        self.assertIsNotNone(overzicht, 'Overzicht view not found')
        
        # Find the cost card markdown
        cost_card_found = False
        for section in overzicht.get('sections', []):
            for card in section.get('cards', []):
                if card.get('type') == 'markdown':
                    content = card.get('content', '')
                    if 'Indicatieve bruto stroomafnamekosten' in content:
                        cost_card_found = True
                        
                        # Must use € notation BEFORE amount
                        self.assertIn('€ {{', content,
                                     'Currency notation must use "€ {{" for Dutch format')
                        
                        # Should format with comma decimal separator
                        self.assertIn("| replace('.', ',')", content,
                                     'Must replace . with , for Dutch decimal notation')
        
        self.assertTrue(cost_card_found, 'Cost card not found in Overzicht')

    def test_battery_savings_unavailable_on_overview(self):
        """
        Overview tab battery savings must show "Nog niet beschikbaar".
        Should not display financial calculations.
        """
        overzicht = next((v for v in self.dashboard['views'] if v['title'] == 'Overzicht'), None)
        
        battery_savings_found = False
        for section in overzicht.get('sections', []):
            for card in section.get('cards', []):
                if card.get('type') == 'markdown':
                    content = card.get('content', '')
                    if 'Batterijbesparing · simulatie' in content:
                        battery_savings_found = True
                        
                        # Must show unavailable, not financial calculation
                        self.assertIn('Nog niet beschikbaar', content,
                                     'Battery savings must show unavailable status')
                        
                        # Should NOT have sensor state calculation
                        self.assertNotIn('sensor.stalman_batterijbesparing_vandaag', content,
                                       'Should not query battery savings sensor')
        
        self.assertTrue(battery_savings_found, 'Battery savings card not found')

    def test_analysis_tab_simplified(self):
        """
        Analysis tab financial section must be simplified.
        Should remove old entities-based cost lists.
        Should show only "Nog niet beschikbaar" messages for unsupported calculations.
        """
        analyse = next((v for v in self.dashboard['views'] if v['title'] == 'Analyse'), None)
        self.assertIsNotNone(analyse, 'Analyse view not found')
        
        # Find the financial section
        financial_section_found = False
        for section in analyse.get('sections', []):
            cards = section.get('cards', [])
            for i, card in enumerate(cards):
                if card.get('type') == 'heading' and card.get('heading') == 'Financiën':
                    financial_section_found = True
                    
                    # Count markdown cards in this section (after the heading)
                    markdown_cards = [c for c in cards[i+1:] if c.get('type') == 'markdown']
                    
                    # Should have at least 3 markdown cards for:
                    # 1. Historische Essent kosten
                    # 2. Batterijbesparing unavailable
                    # 3. Kosten met/zonder batterij unavailable
                    # 4. Terugverdientijd unavailable
                    self.assertGreaterEqual(len(markdown_cards), 3,
                                          'Financial section should have at least 3 markdown cards')
                    
                    # Combine all markdown content
                    all_content = ' '.join([c.get('content', '') for c in markdown_cards])
                    
                    # Must mention "Nog niet beschikbaar" at least twice
                    # (once in conditional template, once+ in separate cards)
                    unavailable_count = all_content.count('beschikbaar')
                    self.assertGreaterEqual(unavailable_count, 3,
                                          'Should show unavailable for multiple items')
        
        self.assertTrue(financial_section_found, 'Financial section not found in Analyse')

    def test_no_outdated_cost_entities_in_display(self):
        """
        Dashboard should NOT display outdated cost calculation entities.
        These sensoren should exist (for backward compatibility) but not be shown.
        """
        analyse = next((v for v in self.dashboard['views'] if v['title'] == 'Analyse'), None)
        
        # Collect all entity references in the dashboard
        all_entities = []
        for section in analyse.get('sections', []):
            for card in section.get('cards', []):
                # Check entities lists
                if 'entities' in card:
                    all_entities.extend([e.get('entity') for e in card['entities'] if isinstance(e, dict)])
        
        # These OLD sensoren should NOT be in the Analyse dashboard anymore
        old_entities = [
            'sensor.stalman_afrekening_kosten_zonder_batterij',
            'sensor.stalman_afrekening_kosten_met_simulatie',
            'sensor.stalman_besparingsscenario',
            'sensor.stalman_totaal_afrekening_zonder_batterij',
            'sensor.stalman_totaal_afrekening_met_simulatie',
            'sensor.stalman_kosten_zonder_batterij_vandaag',
            'sensor.stalman_kosten_met_batterij_vandaag',
            'sensor.stalman_batterijbesparing_vandaag',
            'sensor.stalman_meetvenster_zonder',
            'sensor.stalman_meetvenster_met',
            'sensor.stalman_meetvenster_verschil',
        ]
        
        for old_entity in old_entities:
            self.assertNotIn(old_entity, all_entities,
                           f'Dashboard should not display {old_entity}; use markdown "Nog niet beschikbaar" instead')

    def test_energy_graphs_preserved(self):
        """Energy measurement graphs should still be present and functional."""
        analyse = next((v for v in self.dashboard['views'] if v['title'] == 'Analyse'), None)
        
        graph_types_found = set()
        for section in analyse.get('sections', []):
            for card in section.get('cards', []):
                card_type = card.get('type')
                if card_type in ['statistics-graph', 'energy-distribution', 'energy-usage-graph']:
                    graph_types_found.add(card_type)
        
        # Must have statistics-graph for energy comparison
        self.assertIn('statistics-graph', graph_types_found,
                     'Must preserve energy comparison graph')

    def test_marstek_simulation_section_intact(self):
        """Marstek simulation section should be completely intact."""
        simulatie = next((v for v in self.dashboard['views'] if v['title'] == 'Simulatie'), None)
        self.assertIsNotNone(simulatie, 'Simulatie view must exist')
        
        # Check that Marstek section is present
        marstek_found = False
        for section in simulatie.get('sections', []):
            cards = section.get('cards', [])
            for card in cards:
                if card.get('type') == 'heading' and 'Marstek' in card.get('heading', ''):
                    marstek_found = True
        
        self.assertTrue(marstek_found, 'Marstek simulation section must be preserved')


if __name__ == '__main__':
    unittest.main()
