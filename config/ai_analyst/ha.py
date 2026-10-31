"""Read-only HA statistics collection; report_date is the target local calendar day.

The caller supplies yesterday's date, credentials and validated configuration.
No external sharing or persistence happens here. websocket-client is imported only
on connection. Exceptions intentionally contain no provider-controlled content.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = dt.timezone.utc
HOUR_MS = 3_600_000
COMMANDS = frozenset({"get_states", "recorder/list_statistic_ids", "recorder/statistics_during_period"})


class HAError(RuntimeError):
    """Unsafe configuration or unexpected websocket protocol; abort the report."""


class HASourceError(HAError):
    """A sanitized transport or recorder failure that can be reported per sensor."""


class HAClient:
    """Synchronous, single-consumer websocket client with an explicit read allowlist."""

    def __init__(self, base_url, token, timeout=30):
        try:
            parts = urlsplit(base_url)
            port = parts.port
            if (parts.scheme not in {"http", "https", "ws", "wss"}
                    or not parts.hostname or parts.username is not None
                    or parts.password is not None or parts.query or parts.fragment
                    or any(c.isspace() or ord(c) < 32 for c in base_url)
                    or "\\" in base_url or "%" in parts.netloc):
                raise ValueError
            if port is not None and not 1 <= port <= 65535:
                raise ValueError
            path = parts.path.rstrip("/") + "/api/websocket"
            self._url = urlunsplit(("wss" if parts.scheme in {"https", "wss"} else "ws",
                                    parts.netloc, path, "", ""))
        except (TypeError, ValueError, AttributeError):
            raise HAError("Ongeldige Home Assistant-verbindingsconfiguratie.") from None
        if not isinstance(token, str) or not token or any(ord(c) < 32 for c in token):
            raise HAError("Ongeldige Home Assistant-authenticatieconfiguratie.")
        if _number(timeout) is None or timeout <= 0:
            raise HAError("Ongeldige verbindingstime-out.")
        self._token = token
        self._timeout = timeout
        self._socket = None
        self._next_id = 0

    def __enter__(self):
        if self._socket is not None:
            raise HAError("Verbinding is al geopend.")
        try:
            import websocket
            self._socket = websocket.create_connection(
                self._url, timeout=self._timeout, redirect_limit=0, suppress_origin=True)
            # A redirect response must never receive an authentication frame.
            if self._socket.getstatus() != 101:
                raise HAError("Websocket-upgrade geweigerd; redirects zijn niet toegestaan.")
            if self._receive().get("type") != "auth_required":
                raise HAError("Onverwachte authenticatievolgorde.")
            self._send({"type": "auth", "access_token": self._token})
            if self._receive().get("type") != "auth_ok":
                raise HAError("Home Assistant-authenticatie geweigerd.")
            return self
        except ImportError:
            self.__exit__(None, None, None)
            raise HAError("Ontbrekende dependency: websocket-client>=1.8,<2.") from None
        except HAError:
            self.__exit__(None, None, None)
            raise
        except Exception:
            self.__exit__(None, None, None)
            raise HASourceError("Home Assistant-verbinding niet beschikbaar.") from None

    def __exit__(self, exc_type, exc_value, traceback):
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        return False

    def _receive(self):
        try:
            raw = self._socket.recv()
        except Exception:
            raise HASourceError("Home Assistant-antwoord niet beschikbaar.") from None
        try:
            frame = json.loads(raw, parse_constant=lambda _: None)
        except (ValueError, TypeError, UnicodeError):
            raise HAError("Ongeldig Home Assistant-protocolbericht.") from None
        if not isinstance(frame, dict):
            raise HAError("Ongeldig Home Assistant-protocolbericht.")
        return frame

    def _send(self, message):
        try:
            self._socket.send(json.dumps(message, allow_nan=False))
        except Exception:
            raise HASourceError("Home Assistant-verzoek niet verzonden.") from None

    def command(self, kind, **kwargs):
        allowed = {
            "get_states": set(),
            "recorder/list_statistic_ids": {"statistic_type"},
            "recorder/statistics_during_period": {
                "start_time", "end_time", "statistic_ids", "period", "types"},
        }
        if not isinstance(kind, str) or kind not in COMMANDS or set(kwargs) - allowed[kind]:
            raise HAError("Alleen toegestane leesopdrachten zijn beschikbaar.")
        if kind == "recorder/list_statistic_ids":
            statistic_type = kwargs.get("statistic_type", "sum")
            if not isinstance(statistic_type, str) or statistic_type not in {"sum", "mean"}:
                raise HAError("Ongeldig statistiekverzoek.")
        if kind == "recorder/statistics_during_period":
            try:
                ids, types = kwargs["statistic_ids"], kwargs["types"]
                start, end = (dt.datetime.fromisoformat(kwargs[key]) for key in ("start_time", "end_time"))
                if (not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids)
                        or not isinstance(types, list) or not types
                        or any(not isinstance(t, str) or t not in {"change", "mean", "min", "max"} for t in types)
                        or kwargs["period"] != "hour" or start.utcoffset() != dt.timedelta(0)
                        or end.utcoffset() != dt.timedelta(0) or end <= start):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise HAError("Ongeldig statistiekverzoek.") from None
        if self._socket is None:
            raise HAError("Home Assistant-verbinding is niet geopend.")
        self._next_id += 1
        self._send({"id": self._next_id, "type": kind, **kwargs})
        frame = self._receive()
        if (frame.get("type") != "result" or type(frame.get("id")) is not int
                or frame["id"] != self._next_id or type(frame.get("success")) is not bool):
            raise HAError("Onverwacht Home Assistant-opdrachtantwoord.")
        if not frame["success"]:
            raise HASourceError("Home Assistant-leesopdracht mislukt.")
        if "result" not in frame:
            raise HAError("Home Assistant-resultaat ontbreekt.")
        return frame["result"]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounds(day, zone):
    start = dt.datetime.combine(day, dt.time(), zone).astimezone(UTC)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), zone).astimezone(UTC)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _daily(rows, days, zone, sensor):
    bounds = [_bounds(day, zone) for day in days]
    expected = {ts: index for index, (start, end) in enumerate(bounds)
                for ts in range(start, end, HOUR_MS)}
    buckets, seen = {}, set()
    errors = [dict() for _ in days]

    def error(index, reason):
        errors[index][reason] = errors[index].get(reason, 0) + 1

    if not isinstance(rows, list):
        rows = []
        for index in range(len(days)):
            error(index, "invalid_statistics")
    for row in rows:
        start = _number(row.get("start")) if isinstance(row, dict) else None
        if start is None or start not in expected:
            for index in range(len(days)):
                error(index, "unexpected_bucket")
            continue
        index = expected[start]
        if start in seen:
            buckets.pop(start, None)
            error(index, "duplicate_bucket")
            continue
        seen.add(start)
        end = _number(row.get("end"))
        if end != start + HOUR_MS:
            error(index, "invalid_bucket_end")
            continue
        if ("unit_of_measurement" in row and row["unit_of_measurement"] != sensor["unit"]
                or "unit" in row and row["unit"] != sensor["unit"]):
            error(index, "wrong_unit")
            continue
        fields = ["change"] if sensor["kind"] == "total_increasing" else ["mean", "min", "max"]
        values = [_number(row.get(field)) for field in fields]
        if any(value is None for value in values):
            error(index, "invalid_numeric_value")
        elif sensor["kind"] == "total_increasing" and values[0] < 0:
            error(index, "negative_counter_change")
        elif sensor["kind"] == "measurement" and not values[1] <= values[0] <= values[2]:
            error(index, "invalid_measurement_range")
        else:
            buckets[start] = values
    result = []
    for index, (start, end) in enumerate(bounds):
        values = [buckets[ts] for ts in range(start, end, HOUR_MS) if ts in buckets]
        hours = (end - start) // HOUR_MS
        reasons = errors[index]
        if len(values) != hours:
            reasons["missing_or_invalid_hours"] = hours - len(values)
        quality = {"status": "incomplete", "reason": ",".join(sorted(reasons)) or "complete_hourly_buckets",
                   "expected_hours": hours, "valid_hours": len(values), "counts": reasons}
        daily = {"value": None, "quality": quality}
        if not reasons:
            try:
                value = (math.fsum(v[0] for v in values) if sensor["kind"] == "total_increasing"
                         else statistics.mean(v[0] for v in values))
            except OverflowError:
                value = math.inf
            if math.isfinite(value):
                daily["value"] = value
                quality["status"] = "ok"
                if sensor["kind"] == "measurement":
                    daily.update(min=min(v[1] for v in values), max=max(v[2] for v in values))
            else:
                quality["reason"] = "numeric_overflow"
        result.append(daily)
    return result


def _comparison(history, target, count):
    values = [day["value"] for day in history[-count:] if day["value"] is not None]
    result = {"complete_days": len(values), "expected_days": count,
              "mean": None, "median": None, "change_pct": None,
              "reason": "incomplete_baseline"}
    if len(values) == count:
        mean = statistics.mean(values)
        median = statistics.mean((statistics.median_low(values), statistics.median_high(values)))
        result.update(mean=mean, median=median, reason="complete_baseline")
        if target is not None and mean != 0:
            change = (target / mean - 1) * 100
            result["change_pct"] = change if math.isfinite(change) else None
    return result


def collect(config, client, report_date: dt.date) -> dict:
    """Collect target day plus preceding 30 local days, never raw entity attributes.

    client.command(kind, **kwargs) returns the unwrapped HA result. Source errors
    use HASourceError (generic exceptions are sanitized too); HAError aborts on
    configuration/protocol failures. Only JSON-safe, finite aggregates are emitted.
    """
    try:
        if type(report_date) is not dt.date or config["timezone"] != "Europe/Amsterdam":
            raise ValueError
        zone = ZoneInfo(config["timezone"])
        sensors = config["sensors"]
        if not isinstance(sensors, list):
            raise ValueError
        aliases = set()
        for sensor in sensors:
            if (not isinstance(sensor, dict)
                    or any(not isinstance(sensor.get(key), str) or not sensor[key]
                           for key in ("id", "entity_id", "statistic_id", "label", "unit", "kind"))
                    or sensor["kind"] not in {"total_increasing", "measurement"}
                    or type(sensor.get("share_with_ai")) is not bool or sensor["id"] in aliases):
                raise ValueError
            aliases.add(sensor["id"])
        days = [report_date - dt.timedelta(days=offset) for offset in range(30, -1, -1)]
        start, _ = _bounds(days[0], zone)
        target_start, end = _bounds(report_date, zone)
    except (KeyError, TypeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        raise HAError("Ongeldige collectorconfiguratie of rapportdatum.") from None

    def request(kind, **kwargs):
        try:
            return client.command(kind, **kwargs), False
        except HASourceError:
            return None, True
        except HAError:
            raise
        except Exception:
            return None, True

    metadata, metadata_error = request("recorder/list_statistic_ids")
    states, states_error = request("get_states")
    if metadata is not None and not isinstance(metadata, list):
        raise HAError("Ongeldig statistiekmetadata-antwoord.")
    if states is not None and not isinstance(states, list):
        raise HAError("Ongeldig actuele-statusantwoord.")
    metadata_map, duplicate_ids = {}, set()
    for item in metadata or []:
        if isinstance(item, dict) and isinstance(item.get("statistic_id"), str):
            key = item["statistic_id"]
            if key in metadata_map:
                duplicate_ids.add(key)
            metadata_map[key] = item
    state_map = {item["entity_id"]: item for item in states or []
                 if isinstance(item, dict) and isinstance(item.get("entity_id"), str)}
    prepared = []
    for sensor in sensors:
        meta = metadata_map.get(sensor["statistic_id"])
        state = state_map.get(sensor["entity_id"])
        current_status = "source_error" if states_error else "missing"
        wrong_current_unit = False
        if state is not None:
            current_state = state.get("state")
            unavailable = current_state is None or current_state == "unknown" or current_state == "unavailable"
            current_status = "unavailable" if unavailable else "available"
            attrs = state.get("attributes")
            actual_unit = attrs.get("unit_of_measurement") if isinstance(attrs, dict) else None
            wrong_current_unit = actual_unit is not None and actual_unit != sensor["unit"]
            if wrong_current_unit and not unavailable:
                current_status = "wrong_unit"
            elif current_status == "available" and actual_unit is None:
                current_status = "unit_missing"
        reason = None
        capability = "has_sum" if sensor["kind"] == "total_increasing" else "has_mean"
        if metadata_error:
            reason = "metadata_source_error"
        elif meta is None:
            reason = "metadata_missing"
        elif sensor["statistic_id"] in duplicate_ids:
            reason = "duplicate_metadata"
        elif meta.get("statistics_unit_of_measurement") != sensor["unit"]:
            reason = "metadata_wrong_unit"
        elif meta.get(capability) is not True:
            reason = "unsupported_statistics"
        elif wrong_current_unit and current_status != "unavailable":
            reason = "current_wrong_unit"
        prepared.append((sensor, current_status, reason))
    data_by_kind = {}
    for kind in ("total_increasing", "measurement"):
        ids = list(dict.fromkeys(s["statistic_id"] for s, _, reason in prepared
                                 if s["kind"] == kind and reason is None))
        if not ids:
            continue
        data, failed = request("recorder/statistics_during_period",
                               start_time=_iso(dt.datetime.fromtimestamp(start / 1000, UTC)),
                               end_time=_iso(dt.datetime.fromtimestamp(end / 1000, UTC)),
                               statistic_ids=ids, period="hour",
                               types=["change"] if kind == "total_increasing" else ["mean", "min", "max"])
        if not failed and not isinstance(data, dict):
            raise HAError("Ongeldig historische-statistiekenantwoord.")
        data_by_kind[kind] = (data, failed)
    output = []
    for sensor, current_status, reason in prepared:
        data, failed = data_by_kind.get(sensor["kind"], ({}, False))
        if reason is None and failed:
            reason = "statistics_source_error"
        daily = _daily(data.get(sensor["statistic_id"], []) if data and reason is None else [], days, zone, sensor)
        if reason is not None:
            for day in daily:
                day["quality"].update(status="unavailable", reason=reason)
        item = {key: sensor[key] for key in ("id", "label", "unit", "kind", "share_with_ai")}
        item.update(daily[-1])
        item["quality"]["current_status"] = current_status
        item["comparison_7d"] = _comparison(daily[:-1], item["value"], 7)
        item["comparison_30d"] = _comparison(daily[:-1], item["value"], 30)
        # A simple, explicitly labelled population-standard-deviation rule.
        baseline = [d["value"] for d in daily[:-1] if d["value"] is not None]
        anomaly = {"method": "30d_population_stddev_3sigma", "baseline_days": len(baseline),
                   "is_anomaly": None, "reason": "incomplete_baseline"}
        if len(baseline) == 30 and item["value"] is not None:
            mean = item["comparison_30d"]["mean"]
            try:
                deviation = statistics.pstdev(baseline)
                difference = abs(item["value"] - mean)
                anomaly.update(is_anomaly=difference > 3 * deviation,
                               reason="complete_baseline" if deviation else "constant_baseline")
            except (OverflowError, ValueError):
                anomaly["reason"] = "numeric_overflow"
        item["anomaly"] = anomaly
        output.append(item)
    return {"schema_version": 1, "date": report_date.isoformat(), "timezone": config["timezone"],
            "period": {"start": _iso(dt.datetime.fromtimestamp(target_start / 1000, UTC)),
                       "end": _iso(dt.datetime.fromtimestamp(end / 1000, UTC))},
            "sensors": output,
            "limitations": ["Volledige uurbuckets bewijzen geen ononderbroken sensorbeschikbaarheid.",
                            "Dagwaarden vereisen alle uurbuckets; ontbrekende data is geen nul.",
                            "Vergelijkingen gebruiken uitsluitend de voorafgaande volledige kalenderdagen.",
                            "Actuele beschikbaarheid zegt niets over historische beschikbaarheid.",
                            "Afwijkingen zijn eenvoudige statistische signalen, geen oorzaakanalyse."]}
