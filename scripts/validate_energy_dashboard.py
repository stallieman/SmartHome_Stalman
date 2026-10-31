"""Offline checks; does not connect to or change Home Assistant.
Run with Python + PyYAML + Jinja2. Synthetic inputs below are test cases only.
"""
from pathlib import Path
import math
import re
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]

class UniqueLoader(yaml.SafeLoader):
    pass

def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'Duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result

UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
UniqueLoader.add_constructor('!include', lambda loader, node: loader.construct_scalar(node))
paths = ['config/dashboards/energie_thuisbatterij.yaml',
         'config/packages/energie_thuisbatterij.yaml',
         'config/themes/stalman_nacht.yaml', 'docs/activation.example.yaml']
data = {p: yaml.load((ROOT / p).read_text(), Loader=UniqueLoader) for p in paths}
dash = data[paths[0]]
package = data[paths[1]]
assert len(dash['views']) == 3
assert len({v['path'] for v in dash['views']}) == 3
allowed = {'heading', 'markdown', 'tile', 'gauge', 'history-graph', 'statistics-graph',
           'entities', 'energy-date-selection', 'energy-distribution', 'energy-usage-graph',
           'energy-solar-graph', 'energy-gas-graph'}
count = 0
for view in dash['views']:
    assert view['type'] == 'sections' and view['max_columns'] in (2, 3)
    assert view['theme'] in data[paths[2]]
    for section in view['sections']:
        assert section['type'] == 'grid'
        for card in section['cards']:
            count += 1
            assert card['type'] in allowed, card['type']
            if card['type'].startswith('energy-'):
                assert card['collection_key'] in {'energy_stalman', 'energy_stalman_overzicht'}
            if 'entity' in card:
                assert card['entity'].startswith('sensor.')
            assert not any(k in card for k in ['hold_action', 'double_tap_action'])

text = '\n'.join((ROOT / p).read_text() for p in paths[:2])
references = set(re.findall(r'\b(?:sensor|input_number|input_boolean)\.[a-z0-9_]+', text))
inventory = (ROOT / 'docs/ENTITIES.md').read_text()
assert all(f'`{e}`' in inventory for e in references)
sensors = package['template'][0]['sensor']
assert package['input_boolean']['stalman_tarieven_bevestigd']['initial'] is False
assert all('initial' not in h for h in package['input_number'].values())

def is_number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False

def evaluate(sensor, values, key):
    env = Environment(undefined=StrictUndefined)
    env.globals.update(states=lambda e: values.get(e, 'unavailable'),
                       is_state=lambda e, s: values.get(e) == s, is_number=is_number)
    return env.from_string(sensor[key]).render()

home = next(s for s in sensors if s['unique_id'] == 'stalman_woningvermogen')
base = 'sensor.marstek_venus_e_5_12kwh_3nd_gen'
values = {'sensor.p1_meter_vermogen': '-300', 'sensor.stalman_total_output_power': '1200'}
assert evaluate(home, values, 'availability') == 'True'
assert float(evaluate(home, values, 'state')) == 900
values['sensor.stalman_total_output_power'] = 'unavailable'
assert evaluate(home, values, 'availability') == 'False'
values['sensor.stalman_total_output_power'] = '100'
assert float(evaluate(home, values, 'state')) == 0
print(f'PASS: 4 YAML files, {len(dash["views"])} views, {count} built-in cards, '
      f'{len(references)} documented entities; availability and financial arithmetic checked.')
print('Not a Home Assistant schema check or browser rendering test.')

# Protect the other tabs, including names, card order and paths.
import subprocess
baseline = yaml.safe_load(subprocess.check_output(
    ['git', 'show', 'f9baab7:config/dashboards/energie_thuisbatterij.yaml'], text=True))
assert dash['views'][1] == baseline['views'][1]
previous = yaml.safe_load(subprocess.check_output(
    ['git', 'show', 'c688432:config/dashboards/energie_thuisbatterij.yaml'], text=True))
assert dash['views'][:2] == previous['views'][:2]
overview = dash['views'][0]
assert overview['title'] == 'Overzicht' and overview['max_columns'] == 2
cards = [c for section in overview['sections'] for c in section['cards']]
assert sum(c['type'] == 'energy-distribution' for c in cards) == 1
assert sum(c['type'] == 'energy-usage-graph' for c in cards) == 1
assert not any(c['type'] in {'history-graph', 'statistics-graph', 'energy-date-selection'} for c in cards)
for card in cards:
    if card['type'] == 'markdown':
        env = Environment(undefined=StrictUndefined)
        env.globals.update(states=lambda e: 'unavailable', is_number=is_number)
        rendered = env.from_string(card['content']).render()
        if 'states(' in card['content']:
            assert 'Nog niet beschikbaar' in rendered
            assert '0.0 €' not in rendered
        env.globals.update(states=lambda e: '42')
        env.from_string(card['content']).render()
meters = package['utility_meter']
assert len(meters) == 5
for meter in meters.values():
    assert meter['cycle'] == 'daily' and meter['always_available'] is False
    assert meter['periodically_resetting'] is True
house_today = next(s for s in sensors if s['unique_id'] == 'stalman_huis_vandaag')
values = {'sensor.stalman_import_vandaag': '5', 'sensor.stalman_export_vandaag': '3',
          'sensor.stalman_zon_vandaag': '7'}
assert float(evaluate(house_today, values, 'state')) == 9
assert evaluate(house_today, values, 'availability') == 'True'
values['sensor.stalman_zon_vandaag'] = 'unavailable'
assert evaluate(house_today, values, 'availability') == 'False'
# HA adapter must reject missing, yesterday's and stale reports.
from datetime import datetime, timezone, timedelta
now_value = datetime(2027, 1, 2, 12, 0, tzinfo=timezone.utc)
attrs = {'scope': 'day', 'start': '2027-01-02', 'observed_until': now_value.isoformat(),
         'saving_eur': '0.36', 'without_eur': '3.23', 'with_eur': '2.87'}
def stamp(value, default=0):
    try:
        return value.timestamp() if isinstance(value, datetime) else datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return default

env = Environment(undefined=StrictUndefined)
env.globals.update(states=lambda e: 'unavailable', is_number=is_number,
                   is_state=lambda e, state: report_state == state,
                   state_attr=lambda e, key: attrs.get(key), now=lambda: now_value, as_timestamp=stamp)
for sensor in [s for s in sensors if s['unique_id'].endswith('vandaag') and s['device_class'] == 'monetary']:
    report_state = 'ok'
    assert env.from_string(sensor['availability']).render() == 'True'
    attrs['observed_until'] = (now_value - timedelta(minutes=16)).isoformat()
    assert env.from_string(sensor['availability']).render() == 'False'
    attrs['observed_until'] = now_value.isoformat()
    attrs['start'] = '2027-01-01'
    assert env.from_string(sensor['availability']).render() == 'False'
    attrs['start'] = '2027-01-02'
    report_state = 'unavailable'
    assert env.from_string(sensor['availability']).render() == 'False'
print('PASS: simulation tab and overview structure preserved; daily arithmetic and report freshness checked.')

# Full-settlement variable costs and totals with fixed costs are distinct.
attrs.update(scope='billing', without_variable_eur='100.00', with_variable_eur='90.00',
             fixed_costs_status='unavailable', without_total_eur=None, with_total_eur=None)
report_state = 'ok'
billing_sensors = {s['unique_id']: s for s in sensors if s['unique_id'].startswith('stalman_afrekening_')
                   or s['unique_id'].startswith('stalman_totaal_afrekening_')}
assert env.from_string(billing_sensors['stalman_afrekening_kosten_zonder_batterij']['availability']).render() == 'True'
assert env.from_string(billing_sensors['stalman_afrekening_kosten_met_simulatie']['availability']).render() == 'True'
assert env.from_string(billing_sensors['stalman_totaal_afrekening_zonder_batterij']['availability']).render() == 'False'
attrs.update(fixed_costs_status='confirmed', without_total_eur='150.00', with_total_eur='140.00')
assert env.from_string(billing_sensors['stalman_totaal_afrekening_zonder_batterij']['availability']).render() == 'True'
attrs['scope'] = 'window'
assert env.from_string(billing_sensors['stalman_afrekening_kosten_zonder_batterij']['availability']).render() == 'False'
print('PASS: billing scenarios distinguish variable costs from confirmed fixed-cost totals.')

# A certified window is deliberately separate from today's/annual costs.
attrs['scope'] = 'window'
report_state = 'ok'
for sensor in [s for s in sensors if s['unique_id'].startswith('stalman_meetvenster_')]:
    assert env.from_string(sensor['availability']).render() == 'True'
    attrs['scope'] = 'day'
    assert env.from_string(sensor['availability']).render() == 'False'
    attrs['scope'] = 'window'
print('PASS: window-only monetary sensors cannot become daily totals.')
