"""Local, fail-closed energy cost comparison. No networking or HA state access."""
import argparse
import json
import hashlib
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


class Unavailable(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise Unavailable('Missing or invalid numeric value') from exc
    if not result.is_finite():
        raise Unavailable('Non-finite number')
    return result


def nonnegative(value):
    result = number(value)
    if result < 0:
        raise Unavailable('Energy and charges must be nonnegative')
    return result


def require(condition, message):
    if not condition:
        raise Unavailable(message)


def day(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise Unavailable('Missing or invalid date') from exc


def money(value):
    return str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def effective_rates(plan):
    require(plan.get('confirmed') is True, 'Contract rates and VAT not confirmed')
    if 'validity_confirmed' in plan:
        require(plan['validity_confirmed'] is True, 'Contract rate validity not confirmed')
    if 'vat_basis_confirmed' in plan:
        require(plan['vat_basis_confirmed'] is True, 'Contract VAT basis not confirmed')
    if 'discount_basis' in plan:
        require(plan['discount_basis'] == 'variable_delivery_only',
                'Unsupported discount basis')
    require(plan.get('cash_basis_confirmed') is True,
            'Export credit and costs must be confirmed as actual household cash amounts')
    vat = nonnegative(plan.get('vat_fraction'))
    require(vat <= 1, 'Invalid VAT fraction')
    discount = nonnegative(plan.get('delivery_discount_fraction'))
    require(discount <= 1, 'Invalid discount')
    rates = {}
    for tariff in ('normal', 'offpeak'):
        r = plan['import'][tariff]
        # Components are entered before discount and excluding VAT.
        delivery = nonnegative(r.get('delivery_ex_vat'))
        tax = nonnegative(r.get('energy_tax_ex_vat'))
        require(isinstance(r.get('quote_includes_vat'), bool), 'Quote VAT basis missing')
        require(isinstance(r.get('quote_includes_discount'), bool), 'Quote discount basis missing')
        quoted_delivery = delivery * (1 - discount) if r['quote_includes_discount'] else delivery
        reconstructed = (quoted_delivery + tax) * (1 + vat if r['quote_includes_vat'] else 1)
        require(abs(reconstructed - nonnegative(r.get('quoted_total'))) <= Decimal('.00001'),
                'Quoted price does not reconcile with delivery, tax, VAT and discount')
        rates[tariff] = (delivery * (1 - discount) + tax) * (1 + vat)
    return rates


def fixed_cost_fields(config, observation, start, end, measured_from, observed):
    unavailable = {
        'fixed_costs_status': 'unavailable',
        'fixed_costs_reason': 'Fixed-cost amounts, VAT basis and validity are not confirmed',
        'fixed_costs_eur': None,
        'without_total_eur': None,
        'with_total_eur': None,
    }
    fixed = config.get('fixed_daily_costs')
    if not isinstance(fixed, dict):
        return unavailable
    try:
        require(fixed.get('confirmed') is True, 'Fixed-cost amounts not confirmed')
        require(fixed.get('validity_confirmed') is True, 'Fixed-cost validity not confirmed')
        require(fixed.get('vat_basis_confirmed') is True, 'Fixed-cost VAT basis not confirmed')
        require(fixed.get('currency') == 'EUR' and fixed.get('unit') == 'per_day',
                'Unsupported fixed-cost currency or unit')
        require(fixed.get('same_for_battery_scenarios') is True,
                'Fixed costs must apply equally to both scenarios')
        valid_from, valid_until = day(fixed.get('valid_from')), day(fixed.get('valid_until'))
        require(valid_from <= start and valid_until >= end,
                'Fixed-cost plan does not cover the complete period')
        full_period_end = datetime.combine(end, datetime.min.time(), ZoneInfo('Europe/Amsterdam'))
        full_period_start = datetime.combine(start, datetime.min.time(), ZoneInfo('Europe/Amsterdam'))
        require(observation.get('scope') in ('day', 'billing'),
                'Fixed costs are not prorated for partial windows')
        require(measured_from == full_period_start and observed == full_period_end,
                'Fixed costs require observations covering the complete calendar period')
        amounts = fixed.get('amounts')
        require(isinstance(amounts, dict) and bool(amounts), 'Missing fixed-cost components')
        daily_total = sum((number(value) for value in amounts.values()), Decimal(0))
        total = daily_total * (end - start).days
        formatted = money(total)
        return {
            'fixed_costs_status': 'confirmed',
            'fixed_costs_reason': None,
            'fixed_costs_eur': formatted,
            'without_total_eur': None,
            'with_total_eur': None,
            '_fixed_costs_exact': total,
        }
    except (Unavailable, KeyError, TypeError) as exc:
        return {**unavailable, 'fixed_costs_reason': str(exc)}


def calculate(config, observation):
    require(observation.get('coverage_confirmed') is True, 'Coverage not confirmed')
    require(observation.get('paired_grid_deltas_confirmed') is True,
            'Need synchronized measured and simulated grid counter deltas, not lifetime totals')
    start, end = day(observation.get('start')), day(observation.get('end'))
    require(start < end, 'Period must be nonempty; end is exclusive')
    boundary = day(config.get('netting_ends'))
    require(not start < boundary < end, 'Split period at end of netting')
    try:
        observed = datetime.fromisoformat(observation.get('observed_until', ''))
        require(observed.tzinfo is not None, 'Observation timestamp must include timezone')
        observed = observed.astimezone(ZoneInfo('Europe/Amsterdam'))
        require(start <= observed.date() <= end, 'Observation timestamp outside period')
    except (ValueError, TypeError) as exc:
        raise Unavailable('Missing or invalid observation timestamp') from exc
    netting = start < boundary
    daily = observation.get('scope') in ('day', 'window')
    require(observation.get('scope') in ('day', 'window', 'billing'), 'Invalid scope')
    if daily:
        require(end == start + timedelta(days=1), 'Daily report must cover one calendar day')
        require(not netting, 'Annual netting cannot be calculated as a daily saving')
    else:
        require(observation.get('billing_period_complete') is True,
                'Billing result needs a complete confirmed settlement period')
        require(observed.date() == end and observed.time().isoformat().startswith('00:00:00'),
                'Billing observations must end at the exclusive end boundary')
    measured_from = timestamp_start = datetime.combine(start, datetime.min.time(), ZoneInfo('Europe/Amsterdam'))
    if observation.get('measured_from') is not None:
        try:
            measured_from = datetime.fromisoformat(observation['measured_from'])
            require(measured_from.tzinfo is not None, 'Measurement start needs timezone')
        except (TypeError, ValueError) as exc:
            raise Unavailable('Invalid measured_from') from exc
    partial = observation.get('coverage_kind') == 'contiguous_partial_day'
    require(timestamp_start <= measured_from < observed, 'Invalid measured measurement window')
    if partial:
        require(daily and measured_from > timestamp_start, 'Partial coverage only valid for explicit day segment')
    else:
        require(measured_from == timestamp_start, 'Unmarked incomplete period')
    candidates = [p for p in config.get('plans', []) if p.get('valid_from') and p.get('valid_until')
                  and day(p['valid_from']) <= start and day(p['valid_until']) >= end]
    require(len(candidates) == 1, 'Need exactly one confirmed tariff plan covering the whole period')
    plan = candidates[0]
    rates = effective_rates(plan)
    credit_rate = nonnegative(plan.get('export_credit_cash_per_kwh'))
    fee_rate = None if netting else nonnegative(plan.get('export_fee_cash_per_kwh'))
    result = {'status': 'ok', 'start': str(start), 'end': str(end), 'scope': observation['scope'],
              'classification': 'variabele kostenraming op gemeten energie; batterijscenario is simulatie',
              'netting': netting, 'plan': plan['id'], 'observed_until': observed.isoformat(), 'measured_from': measured_from.isoformat(),
              'coverage_kind': 'contiguous_partial_day' if partial else 'from_midnight'}
    totals = {}
    for scenario in ('without', 'with'):
        data = observation[scenario]
        imports = {t: nonnegative(data['import_kwh'][t]) for t in rates}
        exports = nonnegative(data['export_kwh'])
        netted = {t: Decimal(0) for t in rates}
        if netting:
            netted = {t: nonnegative(data['netted_import_kwh'][t]) for t in rates}
            require(all(netted[t] <= imports[t] for t in rates), 'Netted energy exceeds imports')
            require(sum(netted.values()) == min(sum(imports.values()), exports),
                    'Confirmed normal/offpeak netting allocation is incomplete')
            require(data.get('export_charges_confirmed') is True,
                    'Need actual contractual export fee for each full-period scenario (including bands)')
            fee = nonnegative(data.get('export_charges_eur'))
        else:
            fee = exports * fee_rate
        import_cost = sum((imports[t] - netted[t]) * rates[t] for t in rates)
        credit = (exports - sum(netted.values())) * credit_rate
        total = import_cost + fee - credit
        totals[scenario] = total
        result[scenario + '_eur'] = money(total)
        result[scenario + '_variable_eur'] = money(total)
        result[scenario + '_import_eur'] = money(import_cost)
        result[scenario + '_export_credit_eur'] = money(credit)
        result[scenario + '_export_costs_eur'] = money(fee)
    # Round only at output, not intermediate tariff/energy calculations.
    result['saving_eur'] = money(totals['without'] - totals['with'])
    fixed = fixed_cost_fields(config, observation, start, end, measured_from, observed)
    if fixed['fixed_costs_status'] == 'confirmed':
        fixed_exact = fixed.pop('_fixed_costs_exact')
        fixed['without_total_eur'] = money(totals['without'] + fixed_exact)
        fixed['with_total_eur'] = money(totals['with'] + fixed_exact)
    else:
        fixed['without_total_eur'] = None
        fixed['with_total_eur'] = None
    result.update(fixed)
    return result


def scenario_2027_totals(config, energy):
    """Apply the same assumptions to unrounded validated energy totals."""
    current = [p for p in config.get('plans', []) if p.get('id') == 'essent-2026-current-contract']
    future = [p for p in config.get('plans', []) if p.get('id') == 'essent-2027-contract']
    require(len(current) == 1 and len(future) == 1, 'Missing scenario tariff assumptions')
    current, future = current[0], future[0]
    require(current.get('discount_basis') == 'variable_delivery_only' and
            nonnegative(current.get('delivery_discount_fraction')) == Decimal('0.10'), 'Invalid discount assumption')
    rates = {}
    for tariff in ('normal', 'offpeak'):
        item = current['import'][tariff]
        require(item.get('quote_includes_vat') is True and item.get('quote_includes_discount') is False,
                'Import tariff assumption must be gross and before discount')
        delivery = nonnegative(item['user_provided_delivery_gross'])
        tax = nonnegative(item['user_provided_energy_tax_gross'])
        require(delivery + tax == nonnegative(item['quoted_total']), 'Import tariff components do not match')
        rates[tariff] = delivery * Decimal('0.90') + tax
    credit = nonnegative(future.get('export_credit_cash_per_kwh'))
    fee = nonnegative(future.get('export_fee_cash_per_kwh'))
    totals = {}
    for name in ('without', 'with'):
        values = energy[name]
        imports = {t: nonnegative(values['import_kwh'][t]) for t in rates}
        export = nonnegative(values['export_kwh'])
        totals[name] = sum(imports[t] * rates[t] for t in rates) + export * (fee - credit)
    return totals


def calculate_scenario_2027(config, observation):
    """Price a certified actual window using explicitly hypothetical 2027 terms."""
    require(observation.get('coverage_confirmed') is True, 'Coverage not confirmed')
    require(observation.get('paired_grid_deltas_confirmed') is True, 'Paired grid deltas not confirmed')
    require(observation.get('scope') == 'window', 'A certified measurement window is required')
    start, end = day(observation.get('start')), day(observation.get('end'))
    require(end == start + timedelta(days=1), 'Measurement window must belong to one day')
    try:
        measured = datetime.fromisoformat(observation.get('measured_from', ''))
        observed = datetime.fromisoformat(observation.get('observed_until', ''))
        require(measured.tzinfo is not None and observed.tzinfo is not None, 'Window timestamps require timezone')
        measured, observed = measured.astimezone(ZoneInfo('Europe/Amsterdam')), observed.astimezone(ZoneInfo('Europe/Amsterdam'))
        require(measured.date() == start and observed.date() == start and measured < observed, 'Invalid measurement window')
    except (ValueError, TypeError) as exc:
        raise Unavailable('Invalid measurement window') from exc
    coverage = observation.get('coverage_kind')
    require(coverage in ('from_midnight', 'contiguous_partial_day'), 'Invalid window coverage')
    midnight = measured.replace(hour=0, minute=0, second=0, microsecond=0)
    require((coverage == 'from_midnight') == (measured == midnight), 'Window coverage does not match start')
    totals = scenario_2027_totals(config, observation)
    return {'status': 'ok', 'classification': 'Indicatieve simulatie met 2027-aannames',
            'measured_from': measured.isoformat(), 'observed_until': observed.isoformat(),
            'without_eur': money(totals['without']), 'with_eur': money(totals['with']),
            'saving_eur': money(totals['without'] - totals['with'])}


def scenario_2027_report(config, observation):
    try:
        return calculate_scenario_2027(config, observation)
    except (Unavailable, KeyError, TypeError, ValueError) as exc:
        return {'status': 'unavailable', 'reason': str(exc),
                'classification': 'Indicatieve simulatie met 2027-aannames'}


def scenario_2027_14d(config, collector_config, db, end):
    """Validate anchored prefixes and price only complete, nonoverlapping packets."""
    from batch_contract import consume_prefix
    from collector import encoded, timestamp
    require(end.tzinfo is not None, 'Window end needs timezone')
    end = end.astimezone(ZoneInfo('UTC'))
    start = end - timedelta(hours=336)
    fingerprint = hashlib.sha256(encoded(collector_config).encode()).hexdigest()
    require(collector_config.get('audit', {}).get('enabled') is True, 'Audit is disabled')
    # The connection is supplied read-only by the CLI. Load entire generations:
    # A gap ends the validated prefix; later packets cannot re-anchor here.
    generation_ids = [r[0] for r in db.execute(
        'SELECT DISTINCT generation FROM audit_packets_v1 WHERE end_ts > ? AND end_ts <= ?',
        (start.isoformat(), end.isoformat()))]
    candidates = []
    for generation in generation_ids:
        rows = db.execute('SELECT payload,config_hash FROM audit_packets_v1 WHERE generation=? ORDER BY sequence', (generation,)).fetchall()
        try:
            if db.execute('SELECT 1 FROM audit_faults_v1 WHERE generation=? LIMIT 1', (generation,)).fetchone():
                continue
            if any(row[1] != fingerprint for row in rows):
                continue
            packets = [json.loads(row[0]) for row in rows]
            _, admitted = consume_prefix(collector_config, packets)
            for packet in admitted:
                a, b = timestamp(packet['processing_start']), timestamp(packet['processing_end'])
                if start <= a < b <= end:
                    candidates.append((a, b, packet))
        except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError):
            continue
    # All packets involved in any overlap are rejected, even across generations.
    candidates.sort(key=lambda x: (x[0], x[1]))
    overlapping = set()
    active = []
    for i, (a, b, _) in enumerate(candidates):
        active = [(j, finish) for j, finish in active if finish > a]
        for j, _ in active:
            overlapping.update((i, j))
        active.append((i, b))
    energy = {name: {'import_kwh': {'normal': Decimal(0), 'offpeak': Decimal(0)},
                     'export_kwh': Decimal(0)} for name in ('without', 'with')}
    seconds = Decimal(0)
    for i, (a, b, packet) in enumerate(candidates):
        if i in overlapping:
            continue
        duration = b - a
        seconds += Decimal(duration.days * 86400 + duration.seconds) + Decimal(duration.microseconds) / Decimal(1000000)
        tariff = collector_config['tariff_mapping'][packet['tariff_after']['code']]
        for name, key in (('without', 'measured'), ('with', 'simulated')):
            before, after = packet[key + '_before'], packet[key + '_after']
            energy[name]['import_kwh'][tariff] += nonnegative(after['import']) - nonnegative(before['import'])
            energy[name]['export_kwh'] += nonnegative(after['export']) - nonnegative(before['export'])
    if seconds == 0:
        return {'status': 'unavailable', 'reason': 'Geen gevalideerde meeturen in deze periode',
                'classification': 'Indicatieve simulatie met 2027-aannames',
                'period_start': start.isoformat(), 'period_end': end.isoformat(),
                'valid_hours': '0.00', 'coverage_percent': '0.00'}
    totals = scenario_2027_totals(config, energy)
    return {'status': 'ok', 'classification': 'Indicatieve simulatie met 2027-aannames',
            'period_start': start.isoformat(), 'period_end': end.isoformat(),
            'valid_hours': str((seconds / Decimal(3600)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
            'coverage_percent': str((seconds * 100 / Decimal(336 * 3600)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)),
            'without_eur': money(totals['without']), 'with_eur': money(totals['with']),
            'saving_eur': money(totals['without'] - totals['with'])}


def scenario_2027_14d_report(config, collector_config, db, end):
    try:
        return scenario_2027_14d(config, collector_config, db, end)
    except (Unavailable, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        return {'status': 'unavailable', 'reason': str(exc),
                'classification': 'Indicatieve simulatie met 2027-aannames'}


def report(config, observation):
    try:
        return calculate(config, observation)
    except (Unavailable, KeyError, TypeError) as exc:
        return {'status': 'unavailable', 'reason': str(exc),
                'without_eur': None, 'with_eur': None,
                'without_variable_eur': None, 'with_variable_eur': None,
                'saving_eur': None, 'fixed_costs_status': 'unavailable',
                'fixed_costs_reason': 'Variable cost calculation is unavailable',
                'fixed_costs_eur': None, 'without_total_eur': None, 'with_total_eur': None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--scenario-2027-14d', action='store_true')
    parser.add_argument('--collector-config', type=Path)
    parser.add_argument('--audit-database', type=Path)
    parser.add_argument('--scenario-2027', action='store_true')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        if args.scenario_2027_14d:
            if not args.collector_config or not args.audit_database:
                raise ValueError('Collector config and audit database required')
            collector_config = json.loads(args.collector_config.read_text())
            with sqlite3.connect(args.audit_database.resolve().as_uri() + '?mode=ro', uri=True) as db:
                db.execute('BEGIN')
                result = scenario_2027_14d_report(config, collector_config, db, datetime.now(ZoneInfo('UTC')))
        else:
            if not args.input:
                raise ValueError('Observation input required')
            calculate_report = scenario_2027_report if args.scenario_2027 else report
            result = calculate_report(config, json.loads(args.input.read_text()))
    except (OSError, ValueError, sqlite3.Error) as exc:
        result = {'status': 'unavailable', 'reason': str(exc),
                  'without_eur': None, 'with_eur': None,
                  'without_variable_eur': None, 'with_variable_eur': None,
                  'saving_eur': None, 'fixed_costs_status': 'unavailable',
                  'fixed_costs_reason': 'Variable cost calculation is unavailable',
                  'fixed_costs_eur': None, 'without_total_eur': None, 'with_total_eur': None}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
