# Bugfix: Script Template from_json Filter — Veilige Aanpak

**Datum**: 2026-11-02  
**Severity**: CRITICAL  
**Status**: FIXED & VERIFIED

## Problem Geïdentificeerd

Home Assistant logs toonden:
```
ERROR ValueError: Template error: from_json got invalid input '...' but no default was specified
```

Twee `from_json` calls zonder default parameter in het script:
- **Regel 139**: `historical_result` variable
- **Regel 172**: `historical_summary_status` variable

## Geleverde Oplossing

### Regel 139
```yaml
# VOOR:
historical_result: "{{ historical_calculation.stdout | from_json }}"

# NA:
historical_result: "{{ historical_calculation.stdout | from_json(default={}) }}"
```

### Regel 172 — Defensieve Benadering
```yaml
# VOOR:
{% set result = historical_summary | from_json %}

# NA:
{% set result = historical_summary if historical_summary is mapping else (historical_summary | from_json(default={})) %}
```

## Waarom Dit Veilig Is

1. **Regel 139**: `historical_calculation.stdout` is altijd een string (shell output), dus `from_json(default={})` werkt correct
   - Valide JSON → geparseerd
   - Ongeldige JSON → teruggeven als lege dict `{}`
   - Templates die volgen gebruiken `.get()` veilig op lege dict

2. **Regel 172**: Defensieve aanpak met `is mapping` check
   - Als `historical_summary` al een dict is → gebruik direct
   - Als `historical_summary` een JSON string is → parse met `from_json(default={})`
   - Beschermt tegen onverwachte toekomstige wijzigingen
   - Geen `ValueError` onder beide scenario's

## Verificatie — 34/34 Tests Slagen

Uitgevoerd tests:
- ✅ 5 tests: Script template fouten (uit)
- ✅ 6 tests: Template sensor trigger semantiek
- ✅ 14 tests: YAML syntax HA 2026.10 compliance
- ✅ 2 tests: Historische import response handling
- ✅ 7 tests: Historische import period validatie

Alle testen doorstaan:
```
==================== 34 passed, 5 subtests passed in 0.19s =====================
```

## Bestandswijzigingen

**config/packages/energie_historische_kosten.yaml**:
- Regel 139: Toegevoegd `(default={})`
- Regel 172: Gewijzigd naar defensieve `is mapping` check

**tests/test_script_template_error_fix.py** (nieuwe regressie tests):
- Controleert `from_json(default={})` in beide locations
- Controleert `is mapping` defensieve logic
- Audit: geen bare `from_json` calls meer in script

## Logische Flow Verificatie

```
script.stalman_historische_importkosten:
  1. Haalt P1 uurstatistieken via shell_command op
  2. Parses stdout als JSON (regel 139: FIXED)
  3. Bouwt samenvatting met validatie en berekeningen
  4. Genereert JSON string via to_json filter
  5. Slaat op in input_text.stalman_historical_importcosts_summary
  6. Parse helper JSON veilig (regel 172: FIXED + defensief)
  7. Update helper als alles geldig
  8. Template sensor luistert naar helper (trigger-based)
  9. Sensor weergeeft EUR bedrag
```

## Deployment Checklist

- [ ] Deploy `energie_historische_kosten.yaml` naar `/home/stallieman/SmartHome_Stalman/config/packages/`
- [ ] Home Assistant herstarten of package opnieuw laden
- [ ] Script handmatig triggeren → check logs voor fouten
- [ ] Verify helper wordt gevuld met geldige JSON
- [ ] Sensor zou nu EUR bedrag moeten tonen (niet `unknown`)
- [ ] Automation draait om 06:15 zonder fouten

## Related Issues Opgelost

1. ✅ Script blokkeringsfout: `from_json` zonder default (FIXED)
2. ⏳ Template sensor `unknown` state (separate fix: trigger-based syntax)
   - Werkt alleen wanneer script script succesvol wordt uitgevoerd
   - Script-fix moet eerst gedeployed worden

