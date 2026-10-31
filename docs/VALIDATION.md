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

## Intervalverzamelaar · 2026-10-31

61 unittests slagen (bestaande financiën plus collector): tellerdelta's, normaal/dal-toewijzing, idempotentie, conflicterende duplicaten, ontbrekende intervallen, onbeschikbare en niet-opnieuw-gerapporteerde states, resets, HA-/procesherstart, tariefwissels, timestampkwaliteit, plausibiliteitsgrenzen, zomer-/wintertijd, configuratiewijzigingen, atomaire export en invoer voor de financiële rekenkern. Collector-YAML, native snapshot-template, ontbrekende-statepad en shell-argumentcodering zijn apart offline gecontroleerd. Alle testmetingen zijn synthetisch en staan buiten productieopslag. Geen servercontact, HA-schema-validatie of runtimecontrole uitgevoerd.

## Bronbewuste revisie na live onderzoek

De oorspronkelijke eis van recente timestamps voor alle tellers is vervangen door onafhankelijke P1-/simulatorwaarnemingen. Het read-only broncode- en API-onderzoek bevestigt dat de geïnstalleerde simulator geen verwerkte P1-meetperiode publiceert. Financiële collector-export is daarom onvoorwaardelijk geblokkeerd; een handmatige vlag kan dat niet omzeilen. De regressietest vergelijkt rechtstreeks met `6fa804e`: oude statische exporttimestamps worden nu bruikbaar bewaard naast actieve import, zonder onterechte financiële koppeling. Zie INTERVAL_COLLECTOR.md. Productiedata of tokens zijn niet opgeslagen.

Resultaat bronbewuste revisie: 58 unittests geslaagd, plus beide offline YAML-/templatevalidators en `git diff --check`. Geen serverwijziging, herstart of push.

## Synchronisatieonderzoek en auditvoorstel

87 unittests slagen. Drie offline validators slagen voor dashboard, broncollector en auditadapter. De echte upstream-initializer uit v2.9.0 is met de gedocumenteerde geïnstalleerde SHA256 vergeleken en lokaal getransformeerd; alle oorspronkelijke method bodies blijven AST-gelijk, voorgestelde code compileert.

## Geïsoleerde Battery Simulator-runtime · 2026-10-31

Zes aanvullende tests slagen in de officiële Home Assistant 2026.10.4 ARM64-container (`sha256:23f4dfbb69ce76315dbc4de7915504f1c2dcecd7ca2648113a493a385972e133`), met `--network none`. De originele en geïnstrumenteerde upstream v2.9.0-code verwerken dezelfde synthetische Home Assistant state-events. De echte HA-state machine/eventbus, batterijbronhandler, periodieke update en `update_battery` worden uitgevoerd. De modelstatus en gesimuleerde netcounters zijn na elke verwerking identiek. Geldige auditbatches lopen door de SQLite-collector, contractvalidatie en financiële kern; identieke batchheraanbiedingen tellen niet dubbel.

De proef dekt P1-updates op twee- en tienseconden-cadans, vertraagde simulatorverwerking, exacte P1-register-/eventgrenzen, tariefmapping en tariefwissel, ontbrekende gegevens, dubbele events, P1-reset en HA-herstart. Ongeldige vensters blijven onbeschikbaar; herstel begint met een nieuwe auditgeneratie. Dit is geen volledige HA-appstart, config-entry-/platformsensorintegratietest, hardwaretest of hercontrole van de actieve HACS-installatie. De auditpolicy blijft uitgeschakeld; productie en geïnstalleerde HACS-bestanden zijn niet gewijzigd.

## Lokale installatie-/transport-/rollbackproef · 2026-10-31

De aanvullende `scripts/validate_battery_installation.py` start zes onafhankelijke Python-processen in een netwerkloze HA 2026.10.4-container: origineel, audit, origineel-herstartreferentie, audit-herstart, rollback en onafhankelijke back-uprestore. Echte HA-bootstrap, config-entry, upstream-platformsensoren en de drie bestaande packages laden met 5,12 kWh, 2,5 kW laden, 0,8 kW ontladen, efficiënties 0,91 en updatefrequentie 60 s. Geen productiecredentials of productie-`.storage` worden gebruikt.

De echte YAML-/shellketen schrijft snapshots en auditbatches naar SQLite en atomaire JSON; command_line en window-templates lezen het resultaat. De onbevestigde contractconfiguratie geeft geen geldbedragen. Met een uitsluitend synthetisch bevestigd lokaal plan komt de sensoruitkomst overeen met de getransporteerde tellerdelta's. Eerste startup-batch, acht dubbele events, ontbrekende/late batch, CLI-fout, uitgeschakelde auditpolicy en geen nieuwe events zijn gecontroleerd. Herstart en rollback behouden de oorspronkelijke modelwerking; upstream herstelt SoC-energie uit een op drie decimalen afgeronde sensorstate, niet uit de exacte interne float. Originele en geïnstrumenteerde herstart zijn hierin identiek.

De proef slaagt. Productie-installatie, productie-back-up, HTTP/frontend en hardware zijn niet getest. De bestaande suites zijn ongewijzigd en daarom niet opnieuw gedraaid. Zie [installatieplan](INSTALLATION_PLAN.md).

## Installatie-/rollbackscripts · 2026-10-31

29 gerichte synthetische deploymenttests slagen in een lokale virtuele omgeving met PyYAML. De twee Bash-entrypoints zijn standaard dry-run; Bash-syntax en `--help` zijn gecontroleerd. Tests gebruiken tijdelijke configuratie-/backupbestanden en volledig gemockte Docker-commando's. Getest zijn de volledig read-only root-dry-run, expliciete root- en runtimeautorisatie, volledige back-upmanifesten, vaste ownership/modes, apply en rollback, ontbrekende/onveilige back-ups, drift, configuratie- en schrijffouten, mislukte healthchecks en herstart zonder actieve wijzigingen als de gestopte momentopname mislukt. Er worden geen secrets of manifestinhouden gelogd.

Deze tests bewijzen de fail-closed orchestratielogica, niet de werking van echte Docker-lifecyclecommando's op productie. De volledige lokale unit-testsuite van 124 tests en de drie statische validators zijn opnieuw geslaagd; productiehandelingen zijn niet uitgevoerd. De bestaande HA-proef uit `dd502c5` blijft apart runtimebewijs. Zie [installatieplan §8](INSTALLATION_PLAN.md#8-installatie--en-rollbackscripts--uitsluitend-lokaal-ontwikkeld).

## Essent-contractscenario's · 2026-10-31

34 financiële unittests slagen. De brutotarieven € 0,31274/€ 0,30911 tellen op uit de opgegeven levering en energiebelasting. Onder de te bevestigen inclusief-btw-basis wordt 21% btw alleen intern verwijderd en eenmaal na de 10%-korting op levering toegepast; de resultaten zijn exact € 0,292551 normaal en € 0,289284 dal. Tests bewijzen dat dubbel toepassen van btw of korting niet gebeurt.

Een 2026-jaarnota-test controleert netting binnen de expliciete normale/dal-verdeling, vergoeding alleen op overschot, expliciete volledige-periode-terugleverkosten en variabele besparing. De 2026 staffel wordt niet omgerekend naar een fictief kWh-tarief. Een 2027-test controleert de opgegeven exportvergoeding/-kosten op een synthetisch bevestigd testplan; de productie-importtarieven, btw-basis van kosten en datumdekking blijven null/onbevestigd. Vaste-dagkosten worden alleen als aparte totale kosten getoond als basis, geldigheid en volledige meetgrenzen bevestigd zijn; ze veranderen de besparing niet.

De dashboardvalidator controleert variabele afrekenkosten en totale kosten inclusief vaste kosten als afzonderlijke sensoren. P1-tariefmapping is bevestigd als code `1` = dal en code `2` = normaal; tests controleren beide codes, de overgang `2` → `1` en gelijkheid tussen financiële en collectorconfiguratie. Productieplannen blijven geblokkeerd door de overige ontbrekende contract- en intervalgegevens. Zie FINANCE.md.
