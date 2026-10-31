# Installatieplan — Battery Simulator-audit en financiële vergelijking

**Datum:** 31 oktober 2026. **Status: geen productiehandeling zonder nieuwe toestemming.** Financiële activatie blijft NO-GO; audit-only-scripts zijn uitsluitend lokaal getest, zie §8.

Dit plan is aanvankelijk als enige bestand toegevoegd. De vervolgens afzonderlijk toegestane lokale fase-A-proef is op 31 oktober uitgevoerd; zie §2. Er is niets op de actieve server geïnstalleerd of herstart en niets gepusht. Alle hieronder beschreven server-schrijfacties en serverherstarts zijn **toekomstige stappen**, waarvoor afzonderlijke toestemming nodig is. Bij ontbrekende rechten stoppen en de beheerder inschakelen; geen sudo of andere omweg.

## 1. Vastgestelde uitgangssituatie

- Lokale repository `SmartHome_Stalman`: aanvankelijke planbaseline `1d6e3b6`, lokale installatieproef vastgelegd in `dd502c59ae21651a4d1820f4bc3f2df14f181d37`. Tijdens de read-only productiepreflight is HEAD nog `dd502c5`. Bestaande, niet aan deze opdracht gerelateerde lokale Ring-wijzigingen in `README.md`, `config/configuration.yaml`, `config/dashboards/ring_cameras.yaml` en `docs/RING_DASHBOARD.md` zijn ongemoeid gelaten. Alleen dit installatieplan wordt bijgewerkt.
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

**Nu geen productie-installatie of financiële activatie.** De lokale fase-A-acceptatieproef met de actieve 5,12-kWh/0,8-kW-instellingen is geslaagd. De read-only preflight uit §7 is een historisch meetmoment; de eigenaar heeft inmiddels mount/image en de nieuwe gecontroleerde back-up bevestigd (§8). Bevoegdheden en expliciete installatie-/stop-/starttoestemming blijven nodig; scripts controleren alle feiten opnieuw en proberen ontbrekende rechten niet te omzeilen. Financiële jaartotalen hebben daarnaast meetdekkings- en contractblokkades.

Eerstvolgende veilige stap: leg de blokkades voor aan de eigenaar en laat een reeds bevoegde beheerder de ontbrekende containergegevens en back-up-/herstelprocedure beoordelen. Geen rechtenverhoging of andere toegangsroute proberen. Het maken/vernieuwen van een back-up en elke installatie/herstart vereisen een nieuwe expliciete opdracht. Contractnota en volledige tariefinformatie kunnen parallel worden aangevuld. Tot die tijd blijven server, HACS-installatie en alle productie-activeringsvlaggen ongewijzigd.

## 7. Read-only productiepreflight · 31 oktober 2026, circa 11:04 CET

Uitgevoerd via `ssh homeassistant` als `stallieman`, zonder sudo, Docker-exec, API-token, configuratiecontrole, server-schrijfacties of herstart. Bestaande testresultaten van `dd502c5` zijn gebruikt; er zijn geen tests herhaald. Alleen archiefheaders en geselecteerde niet-geheime configuratie-/metadata zijn bekeken, geen back-upinhoud uitgepakt en geen credentialbestanden gelezen.

| Controle | Bevinding | Oordeel |
|---|---|---|
| Bereikbaarheid / Core-versie | Lokale HTTP-GET op `http://127.0.0.1:8123/` geeft 200. `config/.HA_VERSION` vermeldt `2026.10.4`. Dit bestand bewijst niet zelfstandig de draaiende procesversie. | HTTP bereikbaar; actieve Core-versie niet onafhankelijk vastgesteld. |
| Docker-container | `docker ps` via de bestaande socket geeft `permission denied`. Geen alternatieve of verhoogde toegang geprobeerd. Containerstatus, actieve image/digest en `/config`-bindmount konden niet worden bevestigd. | Blokkade. |
| Battery Simulator | Alle vier bronhashes uit §1 opnieuw identiek. Manifest blijft `2.7.0`, zoals de gepinde v2.9.0-bron. Geen audithelper aanwezig. De eerdere HACS-release-identificatie en de nu herbevestigde bronidentiteit passen bij het geteste voorstel; geen volledige integratiemapvergelijking gedaan. | Bronbinding slaagt. |
| Package-/dashboardregistratie | Actief: `stalman_energie` → `packages/energie_thuisbatterij.yaml`; YAML-dashboards `energie-thuisbatterij-yaml` en `ring-cameras` met hun bestaande bestanden. Beide dashboardbestanden zijn leesbaar. | Registraties gecontroleerd; beide dashboards behouden. |
| Financiële configuratie | Actief energiepackage bevat `input_boolean`, `input_number`, `template` en `utility_meter`, geen `command_line`. Map `config/energy_finance` ontbreekt; alleen het energiepackage is aanwezig, geen audit-/collectorpackage. | Nieuwe keten niet geïnstalleerd; geen bestaande collector-DB op het geplande pad aangetroffen. |
| Bestandsconflicten | Actief energiepackage SHA256 `ff1fe23c913df617eeee46abf8cce5380f3c4a95c40abca123b5a4dd6ec35155`, lokale kandidaat `530e71b7c946ee9a81902c5572deed23a8e373910a763f9d16c03dad9d96ccef`. Actief energiedashboard SHA256 `e539267c12f8943c2bc74310f82aa316af2e77f7adf1fce3eac798652a9c25e7`, lokale kandidaat `037c6f85badbf0aec40a19008a53eb2d259b827ac5ab8ee1a6b10e46d6b10327`. | Doelbestanden bestaan en verschillen: gerichte diff/merge en back-up verplicht, niet blind overschrijven. |
| Afhankelijkheden / ruimte | Op de host: Python 3.12.3; PyYAML, sqlite3 en zoneinfo aanwezig; circa 19,3 GB beschikbaar. De actieve containeromgeving kon niet worden geïnspecteerd. | Hostvereisten aanwezig; containervereisten alleen lokaal bewezen, productiecontrole open. |
| Schrijfrechten configuratie | Config-root, hoofdconfiguratie, packages en dashboards zijn voor deze gebruiker volgens `os.access` schrijfbaar. Dit is alleen een toegangscontrole, geen daadwerkelijke schrijfproef. | Deels uitvoerbaar, maar geen toestemming tot schrijven gegeven. |
| Schrijfrechten integratie / rollback | `custom_components`, `custom_components/battery_sim` en de initializer zijn root-owned en niet schrijfbaar voor `stallieman` (directories 0755, initializer 0644). | Installeren én terugzetten van de integratie zijn met huidige rechten niet uitvoerbaar. Niet omzeilen. |

### Bestaande back-ups

- `/home/stallieman/homeassistant-backup.tar.gz` bestaat en is als dezelfde SSH-gebruiker leesbaar en te openen: 24.138.864 bytes, wijzigingstijd **30 oktober 2026 23:03:27 CET**, mode **0644**. Het doorlopen van 2.802 archiefheaders slaagt; er is niets uitgepakt of uit geheime leden gelezen.
- Geselecteerde headercontrole: `config/configuration.yaml`, `config/custom_components/battery_sim/__init__.py` en `config/.storage/core.config_entries` zijn aanwezig. Het huidige `config/packages/energie_thuisbatterij.yaml` is in deze controle **niet** aangetroffen. De back-up is daarom niet bevestigd als complete actuele rollbackbaseline voor de geplande wijzigingen.
- Er is ook een leesbare map `/home/stallieman/.ring-dashboard-backup.yL1LDM` met een `configuration.yaml`; de inhoud is niet geopend. Dit is geen bewezen volledige HA-/simulatorback-up.
- Geen extractie-, integriteits-/herstelproef of consistentiecontrole van eventuele databases uitgevoerd. Leesbare archiefheaders bewijzen geen herstelbaarheid van de volledige back-up. De bestaande lokale herstelproef uit fase A vervangt dat productievereiste niet.
- Mode 0644 beperkt de archieftoegang niet tot alleen de eigenaar. Behandel de back-up als mogelijk gevoelig en laat een bevoegd beheerder bij een afzonderlijk toegestane back-upopdracht veilige opslag/toegang en een volledig actueel manifest vastleggen. Nu geen rechten of bestanden gewijzigd.

**Historisch preflightoordeel: NO-GO met de toen beschikbare SSH-rechten.** De geteste bronbinding en lokale keten waren in orde, maar Docker-/integratieschrijfrechten, actieve mount/image en een actuele volledige back-up waren nog niet bevestigd. De eigenaar heeft daarna de omgeving en een nieuwe gecontroleerde back-up bevestigd; zie §8. Rechten worden niet verondersteld of automatisch aangepast. Financiële activatie blijft geblokkeerd door §3.

## 8. Installatie- en rollbackscripts — uitsluitend lokaal ontwikkeld

### Nieuwe bevestiging door de eigenaar

De eigenaar bevestigt HA 2026.10.4 op Ubuntu ARM64, container `homeassistant`, image-ID `sha256:23f4dfbb69ce76315dbc4de7915504f1c2dcecd7ca2648113a493a385972e133`, bindmount `/home/stallieman/SmartHome_Stalman/config` en 18 GB vrij. Nieuwe back-up: `/home/stallieman/homeassistant-backup-20261031.tar.gz`, afzonderlijk uitgepakt en oorspronkelijke simulatorbestanden bytegelijk bevonden. Dit vervangt de oude onvolledige back-up als opgegeven uitgangspunt, niet als overslaan van scriptcontroles. Tijdens de scriptontwikkeling zijn geen productiechecks uitgevoerd, ook geen dry-run via SSH.

### Bestanden en standaardgedrag

- [install_battery_audit.sh](../scripts/install_battery_audit.sh): audit-only-installatie.
- [rollback_battery_audit.sh](../scripts/rollback_battery_audit.sh): expliciet gekozen herstelpunt terugzetten.
- Beide gebruiken [battery_audit_deployment.py](../scripts/battery_audit_deployment.py) en de bestaande repositorybestanden. De wrappers zijn dus geen losse, zelfstandige distributiebestanden. Hostafhankelijkheden: Python 3.9+ met PyYAML, tarfile, sqlite3/zoneinfo voor de HA-runtime en Docker-toegang; er worden geen pakketten geïnstalleerd. Het ondersteunde doel blijft de bevestigde Ubuntu/Python 3.12-omgeving.
- Standaard **dry-run**: uitsluitend lokale leescontroles; geen Docker-aanroep, containerproces, bestand/lock/herstelpunt of permissiewijziging. Runtimecontroles zijn een aparte actie en vereisen expliciete toestemming. `--apply` vereist daarnaast `--authorize-runtime-check` vóór runtimecontroles of wijzigingen. Er is geen SSH-aanroep, sudo, geforceerde installatie of image pull.
- Bij ontbrekende rechten, afwijkingen, symlinks/speciale bestanden, bestaande nieuwe doelpaden, bron-/backuphashverschil, gewijzigd batterijprofiel of onvoldoende ruimte stoppen de scripts. Dry-run beoordeelt rechtenmetadata; alleen bij expliciete apply wordt schrijfbaarheid met een tijdelijke echte schrijfactie gecontroleerd. Er is geen chmod/chown-reparatie van actieve doelbestanden om toegang te verkrijgen.

### Gecontroleerde installatievolgorde

1. Na afzonderlijke toestemming voor runtime-inspectie: voer `python3 -B scripts/battery_audit_deployment.py runtime-check --authorize-runtime-check` uit. Dit inspecteert container/image/mount en gebruikt alleen bij een draaiende container `docker exec` om versie en runtime-identiteit te controleren; er worden geen credentials getoond. De standaard dry-run voert deze checks niet uit. Controleer daarnaast de vier originele bronhashes en de bestaande batterijbinding, bronnen, efficiënties, frequentie en 5,12-kWh/2,5-/0,8-kW-configuratie. Afwijkende opties of solar-cap zijn niet toegestaan.
2. Controleer leesbaarheid en veilige archiefpaden van de opgegeven back-up, vereiste configuratieleden en byte-identiteit van de vier oorspronkelijke simulatorbestanden. Er wordt niets willekeurig uitgepakt. Controleer zowel configuratie- als herstelopslag: minimaal 1 GiB en bovendien voldoende voor drie maal de configuratiegrootte plus 256 MiB reserve. De scriptcheck kan dus strenger zijn dan alleen de bevestigde 18 GB.
3. Alleen onder `--apply`: neem een exclusieve deploymentlock en maak een privéherstelmap onder `~/.local/state/stalman-audit` (0700, eigendom uitvoerder). Kopieer de configuratie naar afgeschermde staging en breng uitsluitend de kandidaatwijzigingen daar aan. De kopie kan secrets bevatten en mag nooit in Git, chat of publieke artifactopslag terechtkomen.
4. Valideer staging met dezelfde image-ID via `docker run --pull=never --network none --read-only`, met alleen staging als `/config` en tijdelijke `/tmp`/`/run`. Commandouitvoer wordt niet getoond, ook niet bij fouten. Een validatiefout raakt de actieve configuratie niet en herstart niets. Configuratiecontrole bewijst geen hardware-/config-entrygezondheid; de eerdere HA-proef blijft aanvullend bewijs.
5. Stop uitsluitend de bestaande container gecontroleerd. Er is geen afgedwongen kill: Docker krijgt een onbeperkte gracetermijn; bij een timeout probeert de foutafhandeling de oorspronkelijke containerstatus te herstellen. Na bevestigde stop en hercontrole van bestanden/batterijconfiguratie: maak een nieuwe consistente volledige configuratieback-up, originele beheerde bestanden en een hash-/ownershipmanifest. Dit veronderstelt dat geen andere hostprocessen dezelfde HA-runtimebestanden schrijven.
6. Installeer alleen de geïnstrumenteerde initializer, helper, vijf financiële kern-/policybestanden en twee collectorpackages. Voeg twee includes chirurgisch aan de bestaande package-mapping toe. Voeg in het bestaande energiepackage alleen de financiële command_line-sensor en de bekende geldtemplates toe/vervang deze op `unique_id`; andere sensoren, helpers en instellingen blijven behouden. Alle dashboardbestanden, dashboardregistraties en overige integraties blijven onaangeroerd. De auditpolicy staat voor audit-only-ontvangst aan, maar alle contract- en vaste-kostenbevestigingen blijven **false**. Geen eurovrijgave.
7. Start dezelfde container zonder nieuwe image. Wacht op HTTP-bereikbaarheid en aantoonbaar geldige, gekoppelde auditbatches in de nieuwe SQLite-keten. Controleer de ongewijzigde batterijbinding/configuratie en ondersteunende bronbestanden opnieuw. Beperkte standaardwachttijd: 180 seconden, aanpasbaar tussen 30 en 600. Geen bedragen of sensor-/API-tokens nodig voor de healthcheck. Live modelpariteit wordt niet opnieuw met een tweede productie-simulator gemeten; daarvoor geldt het bestaande lokale bewijs. Bij ontbrekend auditbewijs probeert de foutafhandeling de beheerde bestanden en de oorspronkelijke containerstatus te herstellen; onvolledige recovery vereist handmatige beoordeling.

De scripts wijzigen geen dashboards; eventuele latere presentatie van nieuwe venstersensoren vraagt een afzonderlijk beoordeelde dashboardwijziging. De synthetische Docker-interacties in de nieuwe scripttests zijn mocks; de echte HA-transport-/herstartproef uit `dd502c5` is bestaand, afzonderlijk bewijs en geen integrale productieproef van deze nieuwe deployer.

### Herstelpunt en expliciete rollback

Het installatiescript toont alleen het pad naar het privéherstelpunt. Bewaar dit pad: rollback vereist `--restore-point` en kiest nooit automatisch de nieuwste back-up. De map bevat `configuration.tar.gz`, `originals/` en `manifest.json`; het manifest wordt vóór de eerste actieve bestandsvervanging geschreven. Bij een opgevangen fout probeert het script beheerde bestanden terug te zetten en de oorspronkelijke containerstatus te herstellen. Als automatische recovery zelf faalt, stopt het met een expliciete melding om herstelpunt, bestanden en container handmatig te beoordelen. Een geforceerde procesbeëindiging of host-/Docker-uitval kan niet door Python-foutafhandeling worden opgevangen.

Rollback controleert image/mount, batterijbinding, ruimte, rechten, snapshots en originele hashes. Bestandsdrift buiten de bekende voor-/nahashes blokkeert herstel, evenals een fout in de herstelde stagingconfiguratie. Een gedeeltelijke installatie met een reeds gestopte container kan vanuit een voorbereid manifest worden teruggedraaid. Herstel onder dezelfde lock; hercontroleer de bestanden opnieuw vlak vóór wijziging. Zet alleen de beheerde originele bestanden en hun ownership/mode terug en verwijder alleen de tijdens installatie nieuw toegevoegde code/configuratiebestanden. Herstel bewaart de containerstatus van vóór rollback; een opgevangen fout probeert de voorafgaande bestanden en status terug te zetten.

**Rollback overschrijft niet automatisch `.storage`, Recorder of de nieuwe intervaldatabase/waarnemingen.** Die blijven bewaard als runtime-/foutbewijs; generatiegrenzen worden niet aan elkaar geplakt. Een volledig snapshotherstel van state/databases is een aparte beheerhandeling. De achterblijvende financiële runtime-map voorkomt bewust een blinde herinstallatie. Automatische recovery is geen automatische herpoging of vrijgave; als recovery onvolledig is, is handmatige beoordeling vereist. De scripts hebben nog geen productie-autorisatie.

### Voorbeelden — nu niet uitvoeren op productie

Alleen ter voorbereiding, door een bevoegde uitvoerder na nieuwe toestemming en vanuit de repository op de bevestigde host:

```bash
# Alleen lezen; ook hiervoor geldt nu: niet op productie uitvoeren.
bash scripts/install_battery_audit.sh
bash scripts/rollback_battery_audit.sh --restore-point /absoluut/pad/naar/herstelpunt

# Runtimecontrole alleen na aparte expliciete toestemming.
python3 -B scripts/battery_audit_deployment.py runtime-check --authorize-runtime-check

# Alleen na expliciete toestemming voor wijzigingen, runtimechecks en gecontroleerde stop/start.
bash scripts/install_battery_audit.sh --apply --authorize-runtime-check
bash scripts/rollback_battery_audit.sh --restore-point /absoluut/pad/naar/herstelpunt --apply --authorize-runtime-check
```

Andere paden mogen alleen expliciet met `--config`, `--backup` en `--restore-root` worden opgegeven; de echte bindmount en overige veiligheidschecks blijven gelden. Pas geen image-ID/bronhash aan om een afwijking te omzeilen.

### Lokale validatie en vrijgave

22 gerichte synthetische tests in [test_battery_deployment.py](../tests/test_battery_deployment.py) controleren dry-run zonder Docker-aanroepen of schrijfacties, expliciete runtimeautorisatie, apply/rollback, behoud van niet-beheerde instellingen, foutafhandeling en herstel na install-/rollbackschrijffout, validatie- en healthcheckfouten, drift, corrupte back-ups/herstelpunten en rechten-/ruimte-/image-/mount-/batterijafwijkingen. Docker wordt volledig gemockt: geen daemon of server is benaderd. Bash-syntax en beide help-entrypoints zijn gecontroleerd. Tests zijn uitgevoerd met PyYAML in een lokale virtuele omgeving.

**Stop vóór iedere productiehandeling.** Actuele bevoegdheden zijn niet opnieuw vastgesteld; de eerdere beperkte SSH-gebruiker kon de HACS-map niet wijzigen. De scripts mogen dit niet omzeilen. Beoordeel deze lokale resultaten en regel afzonderlijk installatie-/stop-/start-/rollbacktoestemming voor een al bevoegde beheerder. Contract- en volledige-meetdekkingsblokkades blijven onveranderd.
