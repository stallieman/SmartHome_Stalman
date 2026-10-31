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


## Revisie Overzicht

- Vier YAML-bestanden geparseerd; 43 ingebouwde kaarten totaal en 32 gedocumenteerde referenties.
- Overige views structureel vergeleken met `f9baab7`: exact ongewijzigd, inclusief titels en URL-paden.
- Overzicht: maximaal twee kolommen, één energiestroomvisualisatie en één verbruiksgrafiek, geen extra historie- of datumkaarten.
- Grote cijferkaarten met Jinja getest bij numerieke én onbeschikbare waarden. Bij ontbrekende tarieven verschijnt geen fictieve nulbesparing.
- Dagbalans, dagscenario, ontbrekende bron en uitgeschakelde tariefbevestiging met synthetische waarden getest.
- Vijf dagmeters op dagelijkse cyclus en beschikbaarheidsinstellingen gecontroleerd. Eerste onvolledige dag zichtbaar vermeld.
- Bestaande bron-ID’s opnieuw read-only via SSH gecontroleerd in het entity-register; alle benodigde P1-, Growatt- en batterijbronnen staan ingeschakeld. Ook de eerder toegevoegde woningvermogen- en financiële templates zijn inmiddels geregistreerd.
- Geen live sensorstatus of frontend-rendering gecontroleerd. Volledige HA-schema- en iPhone-/desktopvalidatie blijven onderdeel van de installatie na toestemming.
- Geen serverbestanden gewijzigd, geen Home Assistant-herstart en geen push uitgevoerd.

## Financiële revisie · 2026-10-31

28 onafhankelijke unittest-scenario's slagen: korting uitsluitend op levering, reeds verwerkte korting, btw-basis, normaal/dal, jaarlijkse saldering, overschot, terugleverkosten, verliezen via netmetingen, negatieve besparing, nulprijzen, ontbrekende/ongeldige data, overlappende plannen en ingangsdatum. Historische jaarreferentie beïnvloedt geen meetberekening. YAML en HA-templates slagen met tests voor onbeschikbare, oude en verouderde dagrapporten. Commandoregeladapter geeft bij lege productie-invoer `unavailable` met null-bedragen. Geen HA-schema-/live test of serverwijziging uitgevoerd. Zie FINANCE.md voor de geblokkeerde gegevensaanvoer en vereiste contractinformatie.
