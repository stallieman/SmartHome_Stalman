"""Synthetic tests only; no production statistics or financial output."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "config" / "energy_finance"))
import historical_import_costs as historical  # noqa: E402


class HistoricalImportCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.production = json.loads(
            (ROOT / "config" / "energy_finance" / "tariffs.json").read_text()
        )

    def response(self, rows_normal, rows_offpeak):
        return {
            "statistics": {
                "sensor.p1_meter_energie_import_tarief_2": rows_normal,
                "sensor.p1_meter_energie_import_tarief_1": rows_offpeak,
            }
        }

    @staticmethod
    def row(start, end, change):
        return {"start": start, "end": end, "change": change}

    def complete_response(self):
        return self.response(
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", 1)],
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", 2)],
        )

    def calculate(self, response=None, start="2026-10-30T21:00:00+01:00",
                  end="2026-10-30T22:00:00+01:00", config=None, plan_id="essent-2026-current-contract"):
        return historical.calculate(
            config or self.production,
            response or self.complete_response(),
            start,
            end,
            "2026-10-30T20:36:47+01:00",
            plan_id,
        )

    def test_confirmed_mapping_selects_normal_and_offpeak_and_reuses_rates(self):
        rates = historical.indicative_rates(self.production["plans"][0])
        self.assertEqual(rates["normal"], historical.Decimal(".292551"))
        self.assertEqual(rates["offpeak"], historical.Decimal(".289284"))
        result = self.calculate()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["classification"], "indicatief")
        self.assertEqual(result["normal"]["statistic_id"], "sensor.p1_meter_energie_import_tarief_2")
        self.assertEqual(result["offpeak"]["statistic_id"], "sensor.p1_meter_energie_import_tarief_1")
        self.assertEqual(result["normal"]["kwh"], "1")
        self.assertEqual(result["offpeak"]["kwh"], "2")
        self.assertEqual(result["normal"]["cost_eur"], "0.29")
        self.assertEqual(result["offpeak"]["cost_eur"], "0.58")
        self.assertFalse(result["contractually_confirmed"])

    def test_explicit_indicative_plan_is_limited_to_scenario_year(self):
        response = self.response(
            [self.row("2027-01-01T20:00:00+00:00", "2027-01-01T21:00:00+00:00", 1)],
            [self.row("2027-01-01T20:00:00+00:00", "2027-01-01T21:00:00+00:00", 0)],
        )
        result = historical.calculate(
            self.production, response, "2027-01-01T21:00:00+01:00",
            "2027-01-01T22:00:00+01:00", "2026-10-30T20:36:47+01:00",
            "essent-2026-current-contract",
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["total_eur"])

    def test_timezone_offsets_select_the_same_utc_hour(self):
        utc = self.calculate(start="2026-10-30T20:00:00+00:00", end="2026-10-30T21:00:00+00:00")
        local = self.calculate(start="2026-10-30T21:00:00+01:00", end="2026-10-30T22:00:00+01:00")
        self.assertEqual(utc["total_eur"], local["total_eur"])
        self.assertEqual(utc["calculated_from"], "2026-10-30T20:00:00+00:00")

    def test_partial_measurement_hour_is_reported_and_excluded(self):
        response = self.response(
            [
                self.row("2026-10-30T19:00:00+00:00", "2026-10-30T20:00:00+00:00", ".113"),
                self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", "1"),
            ],
            [
                self.row("2026-10-30T19:00:00+00:00", "2026-10-30T20:00:00+00:00", "0"),
                self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", "2"),
            ],
        )
        result = self.calculate(response, start="2026-10-30")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["coverage"]["status"], "partial")
        self.assertEqual(result["coverage"]["complete_hours"], 1)
        self.assertEqual(len(result["coverage"]["excluded_partial_hours"]), 1)
        self.assertEqual(result["normal"]["kwh"], "1")

    def test_missing_interior_hour_blocks_all_costs(self):
        response = self.response(
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", 1)],
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", 2)],
        )
        result = self.calculate(response, end="2026-10-30T23:00:00+01:00")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["total_eur"])
        self.assertEqual(result["coverage"]["missing_hours"], ["2026-10-30T21:00:00+00:00"])

    def test_dated_plan_selection_uses_non_overlapping_validity(self):
        config = copy.deepcopy(self.production)
        first = config["plans"][0]
        first.update(id="first", valid_from="2026-10-01", valid_until="2026-10-31")
        second = copy.deepcopy(first)
        second.update(id="second", valid_from="2026-10-31", valid_until="2026-12-01")
        config["plans"] = [first, second]
        result = self.calculate(config=config, plan_id=None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tariff_plans"], ["first"])
        later = self.response(
            [self.row("2026-10-31T20:00:00+00:00", "2026-10-31T21:00:00+00:00", 1)],
            [self.row("2026-10-31T20:00:00+00:00", "2026-10-31T21:00:00+00:00", 0)],
        )
        result = historical.calculate(config, later, "2026-10-31T21:00:00+01:00",
                                      "2026-10-31T22:00:00+01:00",
                                      "2026-10-30T20:36:47+01:00", None)
        self.assertEqual(result["tariff_plans"], ["second"])

    def test_rounding_occurs_after_exact_decimal_calculation(self):
        response = self.response(
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", ".01")],
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", ".01")],
        )
        result = self.calculate(response)
        self.assertEqual(result["normal"]["cost_eur"], "0.00")
        self.assertEqual(result["offpeak"]["cost_eur"], "0.00")
        self.assertEqual(result["total_eur"], "0.01")

    def test_negative_change_is_rejected(self):
        response = self.response(
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", -1)],
            [self.row("2026-10-30T20:00:00+00:00", "2026-10-30T21:00:00+00:00", 0)],
        )
        result = self.calculate(response)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["total_eur"])


if __name__ == "__main__":
    unittest.main()
