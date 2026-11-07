"""Verify the periodic startup guard from the actual automation template."""
from pathlib import Path
from types import SimpleNamespace
import re
import unittest


class FinanceStartupTests(unittest.TestCase):
    def test_periodic_waits_for_session_but_startup_still_initializes_and_collects(self):
        config = (Path(__file__).parents[1] / 'packages/energie_intervalcollector.yaml').read_text()
        pattern = r'  - condition: template\n    value_template: "\{\{ (.*?) \}\}"'
        match = re.search(pattern, config)
        self.assertIsNotNone(match)
        expression = match.group(1)
        self.assertLess(config.index("action: input_text.set_value"), match.start())
        self.assertLess(match.end(), config.index('action: shell_command.stalman_finance_collect'))

        def allowed(trigger_id, session):
            def states(entity):
                self.assertEqual(entity, 'input_text.stalman_finance_session')
                return session
            return eval(expression, {'__builtins__': {}},
                        {'trigger': SimpleNamespace(id=trigger_id), 'states': states})

        # The timer may run first while the startup run is still queued.
        self.assertFalse(allowed('sample', ''))
        # Startup remains able to set the session and execute the collection.
        self.assertTrue(allowed('startup', ''))
        self.assertTrue(allowed('startup', '2026-11-07T16:38:51+01:00'))
        self.assertTrue(allowed('sample', '2026-11-07T16:38:51+01:00'))
        self.assertTrue(allowed('tariff', ''))


if __name__ == '__main__':
    unittest.main()
