"""Offline audit proposal validation; optionally validate exact original source."""
import argparse
import ast
import importlib.util
import json
import hashlib
from pathlib import Path
import shlex
from urllib.parse import unquote
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path)
args = parser.parse_args()
pkg = yaml.safe_load((ROOT/'config/packages/energie_audit_adapter.yaml').read_text())
assert set(pkg) == {'automation','shell_command'}
assert pkg['automation'][0]['triggers'][0]['event_type'] == 'battery_sim_stalman_audit_batch'
assert pkg['automation'][0]['mode'] == 'queued'
env=Environment(undefined=StrictUndefined)
env.filters['to_json']=json.dumps
packet={'producer':'test-only','test':"'$(never);`never`"}
command=env.from_string(pkg['shell_command']['stalman_audit_collect']).render(packet=packet)
parts=shlex.split(command)
assert len(parts)==10 and parts[-2]=='--audit-batch-url'
assert json.loads(unquote(parts[-1]))==packet
assert '$(' not in parts[-1] and '`' not in parts[-1]
config=json.loads((ROOT/'config/energy_finance/collector.json').read_text())
assert config['audit']['enabled'] is False and bool(config['audit']['battery_id'])
assert config['audit']['expected_helper_sha256'] == hashlib.sha256((ROOT/'proposals/battery_sim_audit/stalman_audit.py').read_bytes()).hexdigest()
for file in ['config/energy_finance/batch_contract.py','proposals/battery_sim_audit/stalman_audit.py',
             'proposals/battery_sim_audit/prepare_patch.py']:
    compile((ROOT/file).read_text(),file,'exec')
if args.source:
    spec=importlib.util.spec_from_file_location('proposal',ROOT/'proposals/battery_sim_audit/prepare_patch.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text=module.transform(args.source.read_bytes())
    compile(text,'proposed-battery-sim-initializer','exec')
    print('PASS: exact v2.9.0 source hash; every original battery method body unchanged; proposal compiles.')
print('PASS: adapter YAML, safe event arguments, disabled default and proposal syntax.')
print('NOT a full Home Assistant runtime or simulation-physics validation.')
