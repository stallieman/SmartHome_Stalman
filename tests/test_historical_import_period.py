"""Tests for the historical-cost script's pre-Recorder period guards."""
from datetime import date, datetime, time
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "config" / "packages" / "energie_historische_kosten.yaml"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


def as_timestamp(value, default=None):
    if not isinstance(value, str):
        return default
    try:
        if len(value) == 10:
            parsed = datetime.combine(date.fromisoformat(value), time.min, LOCAL_TZ)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return default
        return parsed.timestamp()
    except (OverflowError, TypeError, ValueError):
        return default


class HistoricalImportPeriodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
        cls.sequence = package["script"]["stalman_historische_importkosten"]["sequence"]
        guards = [step for step in cls.sequence if "if" in step]
        cls.invalid_guard = Environment().from_string(
            guards[0]["if"][0]["value_template"]
        )
        cls.length_guard = Environment().from_string(
            guards[1]["if"][0]["value_template"]
        )
        cls.context = {"as_timestamp": as_timestamp}

    def invalid(self, start, end):
        return self.invalid_guard.render(start=start, end=end, **self.context).strip() == "True"

    def too_long(self, start, end):
        return self.length_guard.render(start=start, end=end, **self.context).strip() == "True"

    def test_both_guards_run_before_recorder_action(self):
        actions = [step.get("action") for step in self.sequence]
        self.assertEqual(actions[0], "input_text.set_value")
        self.assertEqual(actions.index("recorder.get_statistics"), 3)
        guards = [step for step in self.sequence if "if" in step]
        self.assertEqual(guards[0]["then"][0]["error"], True)
        self.assertIn("Ongeldige periode", guards[0]["then"][0]["stop"])
        self.assertEqual(guards[1]["then"][0]["error"], True)
        self.assertIn("Maximaal 14 dagen", guards[1]["then"][0]["stop"])

    def test_valid_date_and_timezone_aware_inputs(self):
        self.assertFalse(self.invalid("2026-10-30", "2026-11-13"))
        self.assertFalse(self.invalid(
            "2026-10-30T00:00:00+02:00", "2026-11-13T00:00:00+01:00"
        ))
        self.assertFalse(self.too_long("2026-10-30", "2026-11-13"))

    def test_exactly_fourteen_elapsed_days_allowed(self):
        self.assertFalse(self.too_long(
            "2026-10-30T00:00:00+00:00", "2026-11-13T00:00:00+00:00"
        ))

    def test_more_than_fourteen_elapsed_days_rejected(self):
        self.assertTrue(self.too_long(
            "2026-10-30T00:00:00+00:00", "2026-11-13T00:00:01+00:00"
        ))

    def test_partial_boundary_buckets_cannot_exceed_336_requested_hours(self):
        self.assertTrue(self.too_long(
            "2026-10-30T00:00:01+00:00", "2026-11-13T00:00:02+00:00"
        ))

    def test_invalid_calendar_dates_naive_datetimes_and_reversed_period_rejected(self):
        for start, end in (
            ("2026-02-30", "2026-03-01"),
            ("2026-10-30T00:00:00", "2026-10-31T00:00:00"),
            ("not-a-date", "2026-11-01"),
            ("2026-11-01", "2026-10-31"),
            ("2026-10-31", "2026-10-31"),
        ):
            with self.subTest(start=start, end=end):
                self.assertTrue(self.invalid(start, end))

    def test_date_range_exceeding_limit_across_dst_is_rejected(self):
        # A fourteen-day local calendar range across the fall-back transition
        # spans fourteen days plus one elapsed hour.
        self.assertTrue(self.too_long("2026-10-20", "2026-11-03"))


if __name__ == "__main__":
    unittest.main()
