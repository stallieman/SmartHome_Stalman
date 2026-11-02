"""Indicative gross import costs from Home Assistant hourly statistics.

The caller obtains statistics through Home Assistant's supported
``recorder.get_statistics`` action. This module does not access Recorder,
Home Assistant state, export energy, or battery simulation data.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

try:
    from .compare import Unavailable, effective_rates, nonnegative, require
except ImportError:  # Direct command-line execution from /config/energy_finance.
    from compare import Unavailable, effective_rates, nonnegative, require


LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
HOUR = timedelta(hours=1)
DEFAULT_MEASUREMENT_START = "2026-10-30T20:36:47+01:00"


def parse_boundary(value: str) -> datetime:
    """Parse a local date or a timezone-aware ISO datetime."""
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.min, LOCAL_TZ)
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise Unavailable("Invalid period boundary") from exc
    require(result.tzinfo is not None, "Period boundary must include a timezone")
    return result


def utc_hour_floor(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


def utc_hour_ceil(value: datetime) -> datetime:
    floor = utc_hour_floor(value)
    return floor if value.astimezone(timezone.utc) == floor else floor + HOUR


def iso(value: datetime) -> str:
    return value.isoformat()


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def statistic_ids(config: dict) -> dict[str, str]:
    mapping = config.get("p1_tariff_mapping", {})
    require(mapping.get("confirmed") is True, "P1 tariff mapping not confirmed")
    codes = mapping.get("codes")
    require(
        isinstance(codes, dict)
        and set(codes) == {"1", "2"}
        and set(codes.values()) == {"normal", "offpeak"},
        "Invalid P1 tariff mapping",
    )
    return {
        tariff: f"sensor.p1_meter_energie_import_tarief_{code}"
        for code, tariff in codes.items()
    }


def select_plan(config: dict, instant: datetime, explicit_plan_id: str | None) -> tuple[dict, str]:
    plans = config.get("plans", [])
    if explicit_plan_id:
        matches = [plan for plan in plans if plan.get("id") == explicit_plan_id]
        require(len(matches) == 1, "Explicit indicative tariff plan not found or duplicated")
        scenario_year = matches[0].get("scenario_year")
        require(
            type(scenario_year) is int and instant.astimezone(LOCAL_TZ).year == scenario_year,
            "Explicit indicative plan cannot be used outside its scenario year",
        )
        return matches[0], "explicit_indicative_plan"

    local_day = instant.astimezone(LOCAL_TZ).date()
    matches = []
    for plan in plans:
        try:
            start = date.fromisoformat(plan["valid_from"])
            end = date.fromisoformat(plan["valid_until"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= local_day < end:
            matches.append(plan)
    require(len(matches) == 1, "Need exactly one dated tariff plan for every complete hour")
    return matches[0], "dated_plan"


def indicative_rates(plan: dict) -> dict[str, Decimal]:
    """Reuse compare.py's exact reconstruction without claiming confirmation."""
    candidate = copy.deepcopy(plan)
    candidate["confirmed"] = True
    candidate["validity_confirmed"] = True
    candidate["vat_basis_confirmed"] = True
    candidate["cash_basis_confirmed"] = True
    return effective_rates(candidate)


def tariff_confirmation(plan: dict) -> dict[str, bool]:
    return {
        "contract_rates": plan.get("confirmed") is True,
        "validity": plan.get("validity_confirmed") is True,
        "vat_basis": plan.get("vat_basis_confirmed") is True,
        "cash_basis": plan.get("cash_basis_confirmed") is True,
    }


def parse_rows(payload: dict, entity_id: str) -> tuple[dict[datetime, Decimal], list[str]]:
    statistics = payload.get("statistics")
    require(isinstance(statistics, dict), "Recorder response has no statistics object")
    source = statistics.get(entity_id)
    require(isinstance(source, list), f"Missing statistic: {entity_id}")
    rows: dict[datetime, Decimal] = {}
    duplicates = []
    for row in source:
        try:
            start = datetime.fromisoformat(row["start"])
            end = datetime.fromisoformat(row["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Unavailable(f"Invalid statistic timestamp: {entity_id}") from exc
        require(start.tzinfo is not None and end.tzinfo is not None,
                "Statistic timestamps must include a timezone")
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        require(end - start == HOUR and start == utc_hour_floor(start),
                "Statistics must be complete UTC hour buckets")
        if start in rows:
            duplicates.append(iso(start))
            continue
        rows[start] = nonnegative(row.get("change"))
    return rows, duplicates


def _unavailable(reason: str, start: datetime | None = None, end: datetime | None = None) -> dict:
    return {
        "status": "unavailable",
        "classification": "indicatief",
        "reason": reason,
        "requested_start": iso(start) if start else None,
        "requested_end": iso(end) if end else None,
        "normal": {"kwh": None, "cost_eur": None},
        "offpeak": {"kwh": None, "cost_eur": None},
        "total_eur": None,
        "coverage": {"status": "invalid"},
    }


def calculate(
    config: dict,
    recorder_response: dict,
    start_value: str,
    end_value: str,
    measurement_start_value: str = DEFAULT_MEASUREMENT_START,
    explicit_plan_id: str | None = None,
) -> dict:
    """Calculate indicative costs for fully covered hourly buckets only."""
    start = end = None
    try:
        start, end = parse_boundary(start_value), parse_boundary(end_value)
        measurement_start = parse_boundary(measurement_start_value)
        require(start < end, "Period must be nonempty")
        ids = statistic_ids(config)
        normal_rows, normal_duplicates = parse_rows(recorder_response, ids["normal"])
        offpeak_rows, offpeak_duplicates = parse_rows(recorder_response, ids["offpeak"])

        effective_start = max(start, measurement_start)
        first_hour = utc_hour_ceil(effective_start)
        last_boundary = utc_hour_floor(end)
        expected = []
        cursor = first_hour
        while cursor < last_boundary:
            expected.append(cursor)
            cursor += HOUR

        missing = [
            iso(hour) for hour in expected
            if hour not in normal_rows or hour not in offpeak_rows
        ]
        duplicate_hours = sorted(set(normal_duplicates + offpeak_duplicates))

        partial_hours = []
        leading_floor = utc_hour_floor(effective_start)
        if effective_start.astimezone(timezone.utc) != leading_floor:
            partial_hours.append({
                "start": iso(leading_floor),
                "end": iso(leading_floor + HOUR),
                "reason": "measurement_or_requested_period_starts_inside_hour",
            })
        trailing_floor = utc_hour_floor(end)
        if end.astimezone(timezone.utc) != trailing_floor:
            partial_hours.append({
                "start": iso(trailing_floor),
                "end": iso(trailing_floor + HOUR),
                "reason": "requested_period_ends_inside_hour",
            })

        require(bool(expected), "No complete hours inside requested and measured period")
        require(not duplicate_hours, "Duplicate hourly statistics")
        require(not missing, "Missing hourly statistics")

        energy = {"normal": Decimal(0), "offpeak": Decimal(0)}
        costs = {"normal": Decimal(0), "offpeak": Decimal(0)}
        used_plans: dict[str, dict] = {}
        selection_modes = set()
        for hour in expected:
            plan, selection_mode = select_plan(config, hour, explicit_plan_id)
            selection_modes.add(selection_mode)
            rates = indicative_rates(plan)
            used_plans[plan["id"]] = plan
            for tariff, rows in (("normal", normal_rows), ("offpeak", offpeak_rows)):
                energy[tariff] += rows[hour]
                costs[tariff] += rows[hour] * rates[tariff]

        confirmations = {
            plan_id: tariff_confirmation(plan) for plan_id, plan in used_plans.items()
        }
        all_confirmed = all(all(flags.values()) for flags in confirmations.values())
        coverage_status = "partial" if partial_hours else "complete"
        return {
            "status": "ok",
            "classification": "indicatief",
            "reason": None,
            "requested_start": iso(start),
            "requested_end": iso(end),
            "measurement_available_from": iso(measurement_start),
            "calculated_from": iso(first_hour),
            "calculated_until": iso(last_boundary),
            "normal": {
                "statistic_id": ids["normal"],
                "kwh": decimal_text(energy["normal"]),
                "cost_eur": money(costs["normal"]),
            },
            "offpeak": {
                "statistic_id": ids["offpeak"],
                "kwh": decimal_text(energy["offpeak"]),
                "cost_eur": money(costs["offpeak"]),
            },
            "total_eur": money(costs["normal"] + costs["offpeak"]),
            "cost_scope": "gross_import_before_netting_complete_hours_only",
            "excluded_cost_components": [
                "netting", "export_credit", "export_fees", "fixed_costs", "battery_saving"
            ],
            "tariff_plans": list(used_plans),
            "tariff_selection": sorted(selection_modes),
            "tariff_confirmation": confirmations,
            "contractually_confirmed": all_confirmed,
            "coverage": {
                "status": coverage_status,
                "complete_hours": len(expected),
                "missing_hours": [],
                "duplicate_hours": [],
                "excluded_partial_hours": partial_hours,
                "statistics_period": "hour",
                "statistics_type": "change",
                "statistics_timezone": "UTC",
                "display_timezone": "Europe/Amsterdam",
            },
        }
    except (Unavailable, KeyError, TypeError) as exc:
        result = _unavailable(str(exc), start, end)
        if start and end:
            result["coverage"] = {
                "status": "incomplete",
                "missing_hours": locals().get("missing", []),
                "duplicate_hours": locals().get("duplicate_hours", []),
                "excluded_partial_hours": locals().get("partial_hours", []),
            }
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--statistics-url", required=True)
    parser.add_argument("--start-url", required=True)
    parser.add_argument("--end-url", required=True)
    parser.add_argument("--measurement-start", default=DEFAULT_MEASUREMENT_START)
    parser.add_argument("--plan-id")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        statistics = json.loads(unquote(args.statistics_url))
        result = calculate(
            config,
            statistics,
            unquote(args.start_url),
            unquote(args.end_url),
            args.measurement_start,
            args.plan_id,
        )
    except (OSError, ValueError) as exc:
        result = _unavailable(str(exc))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] in {"ok", "unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
