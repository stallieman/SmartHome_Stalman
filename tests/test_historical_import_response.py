"""Tests for unavailable CLI responses and Home Assistant script handling."""
from contextlib import redirect_stdout
from io import StringIO
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import quote

from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "config" / "packages" / "energie_historische_kosten.yaml"
sys.path.insert(0, str(ROOT / "config" / "energy_finance"))
import historical_import_costs as historical  # noqa: E402


class HistoricalImportResponseTests(unittest.TestCase):
    def test_unavailable_json_is_a_successfully_processed_cli_response(self):
        config = json.loads(
            (ROOT / "config" / "energy_finance" / "tariffs.json").read_text()
        )
        statistics = {"statistics": {}}
        with TemporaryDirectory() as directory:
            config_path = Path(directory) / "tariffs.json"
            config_path.write_text(json.dumps(config))
            arguments = [
                "historical_import_costs.py",
                "--config", str(config_path),
                "--statistics-url", quote(json.dumps(statistics), safe=""),
                "--start-url", quote("2026-10-30T21:00:00+01:00", safe=""),
                "--end-url", quote("2026-10-30T22:00:00+01:00", safe=""),
                "--plan-id", "essent-2026-current-contract",
            ]
            output = StringIO()
            with patch.object(sys, "argv", arguments):
                with redirect_stdout(output):
                    returncode = historical.main()

        result = json.loads(output.getvalue())
        self.assertEqual(returncode, 0)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["total_eur"])

    def test_script_message_distinguishes_unavailable_from_calculated(self):
        package = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
        sequence = package["script"]["stalman_historische_importkosten"]["sequence"]
        shell_action = next(
            step for step in sequence
            if step.get("action") == "shell_command.stalman_historical_import_costs"
        )
        final_action = sequence[-1]
        message = Environment().from_string(final_action["stop"])

        self.assertEqual(shell_action["response_variable"], "historical_calculation")
        self.assertEqual(final_action["response_variable"], "historical_result")
        self.assertIn(
            "Historische indicatieve importkosten berekend",
            message.render(historical_summary_status="ok"),
        )
        self.assertIn(
            "Historische kosten niet beschikbaar: ontbrekende statistiek",
            message.render(historical_result={
                "status": "unavailable",
                "reason": "ontbrekende statistiek",
            }, historical_summary_status="unavailable"),
        )


if __name__ == "__main__":
    unittest.main()
