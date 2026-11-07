"""Build fail-closed audit packets from simulator boundaries and source events."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

SOURCE_ENTITIES = {'import': 'sensor.p1_meter_energie_import', 'export': 'sensor.p1_meter_energie_export'}
REGISTER_ENTITIES = {role: {code: f'sensor.p1_meter_energie_{role}_tarief_{code}'
                             for code in ('1', '2')} for role in ('import', 'export')}
TZ = ZoneInfo('Europe/Amsterdam')
# One billionth kWh is one million times smaller than the P1 meter's 0.001 kWh step.
IMPORT_ROUNDING_TOLERANCE_KWH = Decimal('0.000000001')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0:
            return None
        return n
    except (InvalidOperation, ValueError, TypeError):
        return None


def helper_digest():
    """Pin both the contract producer and the diagnostic event capture code."""
    root = Path(__file__).parent
    return hashlib.sha256((root / 'audit_producer.py').read_bytes() + b'\0' +
                          (root / 'interval_audit.py').read_bytes()).hexdigest()


def calculate_digests(source_path):
    """Read and hash the current files in a worker, once per published packet."""
    return digest(source_path), helper_digest()


async def async_publish_packet(hass, lock, source_path, packet):
    """Hash in an executor and publish in order only after both reads succeed."""
    async with lock:
        source_hash, helper_hash = await hass.async_add_executor_job(calculate_digests, source_path)
        packet = {**packet, 'upstream_sha256': source_hash, 'helper_sha256': helper_hash}
        hass.bus.async_fire('battery_sim_stalman_audit_batch', packet)


def source_state(state):
    """Capture a real HA state; invalid/restored states cannot anchor a boundary."""
    if state is None or state.attributes.get('restored', False):
        return None
    factor = {'kWh': Decimal(1), 'Wh': Decimal('0.001')}.get(state.attributes.get('unit_of_measurement'))
    value = number(state.state)
    if factor is None or value is None:
        return None
    return {'counter': str(value * factor), 'at': state.last_updated.isoformat(),
            'reset': state.attributes.get('last_reset')}


def capture(states, sources, now):
    """Capture source and register states without estimating missing values."""
    if sources != SOURCE_ENTITIES:
        return None
    values = {role: source_state(states.get(entity)) for role, entity in sources.items()}
    registers = {role: {code: source_state(states.get(entity)) for code, entity in entries.items()}
                 for role, entries in REGISTER_ENTITIES.items()}
    tariff_state = states.get('sensor.p1_meter_tarief')
    if any(v is None for v in values.values()) or any(v is None for x in registers.values() for v in x.values()):
        return None
    if tariff_state is None or tariff_state.attributes.get('restored', False) or tariff_state.state not in ('1', '2'):
        return None
    try:
        end = datetime.fromisoformat(now)
        for s in [*values.values(), *(v for x in registers.values() for v in x.values())]:
            if datetime.fromisoformat(s['at']) > end:
                return None
        tariff = {'code': tariff_state.state, 'last_changed': tariff_state.last_changed.isoformat()}
        if datetime.fromisoformat(tariff['last_changed']) > end:
            return None
    except (ValueError, TypeError):
        return None
    for role in values:
        if sum(Decimal(x['counter']) for x in registers[role].values()) != Decimal(values[role]['counter']):
            return None
    return {'at': now, 'sources': sources, 'measured': values, 'registers': registers, 'tariff': tariff}


class AuditProducer:
    def __init__(self, battery_id, source_path):
        self.battery_id = battery_id
        self.source_path = source_path
        self.previous = None
        self.generation = None
        self.sequence = 0
        self.last_packet = None

    def finish(self, diagnostic, boundary):
        """Return a contract packet only with complete, contiguous evidence."""
        previous, self.previous = self.previous, boundary
        try:
            if previous is None or boundary is None or diagnostic['reasons']:
                raise ValueError('missing or invalid boundary')
            if previous['at'] != diagnostic['processing_start'] or boundary['at'] != diagnostic['processing_end']:
                raise ValueError('boundary timestamp mismatch')
            start, end = (datetime.fromisoformat(diagnostic[k]) for k in ('processing_start', 'processing_end'))
            if start >= end or start.astimezone(TZ).date() != end.astimezone(TZ).date():
                raise ValueError('invalid processing window')
            if previous['tariff'] != boundary['tariff'] or datetime.fromisoformat(boundary['tariff']['last_changed']) > start:
                raise ValueError('tariff change')
            before = {r: v['counter'] for r, v in previous['measured'].items()}
            after = {r: v['counter'] for r, v in boundary['measured'].items()}
            for role in ('import', 'export'):
                if number(diagnostic['measured_before'].get(role)) != Decimal(before[role]) or number(diagnostic['measured_after'].get(role)) != Decimal(after[role]):
                    raise ValueError('processed source mismatch')
                if previous['measured'][role]['reset'] != boundary['measured'][role]['reset']:
                    raise ValueError('source reset')
                for code in ('1', '2'):
                    a, b = previous['registers'][role][code], boundary['registers'][role][code]
                    if a['reset'] != b['reset'] or Decimal(b['counter']) < Decimal(a['counter']):
                        raise ValueError('register reset')
            reg_before = {r: {c: x['counter'] for c, x in v.items()} for r, v in previous['registers'].items()}
            reg_after = {r: {c: x['counter'] for c, x in v.items()} for r, v in boundary['registers'].items()}
            used = [c for c in ('1', '2') if Decimal(reg_after['import'][c]) > Decimal(reg_before['import'][c])]
            if len(used) > 1 or (used and used[0] != boundary['tariff']['code']):
                raise ValueError('ambiguous tariff')
            sim_before, sim_after = diagnostic['simulated_before'], diagnostic['simulated_after']
            if any(number(sim_before.get(r)) is None or number(sim_after.get(r)) is None or
                   number(sim_after[r]) < number(sim_before[r]) for r in ('import', 'export')):
                raise ValueError('invalid simulated counters')
            if number(sim_after['import']) - number(sim_before['import']) > Decimal(after['import']) - Decimal(before['import']) + IMPORT_ROUNDING_TOLERANCE_KWH:
                raise ValueError('unallocated extra import')
            endpoints = {r: Decimal(v) for r, v in before.items()}
            events = []
            for event in diagnostic['accepted_events']:
                role = event['role']
                if role not in endpoints or event['entity'] != boundary['sources'][role]:
                    raise ValueError('wrong source')
                old, new = number(event['old']), number(event['new'])
                if old is None or new is None or old != endpoints[role] or new < old or event['old_reset'] != event['new_reset'] or event['old_reset'] != previous['measured'][role]['reset']:
                    raise ValueError('invalid event')
                old_at, new_at = datetime.fromisoformat(event['old_at']), datetime.fromisoformat(event['new_at'])
                if old_at > new_at or new_at > end or (new > old and (old_at.astimezone(TZ).date() != start.astimezone(TZ).date() or new_at.astimezone(TZ).date() != start.astimezone(TZ).date())):
                    raise ValueError('invalid event time')
                endpoints[role] = new
                events.append({'role': role, 'old': {'counter': str(old), 'at': event['old_at'], 'reset': event['old_reset']},
                               'new': {'counter': str(new), 'at': event['new_at'], 'reset': event['new_reset']}})
            if any(endpoints[r] != Decimal(after[r]) for r in endpoints):
                raise ValueError('unexplained source delta')
            if self.last_packet and (self.last_packet['processing_end'] != diagnostic['processing_start'] or
                                     self.last_packet['measured_after'] != before or self.last_packet['simulated_after'] != sim_before):
                raise ValueError('discontinuous chain')
            if self.generation is None:
                self.generation, self.sequence = uuid4().hex, 0
            self.sequence += 1
            packet = {'producer': 'stalman_audit_v1', 'battery_id': self.battery_id, 'valid': True,
                      'generation': self.generation, 'sequence': self.sequence,
                      'processing_start': diagnostic['processing_start'], 'processing_end': diagnostic['processing_end'],
                      'sources': boundary['sources'], 'tariff_before': previous['tariff'], 'tariff_after': boundary['tariff'],
                      'tariff_registers_before': reg_before, 'tariff_registers_after': reg_after,
                      'measured_before': before, 'measured_after': after,
                      'simulated_before': sim_before, 'simulated_after': sim_after, 'accepted_events': events}
            self.last_packet = packet
            return packet
        except (KeyError, TypeError, ValueError, InvalidOperation):
            self.generation, self.sequence, self.last_packet = None, 0, None
            return None
