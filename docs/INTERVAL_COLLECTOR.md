# Bronbewuste P1 / Marstek-verzameling — revisie 2

**Aanvulling:** een standaard uitgeschakeld, lokaal auditvoorstel is toegevoegd. Zie [BATTERY_SYNC.md](BATTERY_SYNC.md). De onderstaande blokkade blijft gelden voor de ongewijzigde simulator en ruwe snapshots; alleen een afzonderlijk goedgekeurde atomaire auditproducent kan het nieuwe vensterkanaal gebruiken.

Lokaal ontwikkeld na de live steekproeven. De server is uitsluitend read-only onderzocht. Er is niets geïnstalleerd of herstart.

## Onderzoek: de benodigde simulatorinformatie ontbreekt

De eerdere API-steekproeven lieten circa 10–20 seconden tussen P1-importupdates en circa 60 seconden tussen simulator-importupdates zien. Statische exporttellers en het inactieve tariefregister konden urenoude `last_reported`-waarden hebben. De eis uit `6fa804e` dat alle counters iedere minuut opnieuw rapporteerden, met maximaal 10 seconden onderling verschil, verwierp daardoor ook bruikbare bronwaarnemingen.

Read-only controle van de **geïnstalleerde** Battery Simulator bevestigt:

- `__init__.py:859–861`: periodieke verwerking via `async_periodic_update`.
- `__init__.py:883–948`: bronwijzigingen worden als tellerdelta's intern geaccumuleerd; gelijke waarden worden overgeslagen.
- `sensor.py:349–385`: de gesimuleerde import biedt een afgerond percentage bespaarde import; export heeft geen bronperiode-attributen.
- `sensor.py:514–532`: de hoofdsensor biedt instellingen, bron-entity-ID's, status en opnamestart, geen verwerkte tellergrens.
- `__init__.py:1379–1428`: gesimuleerde tellers worden verhoogd en sensorupdates verstuurd; een verwerkte P1-meetperiode wordt daarbij niet als openbaar attribuut meegegeven.

Een API-controle van alleen de relevante attributen bevestigde dit: import bevat onder meer `last_reset` en `percentage_import_energy_saved`; export `last_reset`; de hoofdsensor onder meer `sources` en `date_recording_started`. Geen van deze attributen identificeert de daadwerkelijk verwerkte P1-import/exportstanden of de simulatiebatch. De afgeronde procentwaarde is daarvoor ook ongeschikt. Tokeninhoud en overige HA-configuratie zijn niet opgeslagen.

**Conclusie:** de collector kan bronwaarnemingen betrouwbaar bewaren en fouten herkennen, maar kan nu niet aantonen welke werkelijke P1-meetperiode bij een simulatie-update hoort. `last_updated`, `last_reported`, ongeveer gelijke tijden, vergelijkbare delta's of een handmatige bevestigingsvlag lossen dat niet op.

## Nieuwe verwerking

`collector.py` bewaart twee onafhankelijke reeksen:

| Bronreeks | Inhoud | Classificatie |
|---|---|---|
| `measured_p1` | Import/export totaal, tariefregisters 1/2 en actieve tariefcode | Gemeten tellerwaarnemingen |
| `simulated_marstek` | Gesimuleerde import/export | Virtuele batterij, simulatie |

De entity-ID's staan ongewijzigd in `collector.json`. P1-tariefregisters blijven als codes 1/2 geregistreerd; normaal/dal wordt niet geraden. Onbevestigde mapping verhindert de ruwe registratie niet. Alleen een expliciet bevestigde mapping wordt als metadata meegegeven.

Het afzonderlijke HA-package is voorbereid op een snapshot iedere tien seconden, plus HA-start en tariefwijzigingen. Dat is één leesmoment voor transport, **geen gesynchroniseerde meetperiode**. De collector beoordeelt en bewaart elke bron apart. Uitval van de simulator wist de bruikbare P1-reeks niet, en omgekeerd.

Per bron krijgt een waarneming een status:

- `baseline`: eerste bruikbare tellerstand, of nieuwe baseline na ontbrekende brondata.
- `counter_changed`: waargenomen tellerwijziging, met de verschillen tussen de waargenomen standen.
- `reported_unchanged`: opnieuw gerapporteerd, maar tellerstanden gelijk.
- `unchanged_observation`: dezelfde standen en dezelfde bronrapporten opnieuw uitgelezen; **geen bewezen nulverbruik**. De geobserveerde intervaldelta blijft dan `null`.
- `unavailable`: ontbrekende/niet-numerieke teller, verkeerde eenheid, herstelde state of ongeldige tijdmetadata. Geen vervanging door nul.
- `discontinuity`: gat in snapshots, HA-herstart, reset, teruglopende timestamp of gewijzigde collectorconfiguratie. Geen delta over die grens.

Alle delta's heten uitdrukkelijk `observed_counter_deltas`, niet verwerkte energie per tarief. Zelfs een opnieuw gerapporteerde ongewijzigde teller bewijst niet dat de simulator een bepaalde P1-periode heeft verwerkt.

## Onveranderde tellers en bronactiviteit

Een oude timestamp van een onveranderde exportteller is geen automatische fout meer. P1-import kan intussen wel activiteit tonen. `recent_activity_observed` beschrijft uitsluitend of **een** state in die bron recent rapporteerde: standaard binnen 45 seconden voor P1 en 120 seconden voor Marstek. Dit diagnostische veld bewijst geen integratie-heartbeat of actualiteit van alle andere counters. Het geeft nooit financiële toestemming en maakt een oude state niet kunstmatig vers.

Er is geen grens meer op het tijdverschil tussen P1 en Marstek. Er wordt niet op timestampafstand gepaard. De bestaande kWh-eenheden, geldigheid van getallen, resetmetadata en P1-somcontrole blijven gecontroleerd. Een tellerwijziging zonder passend bijgewerkte `last_updated` is verdacht en verbreekt de reeks. Statische tellers met oude tijden worden wel opgeslagen, met hun originele metadata.

## Opslag, gaten en herstarts

- SQLite `BEGIN IMMEDIATE` bewaart beide bronrecords en het transportsnapshot in één transactie. De CLI vergrendelt ook ingestie en export samen.
- Nieuwe tabellen: `snapshots_v2`, `source_observations_v2`, `faults_v2`. De v1-tabellen worden niet gewijzigd, verwijderd of naar betrouwbare financiële input gepromoveerd.
- Identieke heraanbiedingen zijn idempotent. Een afwijkend snapshot met hetzelfde tijdstip wordt als duurzame fout vastgelegd. Oudere snapshots worden niet over nieuwe baselines heen gelegd.
- Een procesherstart hervat de opgeslagen bronbaselines. Een nieuw HA-sessie-ID verbreekt beide observatievensters, ook als HA states herstelde.
- Bij snapshots om de tien seconden is de voorgestelde maximale transportafstand 15 seconden. Een gemiste poll is dan een gedetecteerd gat. Dit staat los van de P1-/simulator-rapportcadans. Schedulervertraging kan ook een discontinuïteit veroorzaken; er wordt geen energie bij verzonnen.
- Na een onbeschikbare bron wordt de volgende bruikbare stand alleen een baseline. Bij een reset wordt de huidige bruikbare stand de nieuwe baseline, zodat de reset niet als extra of negatieve energie wordt geteld.
- Een niet-zichtbare reset die tussen twee waarnemingen volledig inhaalt zonder resetmetadata is met alleen counters niet aantoonbaar. Deze beperking geldt ook voor andere tellercollectoren.

De SQLite-database en export blijven buiten Git. Bewaar bij back-ups een consistente database, bijvoorbeeld via SQLite's backup-API. Er is geen automatische verwijdering, retentie of risicovolle reparatie.

## Financiële export: verplicht geblokkeerd

`observations.json` bevat altijd:

```json
{
  "coverage_confirmed": false,
  "paired_grid_deltas_confirmed": false,
  "reason": "simulator_processed_p1_window_unavailable",
  "without": null,
  "with": null
}
```

Daarmee geeft `compare.py` geen eurobedragen. Ook `pairing_confirmed: true`, gelijke timestamps of door een gebruiker aangeleverde willekeurige `processed_p1_window`-velden kunnen deze blokkade niet opheffen. Er is bewust geen fictief watermarkprotocol geïmplementeerd dat de huidige integratie niet levert. De optionele eerste-dagbenadering uit v1 wordt niet meer gebruikt voor collector-export.

Een geslaagde collectoropdracht betekent nu **bronwaarnemingen verzameld**, niet **financiële vergelijking beschikbaar**. Ook nuldelta's, tariefwissels en middernacht maken van observaties geen geldige financiële periode. De bestaande financiële kern blijft tevens contractbevestiging, belasting/btw, geldigheidsperiode en jaarlijkse saldering controleren.

## Wat voor betrouwbare koppeling nodig is

Een volgende, afzonderlijk te ontwikkelen uitbreiding van de simulator moet een atomaire batch publiceren met ten minste:

1. Een unieke batch-ID en een reset-/sessiegeneratie.
2. De exacte daadwerkelijk verwerkte P1-bron-entity-ID's en begin-/eindtellerstanden, inclusief tariefregisters of aantoonbare tariefverdeling.
3. De bij diezelfde batch behorende gesimuleerde import-/exportbegin- en eindstanden.
4. Continuïteitsinformatie voor genegeerde/onbeschikbare brondata, zodat een bronuitval niet als nul wordt gecertificeerd.

Alleen dan kan een toekomstige matcher een-op-een batches koppelen, herhaling uitsluiten en tarief-/daggrenzen controleren. Alleen een nieuw tijdstipattribuut is onvoldoende. Die integratie-uitbreiding is **niet** gedaan en vereist een aparte opdracht/beoordeling.

## Tests en aantoonbare verbetering

```sh
python3 -m unittest discover -s tests -v
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_interval_collector.py
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_energy_dashboard.py
```

De regressies gebruiken synthetische gegevens met de gemeten cadans: P1 iedere tien seconden, Marstek iedere zestig seconden en urenoude onveranderde export-/tariefstates. Een directe vergelijking met de code uit `6fa804e` toont dat v1 het snapshot afwijst als verouderd, terwijl v2 de veranderde P1 en ongewijzigde simulator afzonderlijk bewaart. Beide gevallen mogen geen eurobedragen produceren zonder bronperiodebewijs.

Verder worden bronuitval zonder verlies van de andere bron, resets en herstelbaselines, gaten, HA-/procesherstarts, timestampregressie, ongeldige waarden/eenheden, idempotentie, conflicterende duplicaten, transactie-rollback, behoud van het v1-archief en pogingen om financiële blokkering te omzeilen getest. YAML en de native snapshot-template bevatten nu ook `last_updated` en worden offline gecontroleerd.

Live HA-schema-/runtimevalidatie van deze revisie is niet uitgevoerd. Er is niets geïnstalleerd. De template- en unittestvalidatie geven toestemming voor een lokale commit, niet voor toepassing op de server.

## Latere installatie

Alleen na afzonderlijke toestemming, een geldige back-up en HA-configuratiecontrole: plaats collector, configuratie en het aparte package; registreer het package naast de bestaande configuratie, zonder het UI-dashboard te wijzigen. De dagelijkse financiële uitvoer blijft geblokkeerd. Controleer vooraf helper-/automation-ID's en schrijfrechten. Een eventuele herstart valt buiten deze opdracht.

Officiële achtergrond: [HA state-object](https://www.home-assistant.io/docs/configuration/state_object/), [state-machine en last_reported](https://contributors.home-assistant.io/core/internals/states/) en [Shell Command](https://www.home-assistant.io/integrations/shell_command/).
