"""Transactional counter collector. No network, secrets or dependencies beyond Python stdlib."""
import argparse
import hashlib
import fcntl
import json
import os
import sqlite3
import tempfile
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Amsterdam')
COUNTERS = ('real_import', 'real_export', 'real_import_1', 'real_import_2',
            'real_export_1', 'real_export_2', 'sim_import', 'sim_export')


class InvalidSample(ValueError):
    pass


def timestamp(value):
    try:
        value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            raise ValueError('timezone required')
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise InvalidSample('invalid_timestamp') from exc


def numeric(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise InvalidOperation
        return result
    except InvalidOperation as exc:
        raise InvalidSample('invalid_counter') from exc


def encoded(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def validate(sample, config):
    captured = timestamp(sample['captured_at'])
    if not isinstance(sample.get('session'), str) or sample['session'].lower() in ('', 'unknown', 'unavailable', 'none'):
        raise InvalidSample('missing_ha_session')
    values, reports = {}, []
    for role in (*COUNTERS, 'tariff'):
        entity = config['entities'][role]
        state = sample['states'][entity]
        if state.get('restored') is not False:
            raise InvalidSample('restored_or_unverified_state')
        report = timestamp(state['last_reported'])
        age = (captured - report).total_seconds()
        if not 0 <= age <= config['max_age_seconds']:
            raise InvalidSample('stale_or_future_source')
        reports.append(report)
        if role != 'tariff':
            if state.get('unit') != 'kWh':
                raise InvalidSample('wrong_unit')
            values[role] = numeric(state['state'])
        else:
            code = state['state']
            if code not in config['tariff_mapping']:
                raise InvalidSample('unknown_tariff_code')
            values['tariff'] = config['tariff_mapping'][code]
            values['tariff_changed'] = timestamp(state['last_changed'])
            if values['tariff_changed'] > report:
                raise InvalidSample('invalid_tariff_timestamp')
    if (max(reports) - min(reports)).total_seconds() > config['max_skew_seconds']:
        raise InvalidSample('source_timestamp_skew')
    tolerance = numeric(config['counter_sum_tolerance_kwh'])
    for direction in ('import', 'export'):
        if abs(values['real_' + direction] - values['real_' + direction + '_1']
               - values['real_' + direction + '_2']) > tolerance:
            raise InvalidSample('p1_total_does_not_match_tariff_counters')
    return values


def interval(previous, current, config):
    before, after = validate(previous, config), validate(current, config)
    start, end = timestamp(previous['captured_at']), timestamp(current['captured_at'])
    elapsed = (end - start).total_seconds()
    if not 0 < elapsed <= config['max_interval_seconds']:
        raise InvalidSample('missing_interval')
    if previous['session'] != current['session']:
        raise InvalidSample('ha_restart')
    if before['tariff'] != after['tariff'] or after['tariff_changed'] > start:
        raise InvalidSample('tariff_transition')
    for role in COUNTERS:
        entity = config['entities'][role]
        if previous['states'][entity].get('last_reset') != current['states'][entity].get('last_reset'):
            raise InvalidSample('reset_metadata_changed')
    for role in (*COUNTERS, 'tariff'):
        entity = config['entities'][role]
        if timestamp(current['states'][entity]['last_reported']) <= timestamp(previous['states'][entity]['last_reported']):
            raise InvalidSample('source_not_reported_in_interval')
    deltas = {r: after[r] - before[r] for r in COUNTERS}
    if any(d < 0 for d in deltas.values()):
        raise InvalidSample('counter_reset_or_decrease')
    # Real tariff registers provide an independent check on the tariff assignment.
    active = next(k for k, v in config['tariff_mapping'].items() if v == after['tariff'])
    inactive = '2' if active == '1' else '1'
    if any(deltas['real_' + direction + '_' + inactive] != 0 for direction in ('import', 'export')):
        raise InvalidSample('inactive_tariff_counter_changed')
    tolerance = numeric(config['counter_sum_tolerance_kwh'])
    for direction in ('import', 'export'):
        if abs(deltas['real_' + direction] - deltas['real_' + direction + '_1']
               - deltas['real_' + direction + '_2']) > tolerance:
            raise InvalidSample('inconsistent_p1_deltas')
    if start.astimezone(TZ).date() != (end - timedelta(microseconds=1)).astimezone(TZ).date():
        raise InvalidSample('midnight_boundary_not_sampled')
    # Reject impossible jumps; limits must be explicitly set to the connection/simulator limits.
    for role in ('real_import', 'real_export', 'sim_import', 'sim_export'):
        limit = numeric(config['max_power_kw'][role]) * Decimal(str(elapsed)) / Decimal(3600)
        if deltas[role] > limit + tolerance:
            raise InvalidSample('implausible_counter_jump')
    return {'tariff': after['tariff'],
            'counter_deltas': {role: str(value) for role, value in deltas.items()},
            'measured': {d: str(deltas['real_' + d + '_' + active]) for d in ('import', 'export')},
            'simulated': {d: str(deltas['sim_' + d]) for d in ('import', 'export')}}


class Collector:
    def __init__(self, path, config):
        if config.get('mapping_confirmed') is not True or set(config.get('tariff_mapping', {})) != {'1', '2'}:
            raise InvalidSample('tariff_mapping_not_confirmed')
        if set(config['tariff_mapping'].values()) != {'normal', 'offpeak'}:
            raise InvalidSample('invalid_tariff_mapping')
        if set(config.get('entities', {})) != set((*COUNTERS, 'tariff')):
            raise InvalidSample('missing_entity_mapping')
        for key in ('max_interval_seconds', 'max_age_seconds', 'max_skew_seconds'):
            if not isinstance(config[key], (int, float)) or config[key] <= 0:
                raise InvalidSample('invalid_timing_limit')
        for role in ('real_import', 'real_export', 'sim_import', 'sim_export'):
            if numeric(config['max_power_kw'].get(role)) <= 0:
                raise InvalidSample('power_limits_not_configured')
        self.config = config
        self.fingerprint = hashlib.sha256(encoded(config).encode()).hexdigest()
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS samples (
            ts TEXT PRIMARY KEY, payload TEXT NOT NULL, valid INTEGER NOT NULL,
            reason TEXT NOT NULL, config_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS faults (ts TEXT NOT NULL, reason TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS intervals (
            end_ts TEXT PRIMARY KEY, start_ts TEXT NOT NULL, status TEXT NOT NULL,
            reason TEXT NOT NULL, data TEXT);
        ''')

    def close(self):
        self.db.close()

    def ingest(self, sample):
        ts = timestamp(sample['captured_at']).isoformat()
        raw = encoded(sample)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT payload FROM samples WHERE ts=?', (ts,)).fetchone()
            if existing:
                if existing[0] != raw:
                    self.db.execute('INSERT INTO faults VALUES (?,?)', (ts, 'conflicting_duplicate'))
                    self.db.commit()
                    raise InvalidSample('conflicting_duplicate')
                self.db.commit()
                return {'status': 'duplicate', 'captured_at': ts}
            last = self.db.execute('SELECT ts,payload,valid,config_hash FROM samples ORDER BY ts DESC LIMIT 1').fetchone()
            if last and timestamp(ts) <= timestamp(last[0]):
                raise InvalidSample('out_of_order_sample')
            valid, reason = True, ''
            try:
                validate(sample, self.config)
            except (InvalidSample, KeyError, TypeError) as exc:
                valid, reason = False, str(exc)
            data = None
            if not last:
                reason = reason or 'initial_baseline'
            elif valid and last[2] and last[3] == self.fingerprint:
                try:
                    data = interval(json.loads(last[1]), sample, self.config)
                except (InvalidSample, KeyError, TypeError) as exc:
                    reason = str(exc)
            else:
                reason = reason or ('configuration_changed' if last[3] != self.fingerprint else 'baseline_after_missing_data')
            self.db.execute('INSERT INTO samples VALUES (?,?,?,?,?)', (ts, raw, int(valid), reason, self.fingerprint))
            if last:
                self.db.execute('INSERT INTO intervals VALUES (?,?,?,?,?)',
                                (ts, last[0], 'valid' if data else 'invalid', reason, encoded(data) if data else None))
            self.db.commit()
            return {'status': 'valid' if data else 'baseline_or_invalid', 'reason': reason, 'captured_at': ts}
        except Exception:
            self.db.rollback()
            raise

    def observations(self, day_string):
        day = datetime.fromisoformat(day_string).date()
        start = datetime.combine(day, time.min, TZ).astimezone(timezone.utc)
        end = datetime.combine(day + timedelta(days=1), time.min, TZ).astimezone(timezone.utc)
        unavailable = {'scope': 'day', 'start': str(day), 'end': str(day + timedelta(days=1)),
                       'coverage_confirmed': False, 'paired_grid_deltas_confirmed': False,
                       'reason': 'no_contiguous_verified_coverage', 'without': None, 'with': None}
        # A read transaction makes the export coherent even if another process ingests a sample.
        with self.db:
            self.db.execute('BEGIN')
            first = self.db.execute('SELECT ts FROM samples ORDER BY ts LIMIT 1').fetchone()
            faults = self.db.execute('SELECT reason FROM faults WHERE ts>=? AND ts<=?',
                                     (start.isoformat(), end.isoformat())).fetchall()
            rows = self.db.execute('SELECT start_ts,end_ts,status,data,reason FROM intervals WHERE end_ts>? AND start_ts<? ORDER BY end_ts',
                                   (start.isoformat(), end.isoformat())).fetchall()
            samples = self.db.execute('SELECT config_hash FROM samples WHERE ts>=? AND ts<=?',
                                      (start.isoformat(), end.isoformat())).fetchall()
        if faults:
            unavailable['reason'] = 'conflicting_duplicate_in_period'
            return unavailable
        if not rows or any(r[0] < start.isoformat() or r[1] > end.isoformat() or r[2] != 'valid' for r in rows):
            unavailable['invalid_reasons'] = sorted({r[4] for r in rows if r[2] != 'valid'})
            return unavailable
        if any(a[1] != b[0] for a, b in zip(rows, rows[1:])):
            return unavailable
        if any(s[0] != self.fingerprint for s in samples):
            unavailable['reason'] = 'configuration_changed_in_period'
            return unavailable
        partial = rows[0][0] != start.isoformat()
        if partial and not self.config.get('allow_partial_first_day', False):
            unavailable['reason'] = 'missing_midnight_baseline'
            return unavailable
        if partial:
            # Only the first installation day may have a missing prefix, never a hidden later gap.
            if first is None or first[0] != rows[0][0]:
                return unavailable
        if self.config.get('pairing_confirmed') is not True:
            unavailable['reason'] = 'simulator_source_alignment_not_confirmed'
            return unavailable
        totals = {s: {'import_kwh': {'normal': Decimal(0), 'offpeak': Decimal(0)}, 'export_kwh': Decimal(0)}
                  for s in ('without', 'with')}
        for row in rows:
            data = json.loads(row[3])
            for scenario, source in [('without', 'measured'), ('with', 'simulated')]:
                totals[scenario]['import_kwh'][data['tariff']] += numeric(data[source]['import'])
                totals[scenario]['export_kwh'] += numeric(data[source]['export'])
        for total in totals.values():
            total['import_kwh'] = {k: str(v) for k, v in total['import_kwh'].items()}
            total['export_kwh'] = str(total['export_kwh'])
        return {**unavailable, **totals, 'reason': None, 'coverage_confirmed': True,
                'paired_grid_deltas_confirmed': True, 'billing_period_complete': False,
                'observed_until': rows[-1][1], 'measured_from': rows[0][0],
                'coverage_kind': 'contiguous_partial_day' if partial else 'from_midnight',
                'classification': 'without: measured P1; with: virtual battery simulation'}


def atomic_json(path, data):
    """Replace one complete export; leave the previous file intact on failure."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--sample', type=Path)
    parser.add_argument('--sample-url')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    collector = None
    lock = None
    try:
        lock = open(str(args.database) + '.lock', 'a')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        config = json.loads(args.config.read_text())
        sample = json.loads(unquote(args.sample_url)) if args.sample_url else json.loads(args.sample.read_text())
        collector = Collector(args.database, config)
        result = collector.ingest(sample)
        export = collector.observations(timestamp(sample['captured_at']).astimezone(TZ).date().isoformat())
        atomic_json(args.output, export)
        print(encoded(result))
    except (InvalidSample, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        # Never leave an old successful money report in place after a failed ingestion.
        atomic_json(args.output, {'coverage_confirmed': False, 'paired_grid_deltas_confirmed': False,
                                  'reason': str(exc), 'without': None, 'with': None})
        print(encoded({'status': 'unavailable', 'reason': str(exc)}))
        return 1
    finally:
        if collector:
            collector.close()
        if lock:
            lock.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
