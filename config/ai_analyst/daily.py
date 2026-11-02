"""One-shot, read-only Home Assistant reporting; secrets come from the environment."""
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import fcntl
import hashlib
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

MODEL = 'gpt-4.1-mini'
INPUT_PRICE = Decimal('0.40')
OUTPUT_PRICE = Decimal('1.60')
MONTH_LIMIT = Decimal('0.50')
TZ = ZoneInfo('Europe/Amsterdam')
DAYS = ('maandag', 'dinsdag', 'woensdag', 'donderdag', 'vrijdag', 'zaterdag', 'zondag')
MONTHS = ('januari', 'februari', 'maart', 'april', 'mei', 'juni', 'juli', 'augustus',
          'september', 'oktober', 'november', 'december')
# An observation needs a relative and an absolute deviation, so small totals never look dramatic.
RELATIVE_THRESHOLD = Decimal('0.25')
ABSOLUTE_THRESHOLD = {'kWh': 1.0, 'm³': 0.5}
NIGHT_ABSOLUTE_THRESHOLD = 0.3
NIGHT_SHARE_MINIMUM = (0.25, 0.4)  # share of the day's import, and kWh
PEAK_SHARE_MINIMUM = (0.20, 0.75)
MAX_OBSERVATIONS = 2
MAX_CANDIDATES = 4
MAX_TEXT = 160
DIRECTION_WORDS = {'hoger': ('hoger', 'boven', 'meer', 'hoog'), 'lager': ('lager', 'onder', 'minder', 'laag')}
# The AI describes measurements only; it never explains causes, gives tips or mentions devices or money.
FORBIDDEN = re.compile(
    r'\b(?:oorza\w*|veroorzaak\w*|doordat|omdat|vanwege|waarschijnlijk|wasmachine|droger|vaatwasser|kook\w*|oven|'
    r'verwarming|airco|warmtepomp|boiler|elektrische auto|laadpaal|apparaat|apparaten|batterij\w*|bespaar\w*|'
    r'besparing\w*|tips?|advies|adviseer\w*|controleer\w*|euro|kosten|geld|sensor\w*|dekking|statistiek\w*|'
    r'validatie|https?)\b|[€$<>*_`\\]')


class ConfigError(ValueError):
    pass


class DeliveryError(RuntimeError):
    """A transport failure is ambiguous unless the provider rejected the request."""
    def __init__(self, message, uncertain=True):
        super().__init__(message)
        self.uncertain = uncertain


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def http_json(url, payload, headers=None):
    request = Request(url, data=json_bytes(payload), headers={
        'Content-Type': 'application/json', **(headers or {})}, method='POST')
    try:
        with build_opener(NoRedirect).open(request, timeout=45) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise DeliveryError('Antwoord van externe dienst is te groot.')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except HTTPError as exc:
        # Never include response bodies or request URLs (Telegram embeds the token).
        exc.close()
        raise DeliveryError(f'Externe dienst gaf HTTP {exc.code}.', uncertain=exc.code >= 500) from None
    except (URLError, TimeoutError, OSError, ValueError, HTTPException):
        raise DeliveryError('Externe dienst gaf geen geldig antwoord; levering is onzeker.') from None


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ConfigError('Configuratie ontbreekt of is geen geldige JSON.') from None
    if not isinstance(config, dict) or config.get('timezone') != 'Europe/Amsterdam':
        raise ConfigError('timezone moet Europe/Amsterdam zijn.')
    url = config.get('ha_url', '')
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
        valid = valid and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
        _ = parsed.port
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ConfigError('ha_url moet een HTTP(S)-basisadres zonder credentials, pad of query zijn.')
    for key in ('ha_token', 'api_key', 'openai_api_key', 'telegram_token', 'password'):
        if key in config:
            raise ConfigError('Geheimen horen uitsluitend in omgevingsvariabelen, niet in JSON.')
    sensors = config.get('sensors')
    if not isinstance(sensors, list) or not 1 <= len(sensors) <= 24:
        raise ConfigError('Configureer één tot vierentwintig sensoren.')
    seen = set()
    for sensor in sensors:
        if not isinstance(sensor, dict):
            raise ConfigError('Elke sensor moet een object zijn.')
        sid = sensor.get('id', '')
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,39}', sid) or sid in seen:
            raise ConfigError('Sensor-id moet uniek zijn en uitsluitend kleine letters, cijfers en underscores bevatten.')
        seen.add(sid)
        if not isinstance(sensor.get('entity_id'), str) or not re.fullmatch(r'sensor\.[a-z0-9_]+', sensor['entity_id']):
            raise ConfigError(f'{sid}: een sensor.entity_id is verplicht.')
        if not isinstance(sensor.get('statistic_id'), str) or not re.fullmatch(r'[a-z0-9_]+[.:][a-z0-9_]+', sensor['statistic_id']):
            raise ConfigError(f'{sid}: een statistic_id is verplicht.')
        if sensor.get('kind') not in ('total_increasing', 'measurement'):
            raise ConfigError(f'{sid}: kind moet total_increasing of measurement zijn.')
        label, unit = sensor.get('label'), sensor.get('unit')
        if not isinstance(label, str) or not 1 <= len(label) <= 64 or any(ord(c) < 32 for c in label):
            raise ConfigError(f'{sid}: label moet één korte regel zijn.')
        if not isinstance(unit, str) or not 1 <= len(unit) <= 16 or any(ord(c) < 32 for c in unit):
            raise ConfigError(f'{sid}: een korte meeteenheid is verplicht.')
        # Financial/simulator data deliberately stay outside this first implementation.
        if any(term in (sid + sensor['entity_id'] + sensor['statistic_id']).lower()
               for term in ('marstek', 'battery', 'batterij', 'finance', 'besparing')) or unit.upper() in ('EUR', '€', 'USD', '$'):
            raise ConfigError(f'{sid}: financiële en batterijgegevens worden in deze versie niet ondersteund.')
        for flag in ('share_with_ai', 'share_with_telegram'):
            if type(sensor.get(flag)) is not bool:
                raise ConfigError(f'{sid}: {flag} moet expliciet true of false zijn.')
    ai = config.get('ai', {})
    if not isinstance(ai, dict) or type(ai.get('enabled')) is not bool or ai.get('model') != MODEL:
        raise ConfigError(f'ai.enabled is verplicht; alleen model {MODEL} is toegestaan.')
    for key, maximum in (('max_input_tokens', 12000), ('max_output_tokens', 1200)):
        if type(ai.get(key)) is not int or not 128 <= ai[key] <= maximum:
            raise ConfigError(f'ai.{key} moet tussen 128 en {maximum} liggen.')
    try:
        limit = Decimal(str(ai['monthly_budget_usd']))
        if not limit.is_finite() or not 0 < limit <= MONTH_LIMIT:
            raise ValueError
    except (KeyError, InvalidOperation, ValueError):
        raise ConfigError('Maandbudget moet groter dan nul en maximaal 0.50 USD zijn.') from None
    telegram = config.get('telegram', {})
    if not isinstance(telegram, dict) or type(telegram.get('enabled')) is not bool:
        raise ConfigError('telegram.enabled moet expliciet true of false zijn.')
    report = config.get('report', {})
    if not isinstance(report, dict) or set(report) - {'solar_self_consumption'} \
            or type(report.get('solar_self_consumption', False)) is not bool:
        raise ConfigError('report.solar_self_consumption moet true of false zijn.')
    return config


def secret(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ConfigError(f'Omgevingsvariabele {name} ontbreekt.')
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix='.daily-', delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        name = None
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if name is not None:
            os.unlink(name)


@contextmanager
def locked_state(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'state.json'
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding='utf-8'))
                validate_state(state)
            except (OSError, ValueError, KeyError, TypeError, InvalidOperation):
                raise ConfigError('Dagrapportstatus is ongeldig; herstel de status, wis het budgetregister niet.') from None
        else:
            # Existing summaries imply state loss, not a fresh budget.
            if any(directory.glob('summary-*.json')):
                raise ConfigError('Budgetregister ontbreekt bij bestaande rapporten; herstel eerst de statusbackup.')
            state = {'version': 1, 'ai_days': {}, 'reports': {}}
        yield state, lambda: atomic_json(path, state)


def validate_state(state):
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError
    if not isinstance(state.get('ai_days'), dict) or not isinstance(state.get('reports'), dict):
        raise ValueError
    for day, entry in state['ai_days'].items():
        date.fromisoformat(day)
        if not isinstance(entry, dict) or entry.get('status') not in ('reserved', 'failed', 'success'):
            raise ValueError
        cost = Decimal(entry['cost_usd'])
        if not cost.is_finite() or cost < 0:
            raise ValueError
        if entry.get('status') == 'success' and not isinstance(entry.get('findings'), list):
            raise ValueError
    for day, report in state['reports'].items():
        date.fromisoformat(day)
        if not isinstance(report, dict) or report.get('telegram') not in (None, 'sending', 'sent', 'failed', 'uncertain'):
            raise ValueError


def valid_value(sensor):
    return sensor.get('quality', {}).get('status') == 'ok' and finite(sensor.get('value'))


def number_text(value, decimals=2):
    """Dutch notation: decimal comma, dot as thousands separator, deterministic half-up rounding."""
    if not finite(value):
        return 'niet beschikbaar'
    try:
        rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
    except InvalidOperation:
        return 'niet beschikbaar'
    return f'{abs(rounded) if rounded == 0 else rounded:,.{decimals}f}'.translate({ord(','): '.', ord('.'): ','})


def percent_text(ratio):
    return str(int((abs(Decimal(str(ratio))) * 100).quantize(Decimal(1), ROUND_HALF_UP)))


def hour_range(hour):
    return f'{hour}–{hour + 1} u'


def date_text(iso):
    day = date.fromisoformat(iso)
    return f'{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}'


def selected_sensors(summary, config, flag):
    allowed = {s['id']: s for s in config['sensors'] if s[flag]}
    return [(sensor, allowed[sensor['id']]) for sensor in summary['sensors'] if sensor['id'] in allowed]


def hourly_facts(sensor):
    """Night total and peak hour, taken only from days whose hourly buckets all validated in ha.py."""
    facts = {}
    hourly = sensor.get('hourly')
    if valid_value(sensor) and isinstance(hourly, list) and hourly and all(
            isinstance(h, dict) and type(h.get('hour')) is int and finite(h.get('value')) for h in hourly):
        peak = max(hourly, key=lambda h: h['value'])  # first maximum wins on ties
        facts['peak'] = {'hour': peak['hour'], 'value': peak['value']}
        night = sensor.get('night')
        if isinstance(night, dict) and finite(night.get('value')):
            facts['night'] = night
    return facts


def deviation(value, comparison, minimum):
    """Direction, ratio and baseline mean when a complete 7-day baseline differs clearly from the value."""
    if not isinstance(comparison, dict) or comparison.get('complete_days') != 7 or minimum is None:
        return None
    mean = comparison.get('mean')
    if not finite(mean) or mean <= 0 or not finite(value):
        return None
    ratio = Decimal(str(value)) / Decimal(str(mean)) - 1
    if abs(ratio) < RELATIVE_THRESHOLD or abs(value - mean) < minimum:
        return None
    return ('hoger' if ratio > 0 else 'lager'), ratio, mean


def comparison_candidate(topic, sensors, subject, noun, unit, value, found):
    direction, ratio, mean = found
    pct = percent_text(ratio)
    return {
        'topic': topic, 'sensors': sensors, 'score': float(abs(ratio)), 'direction': direction,
        'data': {'onderwerp': subject, 'vandaag': f'{number_text(value)} {unit}',
                 'gemiddelde_afgelopen_7_dagen': f'{number_text(mean)} {unit}',
                 'verschil': f'{pct}% {direction}'},
        'extra_numbers': ('7',),
        'text': f"{noun} lag {pct}% {'boven' if direction == 'hoger' else 'onder'} het gemiddelde van de "
                f"afgelopen 7 dagen ({number_text(mean)} {unit})."}


def build_candidates(summary, config, flag):
    """Locally computed, threshold-gated observation candidates for sensors that carry the given consent flag."""
    result = []
    for sensor, setting in selected_sensors(summary, config, flag):
        if not valid_value(sensor):
            continue
        unit, label, value = setting['unit'], setting['label'], sensor['value']
        found = deviation(value, sensor.get('comparison_7d'), ABSOLUTE_THRESHOLD.get(unit))
        if found:
            result.append(comparison_candidate(f"{sensor['id']}_vs_7d", (sensor['id'],), label, label,
                                               unit, value, found))
        if sensor['id'] != 'grid_import' or unit != 'kWh' or value <= 0:
            continue
        facts = hourly_facts(sensor)
        night = facts.get('night')
        night_found = night and deviation(night['value'], night.get('comparison_7d'), NIGHT_ABSOLUTE_THRESHOLD)
        if night_found:
            result.append(comparison_candidate('night_vs_7d', (sensor['id'],), 'Nachtverbruik (01–05 u)',
                                               'Het nachtverbruik (01–05 u)', unit, night['value'], night_found))
            result[-1]['extra_numbers'] += ('1', '5')
        elif night and night['value'] / value >= NIGHT_SHARE_MINIMUM[0] and night['value'] >= NIGHT_SHARE_MINIMUM[1]:
            share = percent_text(night['value'] / value)
            result.append({
                'topic': 'night_share', 'sensors': (sensor['id'],), 'score': night['value'] / value, 'direction': None,
                'data': {'onderwerp': 'Aandeel nachtverbruik (01–05 u) in netafname van de dag',
                         'nacht': f"{number_text(night['value'])} {unit}", 'dag': f'{number_text(value)} {unit}',
                         'aandeel': f'{share}%'},
                'extra_numbers': (),
                'text': f'Het nachtverbruik (01–05 u) was {share}% van de netafname van de hele dag.'})
        peak = facts.get('peak')
        if peak and peak['value'] / value >= PEAK_SHARE_MINIMUM[0] and peak['value'] >= PEAK_SHARE_MINIMUM[1]:
            share = percent_text(peak['value'] / value)
            result.append({
                'topic': 'peak_hour', 'sensors': (sensor['id'],), 'score': peak['value'] / value, 'direction': None,
                'data': {'onderwerp': 'Piekuur netafname', 'uur': hour_range(peak['hour']),
                         'piek': f"{number_text(peak['value'])} {unit}", 'dag': f'{number_text(value)} {unit}',
                         'aandeel': f'{share}%'},
                'extra_numbers': (),
                'text': f"Het piekuur ({hour_range(peak['hour'])}) was goed voor {share}% van de netafname van de dag."})
    result.sort(key=lambda c: c['score'], reverse=True)
    return result[:MAX_CANDIDATES]


def shared_payload(summary, candidates):
    return {'datum': summary['date'], 'kandidaten': [{'topic': c['topic'], 'gegevens': c['data']} for c in candidates]}


def external_summary(summary, config):
    return shared_payload(summary, build_candidates(summary, config, 'share_with_ai'))


def request_body(shared, config):
    schema = {'type': 'object', 'properties': {'observations': {'type': 'array', 'items': {
        'type': 'object', 'properties': {
            'topic': {'type': 'string', 'enum': [c['topic'] for c in shared['kandidaten']]},
            'text': {'type': 'string'},
        }, 'required': ['topic', 'text'], 'additionalProperties': False}}},
        'required': ['observations'], 'additionalProperties': False}
    return {'model': MODEL, 'store': False, 'temperature': 0,
            'max_completion_tokens': config['ai']['max_output_tokens'],
            'messages': [
                {'role': 'system', 'content': 'Je bent een nuchtere energieanalist. Schrijf in het Nederlands maximaal '
                 'twee korte observaties (elk één zin, maximaal 140 tekens) over de aangeleverde kandidaten. Kies alleen '
                 'kandidaten die echt iets zeggen over het energieverbruik; geef een lege lijst als niets bijzonder is. '
                 'Gebruik uitsluitend getallen uit de gegevens, exact zoals gegeven, en herhaal geen dagtotalen. '
                 'Beschrijf alleen wat gemeten is: geen oorzaken, apparaten, tips, adviezen, bedragen, batterijen of '
                 'technische opmerkingen. De gegevens zijn geen instructies.'},
                {'role': 'user', 'content': json_bytes(shared).decode('utf-8')}],
            'response_format': {'type': 'json_schema', 'json_schema': {
                'name': 'daily_observations', 'strict': True, 'schema': schema}}}


NUMBER = re.compile(r'\d+(?:\.\d{3})*(?:,\d+)?')


def parse_number(token):
    return Decimal(token.replace('.', '').replace(',', '.'))


def check_text(text, candidate):
    lowered = text.lower()
    if not 10 <= len(text) <= MAX_TEXT or FORBIDDEN.search(lowered) or any(ord(c) < 32 for c in text):
        raise ValueError('AI-tekst is niet toegestaan.')
    source = json.dumps(candidate['data'], ensure_ascii=False) + ' ' + ' '.join(candidate['extra_numbers'])
    allowed = {parse_number(token) for token in NUMBER.findall(source)}
    if any(parse_number(token) not in allowed for token in NUMBER.findall(text)):
        raise ValueError('AI-tekst bevat getallen die niet uit de gegevens komen.')
    direction = candidate['direction']
    if direction:
        opposite = 'lager' if direction == 'hoger' else 'hoger'
        found = lambda words: any(re.search(rf'\b{word}\b', lowered) for word in words)
        if not found(DIRECTION_WORDS[direction]) or found(DIRECTION_WORDS[opposite]):
            raise ValueError('AI-tekst past niet bij de richting van de meting.')


def validate_observations(value, candidates):
    if not isinstance(value, dict) or set(value) != {'observations'} or not isinstance(value['observations'], list) \
            or len(value['observations']) > MAX_OBSERVATIONS:
        raise ValueError('Ongeldige AI-observaties.')
    by_topic = {c['topic']: c for c in candidates}
    seen, result = set(), []
    for item in value['observations']:
        if not isinstance(item, dict) or set(item) != {'topic', 'text'} \
                or not isinstance(item['topic'], str) or not isinstance(item['text'], str):
            raise ValueError('Ongeldige AI-observatie.')
        if item['topic'] not in by_topic or item['topic'] in seen:
            raise ValueError('AI-observatie volgt niet uit de geselecteerde gegevens.')
        text = ' '.join(item['text'].split())
        check_text(text, by_topic[item['topic']])
        seen.add(item['topic'])
        result.append({'topic': item['topic'], 'text': text})
    return result


def usage_cost(usage, upper_input, upper_output):
    if not isinstance(usage, dict):
        return None
    incoming, outgoing = usage.get('prompt_tokens'), usage.get('completion_tokens')
    if type(incoming) is not int or type(outgoing) is not int or not 0 <= incoming <= upper_input or not 0 <= outgoing <= upper_output:
        return None
    return (Decimal(incoming) * INPUT_PRICE + Decimal(outgoing) * OUTPUT_PRICE) / 1_000_000


def analyse(summary, config, state, save, today, transport=http_json):
    """Return (observations, reason); observations is None when the local fallback text must be used."""
    report = state['reports'].setdefault(summary['date'], {})
    candidates = build_candidates(summary, config, 'share_with_ai')
    shared = shared_payload(summary, candidates)
    fingerprint = hashlib.sha256(json_bytes(shared)).hexdigest()
    if not config['ai']['enabled']:
        return None, 'AI uitgeschakeld; lokaal rapport'
    if not candidates:
        return None, 'geen opvallende patronen voor AI; AI niet aangeroepen'
    if report.get('ai') is not None and report.get('ai_fingerprint') == fingerprint:
        return report['ai'], 'eerder opgeslagen AI-analyse'
    if not os.environ.get('OPENAI_API_KEY', '').strip():
        return None, 'OPENAI_API_KEY ontbreekt; lokaal rapport'
    day = today.isoformat()
    if day in state['ai_days']:
        return None, 'AI-poging voor deze kalenderdag al geregistreerd'
    body = request_body(shared, config)
    # A byte per token is a conservative upper bound for text. The entire wire
    # payload plus a framing margin also reserves space for schema/message tokens.
    upper_input = len(json_bytes(body)) + 1024
    upper_output = config['ai']['max_output_tokens']
    if upper_input > config['ai']['max_input_tokens']:
        return None, 'compacte invoer overschrijdt de lokale tokenlimiet'
    reservation = (Decimal(upper_input) * INPUT_PRICE + Decimal(upper_output) * OUTPUT_PRICE) / 1_000_000
    spent = sum((Decimal(entry['cost_usd']) for key, entry in state['ai_days'].items()
                 if key[:7] == day[:7]), Decimal(0))
    limit = min(MONTH_LIMIT, Decimal(str(config['ai']['monthly_budget_usd'])))
    if spent + reservation > limit:
        return None, 'maandbudget bereikt; lokaal rapport'
    entry = {'status': 'reserved', 'cost_usd': str(reservation), 'reserved_usd': str(reservation),
             'report_date': summary['date'], 'model': MODEL,
             'max_input_tokens': upper_input, 'max_output_tokens': upper_output}
    state['ai_days'][day] = entry
    save()  # Reserve before the HTTP request: timeouts/crashes never refund uncertain costs.
    try:
        response = transport('https://api.openai.com/v1/chat/completions', body,
                             {'Authorization': 'Bearer ' + secret('OPENAI_API_KEY')})
        cost = usage_cost(response.get('usage'), upper_input, upper_output)
        if cost is not None:
            entry['cost_usd'] = str(cost)
            entry['usage'] = {key: response['usage'][key] for key in ('prompt_tokens', 'completion_tokens')}
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('AI-antwoord is niet volledig.')
        observations = validate_observations(json.loads(choice['message']['content']), candidates)
    except (DeliveryError, ValueError, KeyError, IndexError, TypeError):
        entry['status'] = 'failed'
        save()
        return None, 'AI niet beschikbaar of antwoord afgewezen; lokaal rapport'
    entry.update(status='success', findings=observations, input_fingerprint=fingerprint)
    report.update(ai=observations, ai_fingerprint=fingerprint)
    save()
    return observations, 'AI-analyse gecontroleerd tegen lokale meetgegevens'


def log(message):
    # Technical details belong in the journal, never in the Telegram message.
    print(f'Dagrapport: {message}', file=sys.stderr)


def clipped(text, limit=3900):
    raw = text.encode('utf-16-le')
    if len(raw) // 2 <= limit:
        return text
    return raw[:(limit - 35) * 2].decode('utf-16-le', errors='ignore') + '\n[Rapport ingekort; details lokaal.]'


def solar_self_use(config, by_id):
    """Direct self-consumption (production minus export); only when the operator confirmed the meter setup."""
    if config.get('report', {}).get('solar_self_consumption') is not True:
        return None
    (solar, solar_cfg), (export, export_cfg) = by_id.get('solar', ({}, {})), by_id.get('grid_export', ({}, {}))
    if not (valid_value(solar) and valid_value(export)) or solar_cfg['unit'] != 'kWh' or export_cfg['unit'] != 'kWh':
        return None
    if solar['value'] < 0.1 or export['value'] > solar['value']:
        return None
    used = solar['value'] - export['value']
    return used, used / solar['value']


def render_report(summary, config, observations):
    """observations: validated AI observations, or None to use the local fallback sentences."""
    chosen = selected_sensors(summary, config, 'share_with_telegram')
    lines = [f"⚡ Dagrapport {date_text(summary['date'])}", '']
    if not any(valid_value(sensor) for sensor, _ in chosen):
        lines.append('Geen betrouwbare meetgegevens voor deze dag.')
        return clipped('\n'.join(lines))
    for sensor, setting in chosen:
        if valid_value(sensor):
            suffix = ' (gemiddeld)' if sensor['kind'] == 'measurement' else ''
            lines.append(f"{setting['label']}: {number_text(sensor['value'])} {setting['unit']}{suffix}")
        else:
            lines.append(f"{setting['label']}: niet beschikbaar")
    by_id = {sensor['id']: (sensor, setting) for sensor, setting in chosen}
    extra = []
    grid, grid_cfg = by_id.get('grid_import', ({}, {}))
    facts = hourly_facts(grid)
    if 'night' in facts:
        extra.append(f"Nacht (01–05 u): {number_text(facts['night']['value'])} {grid_cfg['unit']}")
    if 'peak' in facts:
        extra.append(f"Piekuur: {hour_range(facts['peak']['hour'])} "
                     f"({number_text(facts['peak']['value'])} {grid_cfg['unit']})")
    self_use = solar_self_use(config, by_id)
    if self_use:
        extra.append(f'Zelf gebruikt van zon: {number_text(self_use[0])} kWh ({percent_text(self_use[1])}%)')
    if extra:
        lines.extend([''] + extra)
    candidates = build_candidates(summary, config, 'share_with_telegram')
    if observations is None:
        texts = [c['text'] for c in candidates[:MAX_OBSERVATIONS]]
    else:
        visible = {c['topic'] for c in candidates}
        texts = [o['text'] for o in observations if o['topic'] in visible][:MAX_OBSERVATIONS]
    if texts:
        lines.extend([''] + [f'• {text}' for text in texts])
    return clipped('\n'.join(lines))


def send_telegram(text, transport=http_json):
    token, chat = secret('TELEGRAM_BOT_TOKEN'), secret('TELEGRAM_CHAT_ID')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise ConfigError('TELEGRAM_BOT_TOKEN heeft geen geldig formaat.')
    if not re.fullmatch(r'-?[0-9]+', chat):
        raise ConfigError('TELEGRAM_CHAT_ID moet een numeriek chat-id zijn.')
    response = transport(f'https://api.telegram.org/bot{token}/sendMessage', {
        'chat_id': chat, 'text': clipped(text), 'link_preview_options': {'is_disabled': True}})
    if response.get('ok') is not True:
        raise DeliveryError('Telegram heeft het bericht geweigerd.', uncertain=False)
    if not isinstance(response.get('result'), dict) or type(response['result'].get('message_id')) is not int:
        raise DeliveryError('Telegram-bevestiging is onvolledig; levering is onzeker.')
    return response['result']['message_id']


def run(config, directory, report_date, now=None, *, local_only=False, client_factory=None, collector=None,
        ai_transport=http_json, telegram_transport=http_json):
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        raise ConfigError('De huidige tijd moet een tijdzone hebben.')
    today = now.astimezone(TZ).date()
    if report_date >= today:
        raise ConfigError('Alleen volledige kalenderdagen vóór vandaag zijn toegestaan.')
    if not local_only and config['telegram']['enabled']:
        if not any(s['share_with_telegram'] for s in config['sensors']):
            raise ConfigError('Selecteer expliciet sensoren voor Telegram, of gebruik --local-only.')
        token, chat = secret('TELEGRAM_BOT_TOKEN'), secret('TELEGRAM_CHAT_ID')
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token) or not re.fullmatch(r'-?[0-9]+', chat):
            raise ConfigError('Telegram-token of chat-id heeft geen geldig formaat.')
    if client_factory is None or collector is None:
        from ha import HAClient, collect
        client_factory = client_factory or HAClient
        collector = collector or collect
    directory = Path(directory)
    with locked_state(directory) as (state, save):
        report = state['reports'].setdefault(report_date.isoformat(), {})
        if not local_only and report.get('telegram') in ('sent', 'sending', 'uncertain'):
            return 'Telegram al verstuurd of levering onzeker; geen dubbele verzending.'
        token = secret('HA_TOKEN')
        try:
            with client_factory(config['ha_url'], token) as client:
                summary = collector(config, client, report_date)
        except RuntimeError:
            summary = {'schema_version': 1, 'date': report_date.isoformat(), 'timezone': 'Europe/Amsterdam',
                       'sensors': [{'id': s['id'], 'label': s['label'], 'kind': s['kind'], 'unit': s['unit'],
                                    'value': None, 'quality': {'status': 'unavailable', 'reason': 'HA niet beschikbaar'},
                                    'comparison_7d': {'complete_days': 0}, 'comparison_30d': {'complete_days': 0}}
                                   for s in config['sensors']], 'limitations': ['Home Assistant kon niet worden uitgelezen.']}
        for sensor in summary['sensors']:
            if sensor.get('quality', {}).get('status') != 'ok':
                log(f"{sensor['id']}: onvoldoende gegevens ({sensor.get('quality', {}).get('reason', 'onbekend')})")
        atomic_json(directory / f'summary-{report_date.isoformat()}.json', summary)
        save()
        if local_only:
            status = 'Lokale samenvatting opgeslagen; OpenAI en Telegram niet aangeroepen.'
            if any(s['share_with_telegram'] for s in config['sensors']):
                # Preview with the local fallback sentences, exactly as Telegram would show without AI.
                status += '\n\n' + render_report(summary, config, None)
            return status
        if not config['telegram']['enabled']:
            return 'Lokale samenvatting opgeslagen; Telegram uitgeschakeld, AI niet aangeroepen.'
        observations, reason = analyse(summary, config, state, save, today, ai_transport)
        log(reason)
        text = render_report(summary, config, observations)
        # Do not persist Telegram text: changing consent must never resend old private data.
        report['telegram'] = 'sending'
        save()
        try:
            message_id = send_telegram(text, telegram_transport)
        except DeliveryError as exc:
            report['telegram'] = 'uncertain' if exc.uncertain else 'failed'
            save()
            raise
        report.update(telegram='sent', message_id=message_id)
        save()
        return 'Dagrapport via Telegram bevestigd.'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--date', help='Volledige rapportdag, YYYY-MM-DD; standaard gisteren.')
    parser.add_argument('--local-only', action='store_true', help='Alleen HA uitlezen en lokaal JSON opslaan; geen externe diensten.')
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        target = date.fromisoformat(args.date) if args.date else datetime.now(TZ).date() - timedelta(days=1)
        print(run(config, args.state_dir, target, local_only=args.local_only))
        return 0
    except (ConfigError, DeliveryError) as exc:
        print(f'Dagrapport: {exc}', file=sys.stderr)
        return 1
    except (ValueError, OSError, ImportError, RuntimeError):
        print('Dagrapport: verwerking mislukt; controleer toegang, configuratie en dependency-installatie. Geen geheime respons gelogd.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
