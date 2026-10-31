"""Source-aware diagnostic collection; no timestamp-only financial pairing.

The installed Battery Simulator does not publish the P1 counters it processed.
Consequently observations() deliberately cannot produce billable paired input.
"""
import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Amsterdam')
GROUPS = {
    'measured_p1': ('real_import', 'real_export', 'real_import_1', 'real_import_2',
                    'real_export_1', 'real_export_2', 'tariff'),
    'simulated_marstek': ('sim_import', 'sim_export'),
}
COUNTERS = tuple(role for roles in GROUPS.values() for role in roles if role != 'tariff')


class InvalidSample(ValueError):
    pass


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
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


def read_source(sample, config, source):
    """Validate observed states, without interpreting old timestamps as outages."""
    captured = timestamp(sample['captured_at'])
    result = {'values': {}, 'metadata': {}}
    for role in GROUPS[source]:
        state = sample['states'][config['entities'][role]]
        if state.get('restored') is not False:
            raise InvalidSample('restored_or_unverified_state')
        reported = timestamp(state['last_reported'])
        updated = timestamp(state['last_updated'])
        if not updated <= reported <= captured:
            raise InvalidSample('invalid_or_future_source_timestamp')
        value = state['state']
        if role == 'tariff':
            if value not in ('1', '2'):
                raise InvalidSample('unknown_tariff_code')
            changed = timestamp(state['last_changed'])
            if changed > reported:
                raise InvalidSample('invalid_tariff_timestamp')
        else:
            if state.get('unit') != 'kWh':
                raise InvalidSample('wrong_unit')
            value = str(numeric(value))
        result['values'][role] = value
        result['metadata'][role] = {
            'last_reported': reported.isoformat(), 'last_updated': updated.isoformat(),
            'last_reset': state.get('last_reset'),
        }
    if source == 'measured_p1':
        tolerance = numeric(config['counter_sum_tolerance_kwh'])
        v = result['values']
        for direction in ('import', 'export'):
            if abs(numeric(v['real_' + direction]) - numeric(v['real_' + direction + '_1'])
                   - numeric(v['real_' + direction + '_2'])) > tolerance:
                raise InvalidSample('p1_total_does_not_match_tariff_counters')
    latest = max(timestamp(m['last_reported']) for m in result['metadata'].values())
    result['recent_activity_observed'] = (captured - latest).total_seconds() <= config['sources'][source]['activity_age_seconds']
    # This describes activity only. It is never a proof of a live unchanged counter.
    result['classification'] = 'measured' if source == 'measured_p1' else 'simulated'
    result['certified_processed_window'] = False
    return result


def describe_change(previous_sample, current_sample, previous, current, config, source):
    """Counter differences between observations, not synchronized energy intervals."""
    elapsed = (timestamp(current_sample['captured_at']) - timestamp(previous_sample['captured_at'])).total_seconds()
    if previous_sample['session'] != current_sample['session']:
        raise InvalidSample('ha_restart')
    if elapsed > config['max_observation_gap_seconds']:
        raise InvalidSample('missing_observation_interval')
    deltas, changed_reports = {}, []
    for role in GROUPS[source]:
        before, after = previous['metadata'][role], current['metadata'][role]
        if timestamp(after['last_reported']) < timestamp(before['last_reported']):
            raise InvalidSample('source_timestamp_regressed')
        if timestamp(after['last_updated']) < timestamp(before['last_updated']):
            raise InvalidSample('source_timestamp_regressed')
        if after['last_reported'] != before['last_reported']:
            changed_reports.append(role)
        if role == 'tariff':
            continue
        if after['last_reset'] != before['last_reset']:
            raise InvalidSample('reset_metadata_changed')
        delta = numeric(current['values'][role]) - numeric(previous['values'][role])
        if delta < 0:
            raise InvalidSample('counter_reset_or_decrease')
        if delta != 0 and after['last_updated'] == before['last_updated']:
            raise InvalidSample('counter_changed_without_updated_timestamp')
        deltas[role] = str(delta)
    changed = any(Decimal(value) != 0 for value in deltas.values())
    return {
        'status': 'counter_changed' if changed else 'reported_unchanged' if changed_reports else 'unchanged_observation',
        # No repeated old report is exported as a verified zero-energy interval.
        'observed_counter_deltas': deltas if changed or changed_reports else None,
        'new_reports': changed_reports,
        'tariff_code': current['values'].get('tariff'),
        'tariff_mapping': config.get('tariff_mapping') if config.get('mapping_confirmed') is True else None,
        'certified_processed_window': False,
    }


class Collector:
    def __init__(self, path, config):
        expected = set((*COUNTERS, 'tariff'))
        if set(config.get('entities', {})) != expected:
            raise InvalidSample('missing_entity_mapping')
        if len(set(config['entities'].values())) != len(expected):
            raise InvalidSample('duplicate_entity_mapping')
        if config.get('schema_version') != 2:
            raise InvalidSample('source_aware_config_required')
        if numeric(config.get('max_observation_gap_seconds')) <= 0:
            raise InvalidSample('invalid_observation_gap_limit')
        numeric(config['counter_sum_tolerance_kwh'])
        for source in GROUPS:
            if numeric(config['sources'][source]['activity_age_seconds']) <= 0:
                raise InvalidSample('invalid_activity_limit')
        if config.get('mapping_confirmed') is True and (
                set(config['tariff_mapping']) != {'1', '2'} or
                set(config['tariff_mapping'].values()) != {'normal', 'offpeak'}):
            raise InvalidSample('invalid_tariff_mapping')
        self.config = config
        self.fingerprint = hashlib.sha256(encoded(config).encode()).hexdigest()
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        # New tables preserve the complete v1 journal; none of its intervals are promoted.
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS snapshots_v2 (
            ts TEXT PRIMARY KEY, payload TEXT NOT NULL, config_hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS source_observations_v2 (
            ts TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
            state TEXT, change_data TEXT, PRIMARY KEY (ts, source));
          CREATE TABLE IF NOT EXISTS faults_v2 (ts TEXT NOT NULL, reason TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def ingest(self, sample):
        ts = timestamp(sample['captured_at']).isoformat()
        if not isinstance(sample.get('session'), str) or sample['session'].lower() in ('', 'unknown', 'unavailable', 'none'):
            raise InvalidSample('missing_ha_session')
        raw = encoded(sample)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT payload FROM snapshots_v2 WHERE ts=?', (ts,)).fetchone()
            if existing:
                if existing[0] != raw:
                    self.db.execute('INSERT INTO faults_v2 VALUES (?,?)', (ts, 'conflicting_duplicate'))
                    self.db.commit()
                    raise InvalidSample('conflicting_duplicate')
                self.db.commit()
                return {'status': 'duplicate', 'captured_at': ts}
            last = self.db.execute('SELECT ts,payload,config_hash FROM snapshots_v2 ORDER BY ts DESC LIMIT 1').fetchone()
            if last and timestamp(ts) <= timestamp(last[0]):
                raise InvalidSample('out_of_order_sample')
            result = {'status': 'collected_unpaired', 'captured_at': ts, 'sources': {}}
            for source in GROUPS:
                state, change, reason = None, None, None
                status = 'baseline'
                try:
                    state = read_source(sample, self.config, source)
                    if last:
                        prior = self.db.execute('SELECT state FROM source_observations_v2 WHERE ts=? AND source=?',
                                                (last[0], source)).fetchone()
                        if last[2] != self.fingerprint:
                            status, reason = 'discontinuity', 'configuration_changed'
                        elif prior and prior[0] is not None:
                            try:
                                change = describe_change(json.loads(last[1]), sample, json.loads(prior[0]), state, self.config, source)
                                status = change['status']
                            except InvalidSample as exc:
                                status, reason = 'discontinuity', str(exc)
                        else:
                            status, reason = 'baseline', 'baseline_after_missing_source'
                except (InvalidSample, KeyError, TypeError) as exc:
                    status, reason = 'unavailable', str(exc)
                self.db.execute('INSERT INTO source_observations_v2 VALUES (?,?,?,?,?,?)',
                                (ts, source, status, reason, encoded(state) if state else None,
                                 encoded(change) if change else None))
                result['sources'][source] = {'status': status, 'reason': reason,
                                            'recent_activity_observed': state['recent_activity_observed'] if state else None}
            self.db.execute('INSERT INTO snapshots_v2 VALUES (?,?,?)', (ts, raw, self.fingerprint))
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def observations(self, day_string):
        """No manual flag, cadence or last_reported comparison can bypass this gate.

        A future implementation needs simulator-origin batch IDs, consumed P1
        counter boundaries and atomic simulated outputs before adding pairing.
        """
        day = datetime.fromisoformat(day_string).date()
        return {'scope': 'day', 'start': str(day), 'end': str(day + timedelta(days=1)),
                'coverage_confirmed': False, 'paired_grid_deltas_confirmed': False,
                'reason': 'simulator_processed_p1_window_unavailable', 'without': None, 'with': None,
                'classification': 'independent measured and simulated observations; not paired'}


def atomic_json(path, data):
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
    collector, lock = None, None
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
