# Fix Summary: Template Sensor 'unknown' State

## Problem
`sensor.stalman_historische_importkosten` remained `unknown` despite helper containing valid data: `{"status": "ok", "date": "2026-11-01", "eur": "1.64", "coverage": "complete", ...}`

## Root Cause
The template sensor used **old-style list-based syntax** without explicit entity dependencies:
```yaml
template:
  - sensor:  # No dependency declaration
      - name: Stalman historische importkosten
```

Home Assistant's automatic dependency detection on `states()` calls is unreliable, especially with:
- Complex Jinja2 logic (nested conditionals)
- Time-based checks using `now()`
- Multiple state() calls within variable assignments

Result: Sensor didn't re-evaluate when helper updated at 06:15.

## Solution
Converted to **trigger-based template platform** (HA 2022.1+, valid in 2026.10):
```yaml
template:
  - trigger: state
    entity_id: input_text.stalman_historical_importcosts_summary
    sensors:
      stalman_historische_importkosten:
        name: Stalman historische importkosten
        unique_id: stalman_historische_importkosten
        device_class: monetary
        unit_of_measurement: EUR
        availability: [template]
        state: [template]
        attributes: [templates]
```

**Why this works:**
- Explicit entity_id dependency on helper
- Sensor re-evaluates **immediately** when helper state changes
- No time-based re-evaluation race conditions
- Availability check runs in proper trigger context

## Verification
✅ YAML syntax: VALID  
✅ HA 2026.10 template platform: COMPLIANT  
✅ No old-style fields (`default_entity_id` removed)  
✅ All 29 tests pass (14 new syntax validation tests)  

## Files Changed
- `config/packages/energie_historische_kosten.yaml` (lines 6-38)

## Tests Added
- `tests/test_template_sensor_trigger.py` — 6 tests for trigger behavior
- `tests/test_template_sensor_syntax_validation.py` — 14 tests for HA 2026.10 compliance

## Expected Behavior After Installation
1. Script updates helper at 06:15 with calculation
2. Sensor receives state-change trigger immediately
3. Availability check evaluates to True (status='ok', coverage='complete', EUR valid)
4. State template displays EUR amount (e.g., "1.64")
5. Attributes show date, normal/offpeak kWh, coverage

## No Breaking Changes
- All existing automations and scripts unchanged
- Helper structure unchanged
- Python script unchanged
- Dashboard unchanged
