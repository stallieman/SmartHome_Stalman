# Fix: Template Sensor Dependency Not Declared

## Problem
`sensor.stalman_historische_importkosten` remained in state `unknown` despite the helper `input_text.stalman_historical_importcosts_summary` containing valid JSON with `status: ok` and `eur: 1.64`.

## Root Cause
The template sensor used **old-style list-based syntax** without explicit entity dependencies:
```yaml
template:
  - sensor:  # ← No explicit trigger or dependency declaration
      - name: Stalman historische importkosten
```

When the script updated the helper at 06:15, Home Assistant's automatic dependency detection did not guarantee an immediate re-render. The sensor only re-evaluated when other template events occurred, leading to a timing issue:

1. ✓ Script updates helper at 06:15 with `date: "2026-11-01"`
2. ✗ Sensor doesn't listen explicitly for helper changes
3. ⏸️ Sensor only re-renders hours later
4. ✗ By then, `now().date() - 1 day = "2026-11-02"` (not "2026-11-01")
5. ✗ Availability check fails: `result.get('date') ("2026-11-01") != yesterday ("2026-11-02")`
6. ✗ Sensor state becomes `unknown`

## Solution
Converted to **trigger-based syntax** (Home Assistant 2022.1+) with explicit state trigger on the helper:

```yaml
template:
  - trigger: state  # ← Explicit trigger
    entity_id: input_text.stalman_historical_importcosts_summary  # ← Listen for changes
    sensors:  # ← Changed from "- sensor:"
      stalman_historische_importkosten:  # ← Key name instead of list item
        name: Stalman historische importkosten
        # ... rest of config unchanged
```

## Effect
- When helper updates, sensor **re-renders immediately**
- Availability check runs with correct `yesterday` value
- State updates to show EUR value instead of `unknown`
- Old data correctly becomes unavailable once `yesterday` no longer matches helper date

## Files Changed
- `config/packages/energie_historische_kosten.yaml`: Lines 6-38

## Tests
- ✓ All 15 energy-related tests pass
- ✓ 6 new tests for trigger-based syntax verification
- ✓ YAML syntax validation confirms correct structure
- ✓ Template logic verification confirms immediate state update on helper change

## Verification
```bash
pytest tests/test_historical_import_response.py \
        tests/test_template_sensor_trigger.py \
        tests/test_historical_import_period.py -v
```

Result: 15 passed in 0.08s
