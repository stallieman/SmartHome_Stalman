"""Local, fail-closed energy cost comparison. No networking or HA state access."""
import argparse
import json
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
              'classification': 'schatting op gemeten energie; batterijvariant is simulatie',
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
        result[scenario + '_import_eur'] = money(import_cost)
        result[scenario + '_export_credit_eur'] = money(credit)
        result[scenario + '_export_costs_eur'] = money(fee)
    # Round only at output, not intermediate tariff/energy calculations.
    result['saving_eur'] = money(totals['without'] - totals['with'])
    return result


def report(config, observation):
    try:
        return calculate(config, observation)
    except (Unavailable, KeyError, TypeError) as exc:
        return {'status': 'unavailable', 'reason': str(exc),
                'without_eur': None, 'with_eur': None, 'saving_eur': None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = report(json.loads(args.config.read_text()), json.loads(args.input.read_text()))
    except (OSError, ValueError) as exc:
        result = {'status': 'unavailable', 'reason': str(exc),
                  'without_eur': None, 'with_eur': None, 'saving_eur': None}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
