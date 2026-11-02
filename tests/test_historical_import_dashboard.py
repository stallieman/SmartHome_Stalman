"""Tests for daily historical-cost persistence and dashboard freshness."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "config" / "packages" / "energie_historische_kosten.yaml"
DASHBOARD_PATH = ROOT / "config" / "dashboards" / "energie_thuisbatterij.yaml"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


def is_number(value):
    try:
        float(value)
        return value is not None
    except (TypeError, ValueError):
        return False


def from_json(value, default=None):
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class HistoricalImportDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = yaml.safe_load(PACKAGE_PATH.read_text(encoding="utf-8"))
        cls.dashboard = yaml.safe_load(DASHBOARD_PATH.read_text(encoding="utf-8"))
        cls.helper = cls.package["input_text"]["stalman_historical_importcosts_summary"]
        
        # Handle trigger-based template sensors (new format)
        template_list = cls.package["template"]
        if isinstance(template_list, list) and len(template_list) > 0:
            template_item = template_list[0]
            if "sensors" in template_item:
                # trigger-based format: template[0]["sensors"]["stalman_historische_importkosten"]
                cls.sensor = template_item["sensors"]["stalman_historische_importkosten"]
            elif "sensor" in template_item:
                # old format: template[0]["sensor"][0]
                cls.sensor = template_item["sensor"][0]
            else:
                raise KeyError("Cannot find sensor in template")
        
        cls.automation = cls.package["automation"][0]
        cls.sequence = cls.package["script"]["stalman_historische_importkosten"]["sequence"]
        cls.summary_template = (
            next(
                item["variables"]["historical_summary"]
                for item in cls.sequence
                if "variables" in item and "historical_summary" in item["variables"]
            )
        )
        cls.template_env = Environment()
        cls.template_env.filters["from_json"] = from_json
        cls.template_env.filters["to_json"] = json.dumps
        cls.template_env.tests["is_number"] = is_number

    def local_midnight(self, current_date):
        return datetime.combine(current_date, datetime.min.time(), LOCAL_TZ)

    def render_automation_period(self, current_date):
        trigger = self.automation["triggers"][0]
        self.assertEqual(trigger, {"trigger": "time", "at": "06:15:00"})
        action = self.automation["actions"][0]
        self.assertEqual(action["action"], "script.stalman_historische_importkosten")
        today = self.local_midnight(current_date)
        today_at = lambda _clock: today
        env = Environment()
        env.globals.update(
            today_at=today_at,
            now=lambda: today,
            timedelta=timedelta,
            strptime=lambda value, pattern: datetime.strptime(value, pattern),
            as_local=lambda value: (
                value.replace(tzinfo=LOCAL_TZ)
                if value.tzinfo is None
                else value.astimezone(LOCAL_TZ)
            ),
        )
        start = env.from_string(action["data"]["start"]).render()
        end = env.from_string(action["data"]["end"]).render()
        return datetime.fromisoformat(start), datetime.fromisoformat(end)

    def test_daily_automation_runs_the_existing_script_at_0615(self):
        self.assertEqual(self.automation["mode"], "single")
        self.assertEqual(
            self.automation["actions"][0]["action"],
            "script.stalman_historische_importkosten",
        )

    def test_previous_calendar_day_boundaries_follow_spring_dst(self):
        start, end = self.render_automation_period(datetime(2026, 3, 30).date())
        self.assertEqual(start.date().isoformat(), "2026-03-29")
        self.assertEqual(end.date().isoformat(), "2026-03-30")
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 23)

    def test_previous_calendar_day_boundaries_follow_autumn_dst(self):
        start, end = self.render_automation_period(datetime(2026, 10, 26).date())
        self.assertEqual(start.date().isoformat(), "2026-10-25")
        self.assertEqual(end.date().isoformat(), "2026-10-26")
        self.assertEqual((end.timestamp() - start.timestamp()) / 3600, 25)

    def summary_context(self, today, result, start, end):
        today_midnight = self.local_midnight(today)
        env = Environment()
        env.tests["is_number"] = is_number
        env.filters["to_json"] = json.dumps
        env.globals.update(
            today_at=lambda _clock: today_midnight,
            timedelta=timedelta,
            as_timestamp=lambda value: datetime.fromisoformat(value).timestamp(),
            is_number=is_number,
        )
        return json.loads(env.from_string(self.summary_template).render(
            start=start.isoformat(), end=end.isoformat(), historical_result=result
        ))

    def valid_result(self, date, hours):
        start = self.local_midnight(date)
        end = self.local_midnight(date + timedelta(days=1))
        return {
            "status": "ok",
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "total_eur": "5.14",
            "normal": {"kwh": "0"},
            "offpeak": {"kwh": "17.78"},
            "coverage": {"status": "complete", "complete_hours": hours},
        }, start, end

    def test_valid_summary_is_compact_and_contains_only_dashboard_fields(self):
        report_date = datetime(2026, 10, 31).date()
        result, start, end = self.valid_result(report_date, 24)
        summary = self.summary_context(report_date + timedelta(days=1), result, start, end)
        serialized = json.dumps(summary, separators=(",", ":"))
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["date"], "2026-10-31")
        self.assertEqual(summary["eur"], "5.14")
        self.assertEqual(summary["offpeak"], "17.78")
        self.assertEqual(summary["hours"], summary["expected"])
        self.assertLessEqual(len(serialized), self.helper["max"])
        self.assertEqual(self.helper["max"], 255)

    def test_unavailable_incomplete_and_stale_results_never_persist_costs(self):
        report_date = datetime(2026, 10, 31).date()
        result, start, end = self.valid_result(report_date, 24)
        today = report_date + timedelta(days=1)

        for altered in (
            {**result, "status": "unavailable"},
            {**result, "coverage": {"status": "partial", "complete_hours": 23}},
            {**result, "requested_start": "2026-10-30T00:00:00+02:00"},
        ):
            with self.subTest(altered=altered):
                summary = self.summary_context(today, altered, start, end)
                self.assertEqual(summary["status"], "unavailable")
                self.assertNotIn("eur", summary)

    def render_sensor(self, template, summary, today):
        date_today = self.local_midnight(today)
        env = self.template_env
        env.globals["is_number"] = is_number
        template_context = {
            "states": lambda _entity: json.dumps(summary),
            "now": lambda: date_today,
            "timedelta": timedelta,
        }
        return env.from_string(template).render(**template_context).strip()

    def test_sensor_requires_ok_yesterday_and_full_hour_coverage(self):
        self.assertTrue({
            "date", "normal_kwh", "offpeak_kwh", "coverage"
        }.issubset(self.sensor["attributes"]))
        valid_summary = {
            "status": "ok", "date": "2026-10-31", "eur": "5.14",
            "coverage": "complete", "hours": 24, "expected": 24,
            "normal": "0", "offpeak": "17.78",
        }
        availability = self.render_sensor(
            self.sensor["availability"],
            valid_summary,
            datetime(2026, 11, 1).date(),
        )
        self.assertEqual(availability, "True")
        self.assertEqual(
            self.render_sensor(self.sensor["state"], valid_summary, datetime(2026, 11, 1).date()),
            "5.14",
        )
        for summary, day in (
            (
                {"status": "ok", "date": "2026-10-30", "eur": "5.14",
                 "coverage": "complete", "hours": 24, "expected": 24},
                datetime(2026, 11, 1).date(),
            ),
            (
                {"status": "unavailable", "date": "2026-10-31", "coverage": "incomplete"},
                datetime(2026, 11, 1).date(),
            ),
            (
                {"status": "ok", "date": "2026-10-31", "eur": "5.14",
                 "coverage": "complete", "hours": 23, "expected": 24},
                datetime(2026, 11, 1).date(),
            ),
        ):
            self.assertEqual(
                self.render_sensor(self.sensor["availability"], summary, day),
                "False",
            )
        self.assertNotIn("state_class", self.sensor)

    def test_script_clears_old_value_before_any_validation_or_recorder_call(self):
        self.assertEqual(
            self.sequence[0]["action"],
            "input_text.set_value",
        )
        self.assertEqual(
            self.sequence[0]["data"]["value"],
            '{"status":"unavailable"}',
        )
        self.assertGreater(
            next(i for i, step in enumerate(self.sequence)
                 if step.get("action") == "recorder.get_statistics"),
            0,
        )
        length_guard = next(
            step for step in self.sequence
            if step.get("if", [{}])[0].get("value_template")
            == "{{ historical_summary | length <= 255 }}"
        )
        self.assertEqual(
            length_guard["then"][0]["action"],
            "input_text.set_value",
        )
        status_template = next(
            step["variables"]["historical_summary_status"]
            for step in self.sequence
            if "variables" in step and "historical_summary_status" in step["variables"]
        )
        status_env = Environment()
        status_env.filters["from_json"] = from_json
        render_status = status_env.from_string(status_template).render(
            historical_summary='{"status":"ok"}'
        ).strip()
        self.assertEqual(render_status, "ok")
        oversized_status = status_env.from_string(status_template).render(
            historical_summary=json.dumps({"status": "ok", "padding": "x" * 255})
        ).strip()
        self.assertEqual(oversized_status, "unavailable")

    def test_dashboard_card_is_compact_and_has_required_unavailable_text(self):
        """
        Dashboard must have the historical import cost card.
        May appear on Overzicht and/or Analyse tabs.
        """
        overzicht = next((v for v in self.dashboard["views"] if v["title"] == "Overzicht"), None)
        self.assertIsNotNone(overzicht, "Overzicht view not found")
        
        # Find the cost card on Overzicht
        cards = [
            card
            for section in overzicht.get("sections", [])
            for card in section.get("cards", [])
            if card.get("type") == "markdown"
            and "Indicatieve bruto stroomafnamekosten vóór saldering"
            in card.get("content", "")
        ]
        self.assertGreaterEqual(len(cards), 1, "Cost card must exist on Overzicht tab")
        
        cost_card = cards[0]
        self.assertIn("Nog niet beschikbaar", cost_card["content"])
        self.assertIn("date", cost_card["content"])
        self.assertIn("coverage", cost_card["content"])
        self.assertEqual(
            cost_card["entity_id"],
            ["sensor.stalman_historische_importkosten"],
        )


if __name__ == "__main__":
    unittest.main()
