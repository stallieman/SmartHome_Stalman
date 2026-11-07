"""Diagnostic evidence for simulator processing, never a financial certification."""
from datetime import datetime
from decimal import Decimal
import math
from uuid import uuid4


def valid_counter(state):
    """Return a non-restored energy counter in kWh, or no baseline."""
    if state is None or state.attributes.get('restored', False):
        return None
    factor = {'kWh': 1.0, 'Wh': 0.001}.get(state.attributes.get('unit_of_measurement'))
    if factor is None:
        return None
    try:
        value = float(state.state) * factor
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


class IntervalAudit:
    def __init__(self, battery_id):
        self.battery_id = battery_id
        self.generation = uuid4().hex
        self.sequence = 0
        self.events = []
        self.faults = []
        self.last = {}
        self.start = None
        self.tariff = None

    def seed(self, role, value):
        """Establish a baseline only when no accepted reading supplied one."""
        if role in ('import', 'export') and role not in self.last and value is not None:
            self.last[role] = value

    def invalidate(self, role, reason):
        self.last.pop(role, None)
        self.faults.append(reason)

    def reading(self, role, entity, old, new, old_at, new_at, old_reset=None, new_reset=None):
        if role not in ('import', 'export'):
            self.faults.append('unsupported_source')
            return
        if new < old or (role in self.last and self.last[role] != old):
            self.faults.append('counter_reset_or_gap')
        self.events.append({'role': role, 'entity': entity, 'old': old, 'new': new,
                            'old_at': old_at, 'new_at': new_at,
                            'old_reset': old_reset, 'new_reset': new_reset})
        self.last[role] = new

    def fault(self, reason):
        self.faults.append(reason)

    def finish(self, end, simulated_before, simulated_after, tariff):
        before = dict(self.last)
        for event in reversed(self.events):
            before[event['role']] = event['old']
        after = dict(self.last)
        reasons = list(self.faults)
        if self.start is None or set(before) != {'import', 'export'}:
            reasons.append('missing_baseline')
        if set(simulated_before) != {'import', 'export'} or set(simulated_after) != {'import', 'export'}:
            reasons.append('missing_simulated_counter')
        if not self.tariff or not tariff or self.tariff['code'] not in ('1', '2') or self.tariff != tariff:
            reasons.append('tariff_unverified_or_changed')
        elif self.start and datetime.fromisoformat(tariff['last_changed']) > datetime.fromisoformat(self.start):
            reasons.append('tariff_changed_during_interval')
        extra = None
        if 'import' in before and 'import' in after and 'import' in simulated_before and 'import' in simulated_after:
            # Compare decimal representations consistently with the audit contract.
            delta = ((Decimal(str(simulated_after['import'])) - Decimal(str(simulated_before['import'])))
                     - (Decimal(str(after['import'])) - Decimal(str(before['import']))))
            extra = float(max(Decimal(0), delta))
            if delta > Decimal('0.000000001'):
                reasons.append('extra_grid_charging_unallocated')
        self.sequence += 1
        packet = {'battery_id': self.battery_id, 'generation': self.generation, 'sequence': self.sequence,
                  'processing_start': self.start, 'processing_end': end,
                  'measured_before': before, 'measured_after': after, 'accepted_events': self.events,
                  'simulated_before': simulated_before, 'simulated_after': simulated_after,
                  'tariff_before': self.tariff, 'tariff_after': tariff,
                  'extra_grid_import_kwh': extra, 'financially_certified': False,
                  'reasons': reasons}
        self.start, self.tariff, self.events, self.faults = end, tariff, [], []
        return packet
