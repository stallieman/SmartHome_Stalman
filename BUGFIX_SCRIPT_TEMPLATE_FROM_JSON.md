# Bugfix: Script Template from_json Filter Missing Default Values

**Date**: 2026-11-02  
**Severity**: CRITICAL  
**Impact**: Script execution blocked; sensor state cannot be calculated

## Problem

Home Assistant logs from the active instance (2026-11-02 19:13:31) showed:

```
ERROR ValueError: Template error: from_json got invalid input '...' but no default was specified
```

The script `script.stalman_historische_importkosten` contained two `from_json` filter calls without default value parameters. Home Assistant's Jinja2 `from_json` filter requires an explicit default when parsing potentially invalid JSON.

## Root Cause

**Line 139** (script variable `historical_result`):
```yaml
historical_result: "{{ historical_calculation.stdout | from_json }}"
```

**Line 172** (script variable `historical_summary_status`):
```yaml
historical_summary_status: >-
  {% set result = historical_summary | from_json %}
  {{ 'ok' if result.get('status') == 'ok' and historical_summary | length <= 255 else 'unavailable' }}
```

Both called `from_json` without specifying a default value. When `from_json` encounters non-JSON input or expects a default, it raises `ValueError`.

## Solution

Added `(default={})` parameter to both `from_json` filter calls:

**Line 139** (fixed):
```yaml
historical_result: "{{ historical_calculation.stdout | from_json(default={}) }}"
```

**Line 172** (fixed):
```yaml
historical_summary_status: >-
  {% set result = historical_summary | from_json(default={}) %}
  {{ 'ok' if result.get('status') == 'ok' and historical_summary | length <= 255 else 'unavailable' }}
```

## Why This Works

- `from_json(default={})` returns an empty dict `{}` if the input is not valid JSON
- The subsequent templates safely call `.get()` on the result (empty dict returns `None` for missing keys)
- No `ValueError` is raised; script continues to execution flow

## Files Modified

- `config/packages/energie_historische_kosten.yaml`
  - Line 139: Added `(default={})` to `historical_result` variable
  - Line 172: Added `(default={})` to `historical_summary_status` variable

## Tests

Created regression test suite: `tests/test_script_template_error_fix.py`

- ✓ Script has `from_json(default={})` in both locations
- ✓ No bare `from_json` without default anywhere in the script
- ✓ Helper update action exists
- ✓ JSON parse logic is sound

All 33 related tests passing (template sensor, syntax validation, error handling, period validation).

## Verification

Run:
```bash
source .venv/bin/activate
python3 -m pytest tests/test_script_template_error_fix.py -v
```

## Next Steps

1. Deploy the fixed `energie_historische_kosten.yaml` to Home Assistant
2. Restart Home Assistant or reload the package
3. Trigger the script manually to verify no template errors
4. Verify sensor updates to show EUR value instead of `unknown`
5. Verify automation runs at 06:15 without errors

## Related Issues

- Template sensor displayed `unknown` state due to timing/dependency issue (separate fix: trigger-based platform syntax)
- Script blocked script execution completely; script fix must happen before sensor fix can be validated
