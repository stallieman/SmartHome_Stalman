# Installatieplan — Battery Simulator-audit en financiële vergelijking

**Datum:** 31 oktober 2026. **Status: NO-GO voor productieactivatie.**

Dit plan is aanvankelijk als enige bestand toegevoegd. De vervolgens afzonderlijk toegestane lokale fase-A-proef is op 31 oktober uitgevoerd; zie §2. Er is niets op de actieve server geïnstalleerd of herstart en niets gepusht. Alle hieronder beschreven server-schrijfacties en serverherstarts zijn **toekomstige stappen**, waarvoor afzonderlijke toestemming nodig is. Bij ontbrekende rechten stoppen en de beheerder inschakelen; geen sudo of andere omweg.

## 1. Vastgestelde uitgangssituatie

- Lokale repository `SmartHome_Stalman`: HEAD `1d6e3b65a5941fa7fe1042c1cc63c0ff85b1d360`; geen latere commits en vóór dit plan een schone werkboom.
- Op 31 oktober opnieuw uitsluitend read-only via bestaande SSH-toegang gecontroleerd: `/home/stallieman/SmartHome_Stalman/config/custom_components/battery_sim`.
- HACS registreert `hif2k1/battery_sim`, `version_installed: v2.9.0`, `installed_commit: aaac361`. Het integratiemanifest zegt `2.7.0`; dat is ook het gedocumenteerde upstream-manifest. Deze metadata alleen bewijst geen bronidentiteit. De vier hieronder gecontroleerde bestanden zijn wél bytegelijk aan de gepinde testbron. Geen volledige integratiemapvergelijking uitgevoerd.
- `stalman_audit.py` is niet geïnstalleerd. Het lokale voorstel wijzigt uitsluitend import/decorators in de initializer; de oorspronkelijke batterijmethod bodies blijven AST-gelijk.
- Actieve batterijbinding: `01M678WZZ6M086SEWQ1QENFZ8Z`; één P1-import- en één P1-exportbron, beide zonder simulator-tariefinformatie. Vastgestelde instellingen: 5,12 kWh, maximaal laden 2,5 kW, ontladen 0,8 kW, laad-/ontlaadefficiëntie ieder 0,91 en updatefrequentie 60 seconden. Deze instellingen moeten behouden blijven.
- Op de server staat alleen package `energie_thuisbatterij.yaml`; de hoofdconfiguratie includeert dit als `stalman_energie`. Geen bestanden aangetroffen in `config/energy_finance`; auditadapter en intervalcollector zijn niet als package aanwezig. Het bestaande package is niet volledig met de lokale versie vergeleken.
- Het onderzochte serverpad bestaat en is geen afwijkend symlinkdoel. De daadwerkelijke Docker-bindmount, actieve image-ID/digest en huidige draaiende Core-versie zijn in deze controle **niet opnieuw vastgesteld**. De lokale Compose gebruikt een veranderlijke `stable`-tag; geen image pull of upgrade combineren met deze wijziging.

### Gecontroleerde SHA256-identiteiten

| Bestand in `custom_components/battery_sim` | Geïnstalleerd = gepinde bron |
|---|---|
| `__init__.py` | `a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6` |
| `sensor.py` | `c6a137075d962c43fc88246ba078b81ce98269dbe2f7ae0379ba0cddad129724` |
| `const.py` | `c84a30d515e842897364b6a96b4ca1144932f278e24f91bef8e0f59a64932dbc` |
| `helpers.py` | `8d5bd7d6772cf9093798a3c383c1c0ec68a8f6d1f2da6d8a30e5b19623019b9e` |

Lokale helperhash, gelijk aan `collector.json.audit.expected_helper_sha256`:
`b5e61c635b572cc965c52aa94c824b15a4e57e277ae75a17d834594e8f4561c9`.
Een hashafwijking bij een latere controle betekent stoppen, niet de verwachte hash aanpassen om verder te kunnen gaan. HACS-commitmetadata `aaac361` niet verwarren met de gedocumenteerde releasecommit `4cb396ff635f235787b42a51734ffef4168c330e`.

## 2. Wat bewezen is en wat nog een toegangspoort vormt

Bestaand bewijs uit `1d6e3b6`: 95 unittests, drie offline validators en zes geïsoleerde Home Assistant 2026.10.4-runtimegevallen geslaagd. Exacte P1-eventketens, tariefregistergrenzen, ruwe simulatiecounters en SQLite-uitvoer zijn vergeleken; oorspronkelijke en geïnstrumenteerde modellen leverden identieke resultaten. Zie [synchronisatiebewijs](BATTERY_SYNC.md) en [validatie](VALIDATION.md). Geen tests herhaald voor deze documentatiewijziging.

Het eerdere bewijs is geen volledige Core-/config-entry-/platformsensorproef en gebruikte rechtstreeks collectorfuncties met afwijkende batterijparameters. Deze leemte is nu lokaal aanvullend getest met [validate_battery_installation.py](../scripts/validate_battery_installation.py): zes afzonderlijke Python-processen in de netwerkloze HA 2026.10.4-container starten originele/geïnstrumenteerde integraties via echte config-entries en alle upstream-platforms, inclusief de drie bestaande packages. Alleen synthetische sources en een zelf aangemaakte config-entry worden gebruikt, zonder productiecredentials of `.storage` over te nemen. De test gebruikt exact 5,12 kWh, 2,5/0,8 kW, 0,91/0,91 en 60 seconden.

De keten native snapshot en audit-event → queued automation → shell_command → collector-CLI → SQLite → atomaire JSON → financiële command_line-sensor → window-templates slaagt. Startup-sequence 1, acht dubbele bezorgingen, ontbrekend/laat pakket, ongeldige CLI-invoer en uitgeschakelde auditpolicy worden gecontroleerd. Productiecontractinvoer blijft onbeschikbaar; een uitsluitend lokaal synthetisch bevestigd plan controleert ook de geslaagde euroberekening. Bij geen nieuwe events groeit de meetdekking niet en wordt geen actuele dagbesparing vrijgegeven.

Een echte procesherstart krijgt een nieuwe auditgeneratie. Het batterijresultaat na herstel is gelijk aan de originele code gestart uit dezelfde opgeslagen toestand. Een stilstaande back-upkopie wordt met de originele initializer, zonder helper en zonder auditpackages teruggezet; oorspronkelijke werking en batterijbinding worden tegen een onafhankelijke restore gecontroleerd. **Upstream bewaart/herstelt batterij-energie via de op drie decimalen afgeronde sensorstate**: bijvoorbeeld 2,5832646520146523 → 2,583 kWh. Dit bestaande gedrag is ook zonder audit identiek en wordt niet veranderd of als exact behoud van interne floats gepresenteerd.

Deze proef test echte HA-bootstrap/config-entry-/platform- en transportfunctionaliteit, geen HTTP/frontend, hardware, onbeperkte queuebelasting of productieback-uprechten. Alleen de nieuwe acceptatieproef is uitgevoerd; de ongewijzigde bestaande suites zijn niet onnodig herhaald.

De audit ondersteunt één P1-paar zonder extra solar-cap-bron. Een gemengde tariefbatch, daggrens, ontbrekend pakket, reset of onbetrouwbare registergrens blijft uitgesloten. Na herankering is uitsluitend een nieuw expliciet venster toegestaan; ontbrekende perioden zijn geen nulverbruik. De huidige collector selecteert de nieuwste generatie, geen jaararchiefsamenvatting. Dit is dus nog geen oplossing voor volledige dagen of jaarlijkse afrekening.

## 3. Financiële vrijgavevoorwaarden

De onderstaande ontbrekende invoer blokkeert **euroactivatie**, maar verhindert een afzonderlijke audit-only-proef niet.

| Onderdeel | Bekend / nog vereist |
|---|---|
| P1-mapping | Bevestigd: `1 = offpeak/dal`, `2 = normal/normaal`; HA-overgang 30-10-2026 22:59:50 +01:00. Geen nieuwe mapping nodig. |
| 2026 import | Normaal € 0,31274 en dal € 0,30911/kWh vóór korting; 10% uitsluitend op levering. Effectief € 0,292551 / € 0,289284 onder de beschreven btw-basis. Nog contractnota met btw-basis en exacte begin-/einddatums nodig. |
| 2026 saldering | Volledige afrekenperiode en bevestigde normaal/dal-salderingstoewijzing nodig. Korte auditvensters worden bewust niet als dagelijkse besparing berekend. Historie kan niet achteraf uit huidige tellers worden afgeleid. |
| 2026 terugleverkosten | Eén band bekend: 1.251–1.500 kWh, € 0,48970/dag. Volledige staffels, kas-/btw-basis, volumeregels en factureerbare dagen ontbreken; de kern vraagt een bevestigd volledig-periodebedrag per scenario. Vergoeding boven saldering € 0,15/kWh zonder btw is vastgelegd. |
| 2027 | Exportvergoeding € 0,08343/kWh zonder btw; exportkosten € 0,08092/kWh. Importtarieven normaal/dal, btw-/kasbasis van kosten en contractgeldigheid ontbreken. 2026-importprijzen niet automatisch doortrekken. |
| Vaste kosten | € 0,34490 + € 1,30365 − € 1,72317/dag; geldigheidsperiode en btw-/factuurbasis ontbreken. Alleen nodig voor totale kosten; nooit als batterijbesparing tellen. |

Laat alle onbevestigde contractvlaggen ongewijzigd. De historische jaarrekening 2024–2025 is alleen referentie. Een uitkomst met virtuele Marstek is een simulatieschatting, geen gerealiseerde besparing. Zie [financiële regels](FINANCE.md).

## 4. Uitvoeringsvolgorde met expliciete beslismomenten

### Fase A — eerst lokaal voorbereiden, nog geen serverinstallatie

1. Laat de eigenaar dit gefaseerde plan beoordelen. Verzamel ontbrekende contractinformatie afzonderlijk; audit-only en eurovrijgave zijn twee verschillende toestemmingen.
2. Bereid na toestemming voor verder lokaal werk een reviewkopie met de bestaande [transformer](../proposals/battery_sim_audit/prepare_patch.py) uit de exact gepinde bron. Bewaar origineel, gegenereerde initializer, helper en een bestands-/hashmanifest gescheiden. Niets rechtstreeks in de actieve HACS-map genereren.
3. Voer in een geïsoleerde, netwerkloze HA 2026.10.4-omgeving een volledige configuratie-/transportproef uit met de Marstek-instellingen uit §1. Gebruik alleen synthetische meters, geen productiecredentials of gekopieerde volledige `.storage`.
4. Neem ook het [auditadapterpackage](../config/packages/energie_audit_adapter.yaml), [broncollectorpackage](../config/packages/energie_intervalcollector.yaml), shell_command, financiële command_line-sensor en templatebeschikbaarheid mee. Verifieer correcte YAML-samenvoeging, entity-ID's, Python/zoneinfo, schrijfrechten, queuebelasting, lockgedrag en atomaire JSON-export.
5. Controleer specifiek dat de adapter bij startup de eerste batch van een generatie ontvangt. Een verloren sequence 1 mag geen financiële vrijgave geven. Test ook commandofout, pakketverlies, dubbele bezorging, herstart van collector en stoppen van audit-events. Een oud venster mag niet als actuele dekking worden gepresenteerd; de huidige window-sensoren tonen historische vensters, geen heartbeatgarantie.
6. Controleer dat een consistente back-up in deze proef werkelijk teruggezet kan worden. Herhaal gerichte bestaande tests alleen bij wijzigingen aan code/configuratie of een gewijzigde bronversie.

**GO naar B alleen:** complete transportproef met actieve parameters geslaagd, geen modelverschillen, geen bedragen bij onbetrouwbare invoer, herstelproef geslaagd. Deze lokale proef is nu groen, maar fase B/C vereist nog afzonderlijke toestemming.

Reproduceren met een volledige lokale kopie van de gepinde v2.9.0-integratie (inclusief manifest en platformbestanden), zonder netwerk of productiemount:

```sh
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -v /pad/naar/gepinde/battery_sim:/upstream:ro \
  --entrypoint python3 ghcr.io/home-assistant/home-assistant:2026.10.4 \
  /workspace/scripts/validate_battery_installation.py --source /upstream/__init__.py
```

De repository en upstream-bron blijven read-only; tijdelijke configuraties, `.storage`, SQLite en reviewkopieën bestaan alleen in de container en worden na de proef opgeruimd.

### Fase B — preflight en back-up door bevoegd beheerder

Pas na aparte toestemming voor gecontroleerde installatie:

1. Bevestig met bestaande leesrechten de daadwerkelijk actieve `/config`-mount, Core-versie, container/image-ID en digest, bestandsownership en beschikbare opslag. De bestaande documentatie noemt ook `/home/stallieman/containers/homeassistant`; gebruik dat pad niet zonder de actieve mount te verifiëren. Bij noodzakelijke extra rechten stoppen.
2. Hercontroleer de vier bronhashes, helperhash, batterijbinding, P1-entity-ID's en Marstek-instellingen vlak vóór uitrol. Controleer actuele sensorunits, reset-/restored-status en ontbreken van extra solar-cap-invoer.
3. Leg alle te wijzigen bestaande bestanden, owner/mode en includeplaatsen vast. Inventariseer vooraf de simulatoropslag met de bestaande beheer-/backupvoorziening: de gerichte naamcontrole leverde geen `.storage/*battery*`-bestand op en bewijst niet dat er geen opgeslagen simulatorstatus is.
4. Maak met de goedgekeurde back-upvoorziening een herstelbare, afgeschermde back-up van configuratie, oorspronkelijke volledige integratiemap, relevante `.storage`/simulatorstatus en bestaande financiële runtimebestanden. Secrets horen alleen in beveiligde back-upopslag buiten Git en chat; geen tokens lezen, tonen of naar testcontainers kopiëren.
5. Gebruik voor een bestaande SQLite-database de SQLite-backup-API of een consistente snapshot nadat de betreffende writers zijn gestopt. Kopieer geen losse actieve `.sqlite` zonder rekening te houden met WAL. Behandel Recorder apart met de ondersteunde backupmethode; geen live databasebestanden overschrijven.
6. Verifieer back-upmanifest, leesbaarheid en herstelprocedure. Bewaar de huidige image-identiteit; geen `pull`, HACS-update of afhankelijkheidsupgrade tijdens deze wijziging. Spreek een kort onderhoudsvenster, uitvoerder en rollbackmoment af. Leg HACS-updatebeheer vast: hooks zijn versiegebonden en mogen niet stilzwijgend overschreven worden.

### Fase C — gecontroleerde audit-only-installatie

Alleen na GO op A/B en expliciete toestemming voor het onderhoudsvenster en benodigde herstart:

1. Houd de financiële contractplannen onbevestigd. Bereid een expliciete lijst met toegestane bestanden voor: gegenereerde `custom_components/battery_sim/__init__.py`, bijbehorende `stalman_audit.py`, de bestaande vier Python-/JSON-kernbestanden (`collector.py`, `batch_contract.py`, `compare.py`, `collector.json`) plus `tariffs.json`, de twee collector-/auditpackages en de gerichte financiële package-/dashboardwijzigingen. Geen volledige repository-sync; geen `.storage`, secrets of voorbeeldwaarnemingen uitrollen.
2. Plaats bronbestanden uitsluitend tijdens de goedgekeurde stop-/startprocedure, niet terwijl de integratie deels uit oude en deels uit nieuwe bestanden kan worden geladen. Geen integratie verwijderen/opnieuw toevoegen, batterij resetten of bestaande instellingen wijzigen.
3. Voeg package-includes toe in de bestaande `homeassistant.packages`-structuur; behoud `stalman_energie` en alle bestaande dashboards. Merge de financiële packageversie na diffreview, vervang de actuele hoofdconfiguratie niet door een voorbeeld. Het bestaande activation-fragment bevat nog niet de audit-/collectorregistraties.
4. Geef de HA-gebruiker alleen de noodzakelijke toegang tot de financiële runtime-map; database/lock/JSON moeten schrijfbaar zijn. De auditpolicy mag uitsluitend na controle van batterij-ID en helperhash lokaal voor deze proef op `enabled: true`; dat is **geen** tarief- of eurobevestiging. Wijzig geen andere simulatorinstellingen.
5. Controleer de kandidaatconfiguratie vóór starten met de HA-configuratiecontrole van exact de actieve image in een geschikte stagingkopie; daarna de normale beheerprocedure voor configuratiecontrole. Bij fout stoppen en de originele bestanden terugzetten. Na groen één vooraf goedgekeurde herstart, zonder image-update.
6. Controleer dat oorspronkelijke entiteiten en modelinstellingen behouden zijn, de auditproducent en adapter zonder fouten laden en elke ontvangen batch duurzaam in SQLite staat. Let op sequence/generation, registeridentiteit, gedeelde before/after-counters, ontbrekende pakketten en queued-automationfouten. Test geen resets of uitval door productiesensoren te manipuleren.
7. Observeer meerdere verwerkingen en ten minste een natuurlijke normaal/dal-overgang. Controleer dat de overgangsbatch wordt geweigerd en een volgend venster expliciet nieuw begint. Vang dagelijkse grens- en herstartsituaties in staging af; forceer geen productieherstart voor zo'n proef.
8. Accepteer audit-only uitsluitend als geen dubbel getelde of overbrugde delta ontstaat, de onbevestigde financiële configuratie `unavailable`/null oplevert en de bestaande HA-functies normaal werken. Bewaar beperkt bewijs zonder credentials buiten Git. Laat de gebruiker eerst deze resultaten beoordelen.

### Fase D — financiële vergelijking afzonderlijk vrijgeven

Alleen na een nieuwe toestemming, volledige contractbevestiging en passende meetdekking:

- Vul uitsluitend werkelijk bevestigde tarieven/periodes in. Controleer 10% korting op alleen levering, eenmaal btw, 2026-saldering en scenarioafhankelijke terugleverkosten; vaste kosten blijven buiten besparing.
- Periode- of tariefwijziging vereist passend afgebakende input. De kern rekent één plan per periode en kan het huidige auditvensterkanaal niet tot een volledige 2026-afrekening samenvoegen. Dit is een functionele blokkade, geen vinkje dat een beheerder mag overrulen.
- Vanaf 2027 zijn enkel bewezen vensters waardeerbaar als de 2027-invoer bevestigd is. Controleer scope `window` en zichtbare begin-/eindtijden; geen dag-, jaar- of terugverdientijdclaim. Ontbrekende prefixes en uitgesloten overgangen niet aanvullen.
- Bevestig gelijke begin-/eindperiode en interpreteer afwijkende begin-/eind-SoC als vensterkasstroom, niet als stationaire jaarbesparing. Zolang volledige dekking ontbreekt blijven dag-/afrekentotalen onbeschikbaar.

## 5. Stopcriteria en rollback

**Direct stoppen met vrijgave:** bronhashwijziging, onvolledige back-up, onbekende mount/rechten, gewijzigde batterijbinding, model-/configafwijking, queue-/schrijffouten, financiële bedragen zonder geldig bewijs of onvoldoende brondekking. Een normaal geweigerde overgangsbatch is geen modelstoring, maar mag nooit een fictief compleet totaal worden.

Rollback wordt vooraf door dezelfde bevoegde beheerder goedgekeurd en uitgevoerd:

1. Blokkeer financiële publicatie, schakel auditontvangst uit via de beheerprocedure en stop de betrokken writers vóór herstel. Bewaar incidentdatabase, JSON en foutbewijzen afgeschermd; niet wissen of als betrouwbare input hergebruiken.
2. Zet de originele initializer en oorspronkelijke integratiemap terug volgens het back-upmanifest; verwijder alleen de nieuw toegevoegde helper als die vóór installatie ontbrak. Herstel uitsluitend gewijzigde YAML-/JSON-bestanden en includeplaatsen. Behoud bestaande dashboards en helpers.
3. Controleer de herstelde configuratie en bronhashes; voer alleen de afzonderlijk toegestane herstart uit met dezelfde image. Bij ontbrekende rechten stoppen en overdragen.
4. Controleer oorspronkelijke sensorbeschikbaarheid, instellingen en modelstatus. Herstel niet automatisch oude volledige `.storage` of Recorder over nieuwe gegevens heen: alleen als dat aantoonbaar nodig is en de beheerder expliciet een coherent herstelpunt kiest. Geen handmatige state-/countercorrecties.
5. Hergebruik een tijdens de proef ontstane generatie niet na rollback/herinstallatie. Bewaar databases als bewijs; een nieuwe proef begint met een nieuwe geldige auditgeneratie en expliciete meetgrenzen. Oude euro-export mag niet als actueel worden getoond.

## 6. Besluit en eerstvolgende veilige stap

**Nu geen productie-installatie of financiële activatie.** De lokale fase-A-acceptatieproef met de actieve 5,12-kWh/0,8-kW-instellingen is geslaagd. De operationele preflight, actuele mount-/imagecontrole, herstelbare productieback-up, beheerrechten en afzonderlijke installatie-/herstarttoestemming uit fase B/C blijven nodig. Financiële jaartotalen hebben daarnaast meetdekkings- en contractblokkades.

Eerstvolgende veilige stap: laat de eigenaar de lokale proef beoordelen en bepaal daarna de toestemming voor fase B; geen automatische overgang naar installatie. Contractnota en volledige tariefinformatie kunnen parallel worden aangevuld. Tot een expliciete volgende opdracht blijven server, HACS-installatie en alle productie-activeringsvlaggen ongewijzigd.
