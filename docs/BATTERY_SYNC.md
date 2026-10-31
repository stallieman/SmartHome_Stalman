# Battery Simulator: exacte bronkoppeling en financiële meetvensters

## Uitkomst en gereedheid

De ongewijzigde simulator kan geen aantoonbaar gesynchroniseerde financiële vergelijking leveren. Een lokale, versiegebonden **audituitbreiding als voorstel** is uitgewerkt, met een strikte ontvanger en rekenpad voor expliciete meetvensters. De uitbreiding wijzigt geen rekenmethode, capaciteit, efficiëntie, planning of bediening van de simulator.

**Niet klaar voor rechtstreekse productie-installatie.** De geïsoleerde Home Assistant-runtime- en modelpariteitsproef slaagt, maar alle audittoestemming staat standaard uit. Contractgegevens blijven onvolledig en de simulator publiceert geen verwerkte P1-meetvensters. De P1 normaal/dal-mapping is inmiddels bevestigd: code 2 = normaal en code 1 = dal, op basis van de Home Assistant-overgang 2 → 1 op 30 oktober 2026 om 22:59:50. Er zijn geen eurobedragen voor de actieve installatie vrijgegeven.

Geen wijzigingen op Ubuntu, geen geïnstalleerde HACS-bestanden aangepast, geen productieherstart en geen push. De runtimeproef draaide lokaal in een geïsoleerde HA 2026.10.4-container met netwerk uitgeschakeld, uitsluitend met synthetische waarden en de vastgepinde upstream-bron.

## 1. Onderzochte versie en bronnen

[Upstream-release v2.9.0](https://github.com/hif2k1/battery_sim/releases/tag/v2.9.0) verwijst naar commit `4cb396ff635f235787b42a51734ffef4168c330e` (releasepublicatie 2 oktober 2026).

De geïnstalleerde bronbestanden zijn bytegelijk aan die tag:

| Bestand | SHA256 |
|---|---|
| `__init__.py` | `a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6` |
| `sensor.py` | `c6a137075d962c43fc88246ba078b81ce98269dbe2f7ae0379ba0cddad129724` |

Het manifest vermeldt `2.7.0`, maar dat doet het manifest in de upstream v2.9.0-tag óók. Dit is dus geen bewijs van een oudere geïnstalleerde kern. De huidige master heeft een andere bronhash; het patchvoorstel weigert die zonder nieuwe beoordeling.

Primaire codeverwijzingen, vastgepind:

- [Bronlisteners en periodieke timer](https://github.com/hif2k1/battery_sim/blob/4cb396ff635f235787b42a51734ffef4168c330e/custom_components/battery_sim/__init__.py#L825)
- [Acceptatie en accumulatie van bronwijzigingen](https://github.com/hif2k1/battery_sim/blob/4cb396ff635f235787b42a51734ffef4168c330e/custom_components/battery_sim/__init__.py#L864)
- [Verwerking en legen van accumulators](https://github.com/hif2k1/battery_sim/blob/4cb396ff635f235787b42a51734ffef4168c330e/custom_components/battery_sim/__init__.py#L1045)
- [Berekening en publicatie van simulatiecounters](https://github.com/hif2k1/battery_sim/blob/4cb396ff635f235787b42a51734ffef4168c330e/custom_components/battery_sim/__init__.py#L1107)
- [Openbare sensorattributen](https://github.com/hif2k1/battery_sim/blob/4cb396ff635f235787b42a51734ffef4168c330e/custom_components/battery_sim/sensor.py#L349)

Read-only metadata bevestigde de bronkoppeling: `sensor.p1_meter_energie_import` en `sensor.p1_meter_energie_export`. Het bestaande Marstek-config-entry-ID is vastgelegd in de lokaal uitgeschakelde auditpolicy; dit is een apparaatbinding, geen token. Controleer die binding opnieuw vóór een eventuele installatie.

## 2. Hoe de simulator werkt

P1-`state_changed`-events bevatten de oude en nieuwe bronwaarde. De handler controleert beschikbaarheid en eenheid (Wh/kWh), berekent het verschil en telt dat bij `_accumulated_import_reading` of `_accumulated_export_reading`. Een gelijke tellerwaarde wordt overgeslagen. Bij een daling wordt de gesimuleerde teller opnieuw op de bron gebaseerd. Onbekende/ontbrekende oude of nieuwe states worden genegeerd: dat is geen garantie op complete meetdekking.

De standaardtimer verwerkt ongeveer iedere 60 seconden. Daarnaast kunnen switch-, number- en select-bedieningen `async_trigger_update()` aanroepen. Een minimale tussentijd van vijf seconden kan verwerking uitstellen. Al deze paden lopen in de onderzochte versie via `_async_maybe_update_battery()`, die `update_battery()` precies eenmaal aanroept en daarna de accumulators leegt.

Intern bestaan de totale geaccumuleerde energie, `event.old_state/new_state`, de tijd van de vorige berekening en de ruwe simulatiecounters. `_last_import_reading_sensor_data`/`_last_export_reading_sensor_data` bewaren inputconfiguratie, geen publiek register met verwerkte absolute begin-/eindstanden. De associatie tussen individuele bronwijzigingen en een voltooide berekening wordt niet openbaar bewaard.

`dispatcher_send` signaleert dat batterijsensoren moeten verversen, maar bevat geen geconsumeerde bronstanden of batch-ID. De losse sensoren publiceren afgeronde waarden en afzonderlijke tijdstempels. `sources`, `last_reset` en het afgeronde besparingspercentage bevatten evenmin het benodigde bewijs.

## 3. Waarom andere oplossingen onvoldoende zijn

1. **Bestaande attributen:** geen exacte verwerkingsgrens beschikbaar.
2. **Alleen HA-events observeren:** vertelt welke bronwaarden veranderden, maar niet of een wijziging werd geaccepteerd, genegeerd, vertraagd of in welke berekening zij is verbruikt.
3. **Adapter zonder bronhook:** kan geen ontbrekende interne informatie reconstrueren. Private functies tijdens runtime vervangen zou dezelfde instrumentatie vereisen, maar is minder expliciet te beoordelen dan een kleine vastgepinde bronpatch.
4. **Minimale auditpatch:** voegt uitsluitend observatiehooks toe op registratie, bronacceptatie, verwerking en resets. Dit is het gekozen lokale voorstel. Geen fork met een ander batterijmodel.

Er wordt nooit op 2 seconden verschil, een 60-secondenpatroon of toevallig gelijke delta's gesynchroniseerd.

## 4. Lokale implementatie

### Voorstel voor de producent

`proposals/battery_sim_audit/prepare_patch.py` maakt uitsluitend een **nieuwe afzonderlijke kopie** van de byte-exacte initializer. Het weigert onbekende hashes, een bestaand uitvoerbestand en overschrijven van de bron. Alle oorspronkelijke method bodies worden via AST-vergelijking op ongewijzigdheid gecontroleerd.

`upstream-v2.9.0.patch` toont de kleine import-/decoratorwijziging. De bijbehorende `stalman_audit.py` is een zelfstandig auditmodulevoorstel, niet geïnstalleerde integratiecode. De MIT-licentie van de upstream-context is meegeleverd.

Hooks registreren de daadwerkelijk door de originele handler geaccepteerde old/new-counterketens. Zij controleren dat deze som exact aansluit op de geconsumeerde accumulators (met uitsluitend een expliciete `1e-8 kWh`-tolerantie voor bestaande float-rekenruis in de acceptatiecontrole). De oorspronkelijke berekening wordt eenmaal met dezelfde argumenten uitgevoerd. Daarna bevat één atomair event:

- producent, upstream-bronhash en audithelper-hash;
- batterij/config-entry, generatie en batchvolgnummer;
- exacte geaccepteerde broncounterbegin/eindstanden en de bron-events;
- ruwe gesimuleerde begin-/eindcounters uit dezelfde voltooide berekening;
- expliciete verwerkingstijden en broncountertijdstempels;
- P1-tariefregisters op de geattesteerde countergrenzen;
- tariefcode, reset-/continuïteitsgeldigheid en foutreden.

Dit minimale voorstel ondersteunt één P1-import/exportpaar zonder aanvullende solar-cap-bron. Een extra Growatt-cap of meerdere meters vereist ook acceptatie-audit van die extra bron; het voorstel blokkeert certificering zolang dat niet is uitgewerkt.

Gebruik van ruwe interne simulatiecounters voorkomt extra afronding door afzonderlijke HA-sensorstates. Auditfouten veranderen het model niet en mogen alleen bewijs blokkeren. Originele uitzonderingen blijven originele uitzonderingen. Een uitgestelde berekening zonder uitvoering publiceert geen batch.

### Normaal/dal wordt met counters gecontroleerd

De actieve tariefcode alléén is onvoldoende: HA kan totaal- en tariefsensoren achter elkaar bijwerken. De ontvanger eist daarom dat de som van P1-registers 1/2 **exact** de geconsumeerde absolute totaalstand identificeert, zowel vóór als na verwerking. De bestaande tolerantie voor diagnostische P1-waarnemingen wordt niet gebruikt om financiële countergrenzen te laten passen.

Een batch met import in beide tariefregisters wordt afgewezen: het model berekent één geaggregeerd resultaat en geeft niet aan hoeveel daarvan bij elk tarief hoort. De geattesteerde tariefcode moet daarnaast overeenkomen met het ene gebruikte register. Extra gesimuleerde netlading boven de werkelijke import wordt ook afgewezen: die extra kWh hebben geen werkelijke P1-registerverdeling. Er wordt niets pro rata verdeeld.

Dit ondersteunt betrouwbare vensters met één normaal- of daltarief. Vensters rond onzekere overgangen worden uitgesloten, niet stilzwijgend opgeteld bij een volledig dagtotaal.

### Ontvanger, opslag en rekenkern

`config/packages/energie_audit_adapter.yaml` bereidt een queued HA-eventadapter voor. URL-gecodeerde JSON wordt als één shell-argument aan de collector doorgegeven. Dit package is niet geregistreerd of actief.

`Collector.ingest_audit()` bewaart events in aparte SQLite-tabellen, naast de behouden v1/v2-journalen. Identieke batch-ID's zijn idempotent; conflicterende duplicaten blokkeren die generatie. Vertraagde of anders geordende bezorging kan herstellen wanneer de volledige aaneengesloten keten alsnog aankomt. Gaten, gewijzigde configuratie, resets en gebroken before/after-counters blokkeren certificering.

`batch_contract.py` is de strikte bewijsontvanger. Pas met een expliciet goedgekeurde producent, batterijbinding, helper-hash en tariefmapping kan hij `coverage_confirmed` vrijgeven. De standaardpolicy is `enabled: false`. Ruwe sensormomentopnamen kunnen dit kanaal niet gebruiken. Dit is een contract met een vertrouwde lokale integratie, geen cryptografische bescherming tegen een beheerder die zelf events of configuratie vervalst.

De rekenkern heeft een afzonderlijke scope **`window`** gekregen. Deze gebruikt de bestaande Essent-berekeningen, met exacte tellerdelta's en expliciete `measured_from/observed_until`. Een venster wordt niet als complete dag of jaarnota gepresenteerd. Drie aparte sensoren tonen kosten zonder batterij, met virtuele batterij en het verschil. In het financiële tabblad staat het begin/einde zichtbaar bij deze kaarten. Overzicht en het batterijtabblad zijn ongewijzigd.

### Herstarts en grensgevallen

Na een HA-start is er een nieuwe auditgeneratie en een nieuwe expliciete anchor. Pending energie van vóór die anchor wordt niet als nieuw gemeten verbruik aangemerkt. Tijdens normale verwerking blijven opeenvolgende batches één keten. Na een reset, ongeldige bron of een tarief-/daggrens kan de audit alleen opnieuw ankeren wanneer de oorspronkelijke berekening haar inputs heeft geleegd en bron-/registerstanden opnieuw coherent zijn. Dit verandert geen simulatorcounters, instellingen of berekeningen.

De onzekere overgangsbatch blijft ongeldig. Een later geldig venster begint expliciet opnieuw; de ontbrekende prefix wordt nooit nul en wordt niet geëxtrapoleerd. Ontbreekt een bezorgd event midden in een generatie, dan komt geen bedrag voor die onvolledige keten vrij. Een procesherstart van de ontvanger gebruikt dezelfde SQLite-batch-ID's en telt niets dubbel.

## 5. Financiële grenzen

De effectieve importprijs blijft `(levering_ex_btw × (1 − korting) + belasting_ex_btw) × (1 + btw)`. De 10% korting wordt niet op het gehele opgegeven tarief toegepast. De aangeleverde prijzen blijven onbevestigd totdat btw, componenten en perioden zijn gereconcilieerd.

Vanaf 2027 vergelijkt de kern per tarief de werkelijke en gesimuleerde importkosten, plus exportkosten minus exportvergoeding. Batterijverliezen zitten al in het modelresultaat; er wordt geen extra efficiëntiefactor afgetrokken.

**Tot en met 2026 wordt ook een gecertificeerd kort meetvenster niet als dagelijkse financiële besparing gewaardeerd.** Jaarlijkse saldering, contractuele tariefverrekening en terugleverkostenstaffels vereisen een volledige afrekenperiode. Die historische meetreeks kan deze installatie niet achteraf maken. De jaarrekening 2024–2025 blijft alleen referentie.

Er worden geen aanschafkosten, tarieven, rendementen of historische meetgegevens verzonnen. De vensterkosten zijn variabele kostenramingen, geen gemeten factuur, volledige dagkosten of terugverdientijd. Een afwijkende begin-/eind-SoC betekent bovendien een kasstroom over dat venster, geen stationaire jaaropbrengst.

## 6. Langere perioden zonder aanpassing

Het relatieve effect van een minuut achterstand kan bij lange totalen klein lijken. Dat is geen bewijs van een gedeelde bronperiode. Onder de aanvullende voorwaarden van een **gegarandeerde** maximale lag `L` en een bekende vermogensgrens `P` zou een conservatieve endpointfout kunnen worden begrensd met `P × (L_start + L_end) / 3600` kWh per richting. Prijs- en salderingseffecten moeten dan afzonderlijk worden begrensd.

De waargenomen minuutcadans is geen gegarandeerde laggrens tijdens uitval/herstart. Niet-gepubliceerde exporttimestamps kunnen uren oud zijn; geaccepteerde brondata kunnen tijdens onbeschikbaarheid worden overgeslagen. Er is daarom voor de ongewijzigde integratie geen onderbouwde numerieke nauwkeurigheid of harde foutmarge beschikbaar. Deze benadering is niet als euroberekening geïmplementeerd.

Met de audituitbreiding zijn langere **aaneengesloten geattesteerde vensters** mogelijk. Een prijs-/daggrens met een gemengde simulatiebatch blijft een grens aan exacte allocatie. Voor complete dagen of jaarrekeningen is daarnaast een upstream-protocol nodig dat de verwerking bij bevestigde bron-/tariefgrenzen kan afwikkelen, of per-tarief simulatie-output publiceert. Dat kan de modeltiming beïnvloeden en is daarom niet in dit minimale voorstel opgenomen.

## 7. Validatie

- 87 unittests: bestaande financiële tests, bronbewuste collector, audit-hooks en bewijsontvanger.
- Verschillende broncadans, vertraagde verwerking, anders geordende en dubbele events.
- Normaal/dal met exacte registerbinding; gemengde batches en extra netlading worden geblokkeerd.
- Onbeschikbare bron, gemist bron-event, teller-/metadatareset en nieuwe generaties.
- HA-/ontvangerherstart, nieuwe dag, tijdelijke discontinuïteit en expliciet nieuw venster.
- Verliezen via gesimuleerde netcounters, kosten met/zonder batterij en blokkering onder jaarlijkse saldering.
- YAML, template- en veilige argumentcoderingcontroles slagen.
- Het gepinde echte upstreambestand is lokaal getransformeerd: alle oorspronkelijke method bodies zijn AST-gelijk en de voorgestelde initializer compileert.
- Twee aanvullende runtime-tests gebruiken de echte Home Assistant Core 2026.10.4-state machine en eventbus, plus de originele en geïnstrumenteerde `SimulatedBatteryHandle` uit dezelfde upstream-bron.
- De runtime-tests voeren identieke echte `async_reading_handler`- en `update_battery`-paden uit. Alle batterijstatussen en simulatiecounters zijn gelijk; de auditbatch wordt daarna door de echte collector-contract- en financiële functies verwerkt.
- Getest: uitgestelde verwerking onder de minimuminterval, tarief 1/2, tariefwissel met expliciete herankering, ontbrekende brondata en blokkering van ongeldige bedragen.

De runtimeproef is geïsoleerd en zonder netwerk:

```sh
docker run --rm --network none \
  -v "$PWD:/workspace:ro" \
  -v /pad/naar/battery_sim/custom_components/battery_sim:/upstream:ro \
  --entrypoint python3 \
  ghcr.io/home-assistant/home-assistant:2026.10.4 \
  /workspace/scripts/validate_battery_runtime_parity.py \
  --source /upstream/__init__.py
```

De test weigert afwijkende hashes voor `__init__.py`, `const.py` of `helpers.py`. De bestaande hooktests blijven referentiecallbacktests. De runtimeproef start niet de volledige Home Assistant-applicatie of een config-entry/platformsensoropstelling en controleert geen fysieke meters, HACS-updates of hardwaregedrag.

Reproduceren:

```sh
python3 -m unittest discover -s tests -v
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_energy_dashboard.py
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_interval_collector.py
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_battery_audit_proposal.py
```

Voor de aanvullende echte broncontrole, geef een lokale kopie van het vastgepinde upstreambestand mee met `--source /pad/naar/originele/__init__.py`. De validator weigert iedere andere hash en schrijft geen bronbestand.

## 8. Wat nog nodig is vóór productie

De runtimepariteit is alleen lokaal aangetoond voor de vastgepinde bronversie en synthetische inputs. Bevestig vóór installatie de contractgegevens en tariefmapping, controleer hardware-beschikbaarheid/heartbeatgedrag, bepaal HACS-updatebeheer en controleer backups en actieve bronhashes opnieuw. De voorgestelde private hooks hebben een onderhoudslast bij HACS-updates. Ze mogen niet automatisch op een andere versie worden toegepast. Installatie vereist een afzonderlijke beoordeling en toestemming.
