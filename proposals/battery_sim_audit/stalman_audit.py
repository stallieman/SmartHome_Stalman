"""PROPOSED instrumentation for the exact upstream v2.9.0 source.

No battery calculations, scheduling, source events or settings are modified.
This file is NOT an installed custom integration. Audit failures fail closed.
"""
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from datetime import datetime as RealDateTime
from decimal import Decimal, InvalidOperation
from functools import wraps
from uuid import uuid4

PRODUCER = 'stalman_audit_v1'
HELPER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
UPSTREAM_SHA256 = 'a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6'
EVENT = 'battery_sim_stalman_audit_batch'


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('invalid counter')
    return result


def stamp(value):
    if not isinstance(value, RealDateTime) or value.tzinfo is None:
        raise ValueError('missing source timestamp')
    return value.astimezone(timezone.utc).isoformat()


class Audit:
    def __init__(self, handle):
        if getattr(handle, '_solar_entity_id', None) is not None:
            raise ValueError('additional solar-cap input requires its own acceptance audit')
        self.handle = handle
        self.generation = uuid4().hex
        self.sequence = 0
        self.valid = True
        self.reason = None
        self.endpoints = {}
        self.pending = []
        self.window_start = max(datetime.now(timezone.utc), datetime.fromtimestamp(handle._last_battery_update_time, timezone.utc)).isoformat()
        self.last_processing = handle._last_battery_update_time
        self.tariff_start = self.tariff()
        self.register_start = self.registers()
        self.inputs = {}
        self.mapping = {'Import': 'import', 'Export': 'export'}
        for item in handle._inputs:
            role = self.mapping[item['sensor_type']]
            if role in self.inputs:
                raise ValueError('multiple meters unsupported')
            self.inputs[role] = item
        if set(self.inputs) != {'import', 'export'}:
            raise ValueError('one import and one export meter required')
        for role, item in self.inputs.items():
            state = handle._hass.states.get(item['sensor_id'])
            self.endpoints[role] = self.read(state)
        for role in self.inputs:
            if sum(dec(v) for v in self.register_start[role].values()) != dec(self.endpoints[role]['counter']):
                raise ValueError('initial tariff registers do not identify the source counter')
        # No pre-existing accumulation may be silently assigned to this anchor.
        if handle._accumulated_import_reading or handle._accumulated_export_reading:
            raise ValueError('pending source readings before audit anchor')

    @staticmethod
    def read(state):
        if state is None or state.attributes.get('restored', False):
            raise ValueError('missing/restored source')
        unit = state.attributes.get('unit_of_measurement')
        if unit not in ('kWh', 'Wh'):
            raise ValueError('unsupported source unit')
        value = dec(state.state) / (1000 if unit == 'Wh' else 1)
        return {'counter': str(value), 'at': stamp(state.last_updated), 'reset': state.attributes.get('last_reset')}

    def taint(self, reason):
        self.valid = False
        self.reason = reason

    def reading(self, event, before, after):
        role = next((role for role, item in self.inputs.items()
                     if item['sensor_id'] == event.data.get('entity_id')), None)
        if role is None:
            return
        old = self.read(event.data.get('old_state'))
        new = self.read(event.data.get('new_state'))
        if dec(old['counter']) != dec(self.endpoints[role]['counter']):
            raise ValueError('discontinuous source event chain')
        if old.get('reset') != new.get('reset'):
            raise ValueError('source reset metadata changed')
        delta = dec(new['counter']) - dec(old['counter'])
        if delta < 0:
            raise ValueError('source counter reset')
        accepted = Decimal(str(after[role])) - Decimal(str(before[role]))
        if abs(accepted - delta) > Decimal('0.00000001'):
            raise ValueError('handler did not accept exact source delta')
        self.pending.append({'role': role, 'old': old, 'new': new})
        self.endpoints[role] = new

    def tariff(self):
        state = self.handle._hass.states.get('sensor.p1_meter_tarief')
        if state is None:
            return None
        return {'code': state.state, 'last_changed': stamp(state.last_changed)}

    def registers(self):
        return {direction: {code: self.read(self.handle._hass.states.get(
            'sensor.p1_meter_energie_' + direction + '_tarief_' + code))['counter']
            for code in ('1', '2')} for direction in ('import', 'export')}

    def simulation(self):
        return {role: str(dec(self.handle._sensors[item['simulated_sensor']]))
                for role, item in self.inputs.items()}

    def before(self):
        return {'processing_at': self.handle._last_battery_update_time,
                'consumed_endpoints': {k: dict(v) for k, v in self.endpoints.items()},
                'simulated': self.simulation(),
                'pending_import': self.handle._accumulated_import_reading,
                'pending_export': self.handle._accumulated_export_reading}

    def completed(self, before, source_start):
        after_time = self.handle._last_battery_update_time
        if after_time == before['processing_at']:
            return  # minimum-delay branch; calculation did not run
        self.sequence += 1
        self.last_processing = after_time
        changes = {role: sum((dec(e['new']['counter']) - dec(e['old']['counter'])
                              for e in self.pending if e['role'] == role), Decimal(0))
                   for role in self.inputs}
        for role in self.inputs:
            if abs(changes[role] - Decimal(str(before['pending_' + role]))) > Decimal('0.00000001'):
                self.taint('accumulated source deltas do not match audited events')
            if self.handle._sensors[self.inputs[role]['simulated_sensor']] is None:
                self.taint('simulated source not initialized')
        if self.handle._accumulated_import_reading or self.handle._accumulated_export_reading:
            self.taint('processing did not drain audited inputs')
        packet = {'producer': PRODUCER, 'upstream_sha256': UPSTREAM_SHA256, 'helper_sha256': HELPER_SHA256,
                  'battery_id': self.handle._entry_id, 'generation': self.generation,
                  'sequence': self.sequence, 'valid': self.valid, 'reason': self.reason,
                  'processing_start': self.window_start,
                  'model_time_start': datetime.fromtimestamp(before['processing_at'], timezone.utc).isoformat(),
                  'processing_end': datetime.fromtimestamp(after_time, timezone.utc).isoformat(),
                  'sources': {role: item['sensor_id'] for role, item in self.inputs.items()},
                  'source_boundaries_before': source_start,
                  'source_boundaries_after': {k: dict(v) for k, v in self.endpoints.items()},
                  'measured_before': {role: endpoint['counter'] for role, endpoint in source_start.items()},
                  'measured_after': {role: endpoint['counter'] for role, endpoint in self.endpoints.items()},
                  'simulated_before': before['simulated'], 'simulated_after': self.simulation(),
                  'tariff_registers_before': self.register_start, 'tariff_registers_after': self.registers(),
                  'accepted_events': list(self.pending), 'tariff_before': self.tariff_start, 'tariff_after': self.tariff()}
        # Publish one atomic packet; do not reconstruct it from separate entity updates.
        self.handle._hass.bus.async_fire(EVENT, packet)
        self.window_start = packet['processing_end']
        self.register_start = packet['tariff_registers_after']
        self.tariff_start = packet['tariff_after']
        self.pending.clear()
        self.batch_start = {k: dict(v) for k, v in self.endpoints.items()}
        # Do not reprice an ambiguous prefix. Start a NEW explicit observation
        # window after the original calculation has drained its inputs.
        from zoneinfo import ZoneInfo
        local = ZoneInfo('Europe/Amsterdam')
        start_day = RealDateTime.fromisoformat(packet['processing_start']).astimezone(local).date()
        end_day = RealDateTime.fromisoformat(packet['processing_end']).astimezone(local).date()
        tariff_changed = packet['tariff_before'] != packet['tariff_after']
        source_crossed_day = any(e['old']['counter'] != e['new']['counter'] and
            (RealDateTime.fromisoformat(e['old']['at']).astimezone(local).date() != end_day or
             RealDateTime.fromisoformat(e['new']['at']).astimezone(local).date() != end_day)
            for e in packet['accepted_events'])
        tariff = packet['tariff_after']
        tariff_invalid = tariff is None or tariff.get('code') not in ('1', '2')
        if not tariff_invalid:
            changed_at = RealDateTime.fromisoformat(tariff['last_changed'])
            tariff_invalid = any(e['old']['counter'] != e['new']['counter'] and
                RealDateTime.fromisoformat(e['old']['at']) < changed_at for e in packet['accepted_events'])
        register_mismatch = any(sum(dec(v) for v in packet['tariff_registers_after'][role].values()) != dec(packet['measured_after'][role]) for role in ('import', 'export'))
        if register_mismatch or not self.valid or start_day != end_day or tariff_changed or source_crossed_day or tariff_invalid:
            reanchor(self.handle)


def reanchor(handle):
    try:
        audit = Audit(handle)
        audit.batch_start = {k: dict(v) for k, v in audit.endpoints.items()}
        handle._stalman_audit = audit
    except Exception:
        handle._stalman_audit = None


def get_audit(handle):
    return getattr(handle, '_stalman_audit', None)


def audit_tracking(original):
    @wraps(original)
    def wrapped(handle, *args, **kwargs):
        try:
            handle._stalman_audit = Audit(handle)
            handle._stalman_audit.batch_start = {k: dict(v) for k, v in handle._stalman_audit.endpoints.items()}
        except Exception:
            handle._stalman_audit = None
        return original(handle, *args, **kwargs)
    return wrapped


def audit_reading(original):
    @wraps(original)
    def wrapped(handle, event, *args, **kwargs):
        audit = get_audit(handle)
        before = {'import': handle._accumulated_import_reading, 'export': handle._accumulated_export_reading}
        # Original exceptions and return value retain their normal behavior.
        try:
            result = original(handle, event, *args, **kwargs)
        except Exception:
            if audit:
                audit.taint('source handler failed')
            raise
        if audit:
            try:
                audit.reading(event, before, {'import': handle._accumulated_import_reading,
                                             'export': handle._accumulated_export_reading})
            except Exception:
                audit.taint('invalid, missing or reset source event')
        return result
    return wrapped


def audit_processing(original):
    @wraps(original)
    def wrapped(handle, *args, **kwargs):
        audit = get_audit(handle)
        before = None
        original_time = handle._last_battery_update_time
        if audit:
            try:
                before = audit.before()
            except Exception:
                audit.taint('missing simulated baseline')
        try:
            result = original(handle, *args, **kwargs)
        except Exception:
            if audit:
                audit.taint('simulation processing failed')
            raise
        if (audit is None or before is None) and handle._last_battery_update_time != original_time:
            reanchor(handle)
        if audit and before:
            try:
                audit.completed(before, audit.batch_start)
            except Exception:
                audit.taint('audit packet could not be completed or published')
        return result
    return wrapped


def audit_reset(original):
    @wraps(original)
    def wrapped(handle, *args, **kwargs):
        audit = get_audit(handle)
        if audit:
            audit.taint('simulator reset; new audit anchor required')
        return original(handle, *args, **kwargs)
    return wrapped
