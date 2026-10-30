# Validatie · 2026-10-30

- Vier nieuwe YAML-bestanden succesvol geparseerd; dubbele sleutels geweigerd.
- Drie unieke views, 47 ingebouwde kaarten, maximaal drie kolommen, gedeelde energiecollectie en bestaand lokaal thema gecontroleerd.
- Alle 21 gebruikte bestaande sensoren zijn via SSH gevonden in `core.entity_registry` en niet uitgeschakeld. Zes nieuwe entiteiten komen uit het meegeleverde package. Geen ontbrekende entity-ID’s in deze registervergelijking.
- Eenheden uit het register gecontroleerd: P1/Growatt-vermogen W, energie kWh, gas m³; batterijvermogen kW, opgeslagen energie kWh, SoC %, geld EUR.
- Templateberekeningen met Jinja2 getest: woningvermogen bij import/export, begrenzing op nul, ontbrekende bron, uitgeschakelde tariefbevestiging, vaste tariefberekening, nulprijzen, negatieve netto scenario-uitkomst en onbekende simulatorwaarde. Testwaarden zijn synthetisch en staan uitsluitend in het validatiescript.
- Ontbrekende gegevens maken templates onbeschikbaar; geen gefabriceerde historie of tariefwaarden in het dashboard.
- Bestaand dashboard, hoofdconfiguratie, integraties en Docker-configuratie niet gewijzigd. Serveronderzoek uitsluitend read-only; geen sudo, tokens of authenticatiebestanden.

Reproduceren met Python, PyYAML 6.0.3 en Jinja2 3.1.6:

```sh
python3 -m venv /tmp/stalman-dashboard-check
/tmp/stalman-dashboard-check/bin/pip install PyYAML==6.0.3 Jinja2==3.1.6
/tmp/stalman-dashboard-check/bin/python scripts/validate_energy_dashboard.py
```

Dit is een offline structuur- en templatecontrole, geen volledige Home Assistant-schema-validatie. HA-configuratiecontrole, actuele sensorbeschikbaarheid, Recorder-statistieken en visuele desktop/iPhone-controle zijn nog niet uitgevoerd. Daarvoor is de nog niet toegestane activatie nodig. Er is geen screenshot of preview die een daadwerkelijk gerenderd HA-dashboard suggereert.
