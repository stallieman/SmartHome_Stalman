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
    assert view['type'] == 'sections' and view['max_columns'] == 3
    assert view['theme'] in data[paths[2]]
    for section in view['sections']:
        assert section['type'] == 'grid'
        for card in section['cards']:
            count += 1
            assert card['type'] in allowed, card['type']
            if card['type'].startswith('energy-'):
                assert card['collection_key'] == 'energy_stalman'
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

home, money = sensors
base = 'sensor.marstek_venus_e_5_12kwh_3nd_gen'
values = {'sensor.p1_meter_vermogen': '-300', 'sensor.stalman_total_output_power': '1200'}
assert evaluate(home, values, 'availability') == 'True'
assert float(evaluate(home, values, 'state')) == 900
values['sensor.stalman_total_output_power'] = 'unavailable'
assert evaluate(home, values, 'availability') == 'False'
values['sensor.stalman_total_output_power'] = '100'
assert float(evaluate(home, values, 'state')) == 0
values = {base+'_total_energy_saved': '100', base+'_battery_energy_in': '130',
          'input_number.stalman_importtarief': '0.30', 'input_number.stalman_exporttarief': '0.08',
          'input_boolean.stalman_tarieven_bevestigd': 'off'}
assert evaluate(money, values, 'availability') == 'False'
values['input_boolean.stalman_tarieven_bevestigd'] = 'on'
assert evaluate(money, values, 'availability') == 'True'
assert float(evaluate(money, values, 'state')) == 19.6
values['input_number.stalman_importtarief'] = '0'
assert float(evaluate(money, values, 'state')) == -10.4
values['input_number.stalman_exporttarief'] = '0'
assert float(evaluate(money, values, 'state')) == 0
for bad in ['unavailable', 'unknown', '']:
    values[base+'_total_energy_saved'] = bad
    assert evaluate(money, values, 'availability') == 'False'
print(f'PASS: 4 YAML files, {len(dash["views"])} views, {count} built-in cards, '
      f'{len(references)} documented entities; availability and financial arithmetic checked.')
print('Not a Home Assistant schema check or browser rendering test.')
