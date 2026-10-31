"""Offline HA snapshot-template, command argument and YAML checks."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shlex
from types import SimpleNamespace
from urllib.parse import unquote

import yaml
from jinja2 import Environment, StrictUndefined
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).resolve().parents[1]
pkg = yaml.safe_load((ROOT / 'config/packages/energie_intervalcollector.yaml').read_text())
config = json.loads((ROOT / 'config/energy_finance/collector.json').read_text())
assert set(pkg) == {'input_text', 'shell_command', 'automation'}
assert pkg['input_text']['stalman_finance_session']['initial'] == ''
automation = pkg['automation'][0]
assert automation['mode'] == 'queued'
assert automation['triggers'][1]['seconds'] == '0'
assert automation['actions'][-1]['then'][0]['error'] is True
now = datetime(2027, 1, 2, tzinfo=timezone.utc)
values = {}
for role, entity in config['entities'].items():
    values[entity] = SimpleNamespace(
        state='1' if role == 'tariff' else '0',
        attributes={'unit_of_measurement': 'kWh'} if role != 'tariff' else {},
        last_reported=now, last_changed=now - timedelta(days=1))

class States:
    def __getitem__(self, entity):
        return values.get(entity)

    def __call__(self, entity):
        return now.isoformat()

env = NativeEnvironment(undefined=StrictUndefined)
env.globals.update(states=States(), now=lambda: now)
template = automation['actions'][1]['variables']['snapshot']
snapshot = env.from_string(template).render()
assert isinstance(snapshot, dict) and set(snapshot['states']) == set(config['entities'].values())
assert all(s['restored'] is False for s in snapshot['states'].values())
# Missing states remain explicitly unavailable, with no numeric fallback.
missing = config['entities']['sim_import']
del values[missing]
bad = env.from_string(template).render()
assert bad['states'][missing]['state'] == 'unavailable'
# Shell arguments contain URL-encoded JSON, never raw state strings.
snapshot['states'][missing]['state'] = "'; $(touch /tmp/never-run); `id`; \""
shell = Environment(undefined=StrictUndefined)
shell.filters['to_json'] = json.dumps
command = shell.from_string(pkg['shell_command']['stalman_finance_collect']).render(snapshot=snapshot)
args = shlex.split(command)
assert args[0:2] == ['python3', '/config/energy_finance/collector.py']
assert len(args) == 10
assert json.loads(unquote(args[-1])) == snapshot
assert '$(' not in args[-1] and '`' not in args[-1] and "'" not in args[-1]
assert not config['mapping_confirmed'] and not config['pairing_confirmed']
assert all(v is None for v in config['max_power_kw'].values())
print('PASS: collector YAML, native snapshot, missing-state handling and shell argument escaping.')
print('No Home Assistant schema or runtime check performed.')
