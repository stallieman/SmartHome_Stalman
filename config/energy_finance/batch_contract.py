"""Strict consumer for PROPOSED atomic simulator audit packets.
No time-nearness matching, no physical/simulated interpolation.
Disabled by default; the installed upstream integration cannot produce this protocol.
"""
from datetime import timedelta
from decimal import Decimal
try:
    from .collector import InvalidSample, numeric, timestamp, TZ
except ImportError:
    from collector import InvalidSample, numeric, timestamp, TZ

# Legacy field name upstream_sha256 identifies the installed instrumented simulator source.
# Bound float-counter noise only; 1e-9 kWh is 10^-6 of a 0.001 kWh P1 step.
IMPORT_ROUNDING_TOLERANCE_KWH = Decimal('0.000000001')
SOURCE_SHA = 'df0022ed0f8d2bbca3ee015c801527483046d869f3d129081e36dc35bdc9d429'


def require(condition, reason):
    if not condition:
        raise InvalidSample(reason)


def consume(config, batches):
    """Return only one contiguous, explicitly labelled certified window in a day.

    Invalid/missing batches are not discarded to make a report look complete.
    Producer identity is a trusted local-integration contract, not cryptographic proof.
    """
    policy = config.get('audit', {})
    require(policy.get('enabled') is True and bool(policy.get('battery_id')), 'audit_producer_not_approved')
    require(config.get('mapping_confirmed') is True, 'tariff_mapping_not_confirmed')
    mapping = config['tariff_mapping']
    require(set(mapping) == {'1', '2'} and set(mapping.values()) == {'normal', 'offpeak'}, 'invalid_tariff_mapping')
    require(bool(batches), 'no_audit_batches')
    totals = {s: {'import_kwh': {'normal': Decimal(0), 'offpeak': Decimal(0)}, 'export_kwh': Decimal(0)}
              for s in ('without', 'with')}
    previous = None
    first_start = timestamp(batches[0]['processing_start'])
    day = first_start.astimezone(TZ).date()
    for batch in batches:
        require(batch.get('producer') == 'stalman_audit_v1' and batch.get('upstream_sha256') == SOURCE_SHA,
                'unrecognized_audit_producer')
        require(bool(policy.get('expected_helper_sha256')) and batch.get('helper_sha256') == policy['expected_helper_sha256'], 'unapproved_audit_helper')
        require(batch.get('battery_id') == policy['battery_id'], 'wrong_battery')
        require(batch.get('valid') is True, 'tainted_audit_batch')
        require(isinstance(batch.get('generation'), str) and bool(batch['generation']), 'missing_generation')
        require(type(batch.get('sequence')) is int and batch['sequence'] > 0, 'invalid_sequence')
        start, end = timestamp(batch['processing_start']), timestamp(batch['processing_end'])
        require(start < end, 'invalid_processing_window')
        require(start.astimezone(TZ).date() == day and end.astimezone(TZ).date() == day,
                'day_boundary_requires_explicit_settlement')
        require(batch['sources'] == {'import': config['entities']['real_import'], 'export': config['entities']['real_export']},
                'wrong_source_meters')
        tariff = batch.get('tariff_after')
        require(isinstance(tariff, dict) and isinstance(batch.get('tariff_before'), dict), 'missing_tariff_proof')
        require(tariff == batch['tariff_before'] and tariff.get('code') in mapping, 'ambiguous_tariff_batch')
        changed = timestamp(tariff['last_changed'])
        require(changed <= start, 'tariff_transition_in_processing_window')
        register_deltas = {}
        for role in ('import', 'export'):
            before_regs, after_regs = batch['tariff_registers_before'][role], batch['tariff_registers_after'][role]
            require(set(before_regs) == {'1', '2'} and set(after_regs) == {'1', '2'}, 'missing_tariff_registers')
            require(sum(numeric(v) for v in before_regs.values()) == numeric(batch['measured_before'][role]), 'registers_do_not_identify_consumed_start')
            require(sum(numeric(v) for v in after_regs.values()) == numeric(batch['measured_after'][role]), 'registers_do_not_identify_consumed_end')
            register_deltas[role] = {code: numeric(after_regs[code]) - numeric(before_regs[code]) for code in mapping}
            require(all(delta >= 0 for delta in register_deltas[role].values()), 'tariff_register_reset')
        used_codes = [code for code, delta in register_deltas['import'].items() if delta > 0]
        require(len(used_codes) <= 1, 'mixed_tariff_model_batch_cannot_be_allocated')
        require(not used_codes or used_codes == [tariff['code']], 'active_tariff_disagrees_with_p1_registers')
        real_import = numeric(batch['measured_after']['import']) - numeric(batch['measured_before']['import'])
        sim_import = numeric(batch['simulated_after']['import']) - numeric(batch['simulated_before']['import'])
        require(sim_import <= real_import + IMPORT_ROUNDING_TOLERANCE_KWH, 'additional_simulated_grid_charging_has_no_register_allocation')
        if previous:
            require(batch['generation'] == previous['generation'], 'generation_changed')
            require(batch['sequence'] == previous['sequence'] + 1, 'missing_or_duplicate_batch')
            require(start == timestamp(previous['processing_end']), 'processing_gap')
            for key in ('measured', 'simulated'):
                require(batch[key + '_before'] == previous[key + '_after'], 'counter_boundary_discontinuity')
        else:
            require(batch['sequence'] == 1, 'missing_first_batch')
        endpoints = {role: numeric(batch['measured_before'][role]) for role in ('import', 'export')}
        for event in batch['accepted_events']:
            role = event['role']
            require(role in endpoints, 'unknown_source_role')
            require(event['old'].get('reset') == event['new'].get('reset'), 'source_reset_metadata_changed')
            old, new = numeric(event['old']['counter']), numeric(event['new']['counter'])
            require(old == endpoints[role] and new >= old, 'missing_event_or_counter_reset')
            old_at, new_at = timestamp(event['old']['at']), timestamp(event['new']['at'])
            require(old_at <= new_at <= end, 'invalid_source_event_window')
            if new > old:
                require(old_at.astimezone(TZ).date() == day and new_at.astimezone(TZ).date() == day,
                        'source_interval_crosses_day_boundary')
            endpoints[role] = new
        for role in endpoints:
            require(endpoints[role] == numeric(batch['measured_after'][role]), 'unexplained_measured_delta')
        for scenario, key in [('without', 'measured'), ('with', 'simulated')]:
            deltas = {role: numeric(batch[key + '_after'][role]) - numeric(batch[key + '_before'][role])
                      for role in ('import', 'export')}
            require(all(v >= 0 for v in deltas.values()), 'simulated_or_measured_reset')
            totals[scenario]['import_kwh'][mapping[tariff['code']]] += deltas['import']
            totals[scenario]['export_kwh'] += deltas['export']
        previous = batch
    observed = timestamp(previous['processing_end'])
    partial = any((first_start.astimezone(TZ).hour, first_start.astimezone(TZ).minute,
                   first_start.astimezone(TZ).second, first_start.microsecond))
    for total in totals.values():
        total['import_kwh'] = {k: str(v) for k, v in total['import_kwh'].items()}
        total['export_kwh'] = str(total['export_kwh'])
    return {**totals, 'scope': 'window', 'start': str(day), 'end': str(day + timedelta(days=1)),
            'observed_until': observed.isoformat(), 'measured_from': first_start.isoformat(),
            'coverage_kind': 'contiguous_partial_day' if partial else 'from_midnight',
            'coverage_confirmed': True, 'paired_grid_deltas_confirmed': True,
            'billing_period_complete': False,
            'classification': 'certified simulator processing window; not whole-day or invoice costs'}


def consume_prefix(config, batches):
    """Validate the contiguous prefix from sequence one; never re-anchor after a gap.

    Duplicate or out-of-order numbers invalidate the generation, including its
    prefix. All other existing checks are applied unchanged by consume().
    """
    require(bool(batches), 'no_audit_batches')
    sequences = [batch['sequence'] for batch in batches]
    require(all(type(n) is int and n > 0 for n in sequences), 'invalid_sequence')
    require(all(a < b for a, b in zip(sequences, sequences[1:])), 'duplicate_or_out_of_order_batch')
    prefix_length = 0
    for number in sequences:
        if number != prefix_length + 1:
            break
        prefix_length += 1
    require(prefix_length > 0, 'missing_first_batch')
    prefix = batches[:prefix_length]
    return consume(config, prefix), prefix
