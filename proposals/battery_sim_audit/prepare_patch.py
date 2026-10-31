"""Prepare a separately reviewed copy; never modifies the supplied source.
Only the byte-exact upstream v2.9.0 initializer is supported.
"""
import argparse
import ast
import hashlib
from pathlib import Path

EXPECTED = 'a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6'
HOOKS = {'async_source_tracking': 'audit_tracking', 'async_reading_handler': 'audit_reading',
         '_async_maybe_update_battery': 'audit_processing', 'async_reset_battery': 'audit_reset',
         'reset_sim_sensor': 'audit_reset'}


def transform(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise ValueError('Unsupported source SHA256; no patch prepared')
    text = source.decode()
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SimulatedBatteryHandle')
    methods = {m.name: m for m in cls.body if isinstance(m, ast.FunctionDef)}
    lines = text.splitlines(keepends=True)
    for name in sorted(HOOKS, key=lambda name: methods[name].lineno, reverse=True):
        lines.insert(methods[name].lineno - 1, '    @' + HOOKS[name] + '\n')
    text = ''.join(lines)
    # Insert after the module docstring, preserving any future imports.
    tree = ast.parse(text)
    position = tree.body[0].end_lineno if isinstance(tree.body[0], ast.Expr) else 0
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            position = node.end_lineno
    lines = text.splitlines(keepends=True)
    lines.insert(position, '\nfrom .stalman_audit import audit_tracking, audit_reading, audit_processing, audit_reset\n')
    patched = ''.join(lines)
    check = ast.parse(patched)
    patched_cls = next(n for n in check.body if isinstance(n, ast.ClassDef) and n.name == cls.name)
    originals = {n.name: ast.dump(ast.Module(body=n.body, type_ignores=[])) for n in cls.body if isinstance(n, ast.FunctionDef)}
    updated = {n.name: ast.dump(ast.Module(body=n.body, type_ignores=[])) for n in patched_cls.body if isinstance(n, ast.FunctionDef)}
    if originals != updated:
        raise ValueError('Battery method bodies changed; refusing patch')
    return patched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.exists():
        parser.error('Output must be a new separate file')
    patched = transform(args.source.read_bytes())
    with args.output.open('x') as stream:
        stream.write(patched)
    print('Prepared separate proposal; all battery method bodies unchanged. Not installed.')


if __name__ == '__main__':
    main()
