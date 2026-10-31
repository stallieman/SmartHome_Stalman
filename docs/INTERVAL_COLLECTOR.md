# P1 / virtuele batterij — intervalverzamelaar

Uitsluitend lokaal ontwikkeld. Geen verbinding met Ubuntu gemaakt, geen serverwijziging, herstart of push. De financiële rekenkern uit `29e6ca8` blijft verantwoordelijk voor tarieven en saldering.

## Bestanden en gegevensstroom

- `config/energy_finance/collector.py`: standaardbibliotheek-Python, transactionele SQLite-opslag en atomaire financiële export.
- `config/energy_finance/collector.json`: entiteiten, bevestigde tariefmapping, kwaliteitsgrenzen.
- `config/packages/energie_intervalcollector.yaml`: afzonderlijk, nog niet geregistreerd HA-package met sessiehelper, automation en shell_command. Geen tokens of netwerktoegang nodig.
- `tests/test_interval_collector.py` en `scripts/validate_interval_collector.py`: lokale controles met synthetische waarnemingen.

Na een latere goedgekeurde installatie: een automation neemt iedere minuut, bij tariefwissels en na HA-start een snapshot van alle betrokken state-objecten. Eén snapshot bevat tellerstanden, eenheden, `last_reported`, tarief-`last_changed`, resetmetadata en een HA-sessie-ID. De shell-opdracht geeft uitsluitend URL-gecodeerde JSON als één argument door. Er komen geen ruwe sensorstrings in shellcode.

De collector schrijft `intervals.sqlite` (inclusief WAL/SHM en lockfile) onder `energy_finance`. Alle snapshots blijven bewaard, inclusief ongeldige samples en redenen. Geldige intervallen bevatten begin/eind, tarief, alle tellerdelta's en afzonderlijk **gemeten** en **gesimuleerde** import/export. `observations.json` is een vervangbaar exportbestand voor `compare.py`, geen primaire opslag. Runtimebestanden zijn uitgesloten van Git.

## Bronnen

| Rol | Entity-ID |
|---|---|
| Werkelijke import/export totaal | `sensor.p1_meter_energie_import`, `sensor.p1_meter_energie_export` |
| Werkelijke import per tariefcode | `sensor.p1_meter_energie_import_tarief_1`, `sensor.p1_meter_energie_import_tarief_2` |
| Werkelijke export per tariefcode | `sensor.p1_meter_energie_export_tarief_1`, `sensor.p1_meter_energie_export_tarief_2` |
| Actieve tariefcode | `sensor.p1_meter_tarief` |
| Gesimuleerde import | `sensor.marstek_venus_e_5_12kwh_3nd_gen_simulated_sensor_p1_meter_energie_import` |
| Gesimuleerde export | `sensor.marstek_venus_e_5_12kwh_3nd_gen_simulated_sensor_p1_meter_energie_export` |

Alle energietellers moeten kWh leveren. Werkelijke import komt rechtstreeks uit de P1-tariefregisterdelta's; totalen zijn een onafhankelijke somcontrole. Gesimuleerde import wordt uitsluitend aan een tarief toegewezen als dat tarief aantoonbaar stabiel was gedurende het volledige interval en de inactieve P1-telwerken niet veranderden. Growatt, opgeslagen energie, efficiëntie en `total_energy_saved` worden niet nogmaals als financiële energie opgeteld.

## Geen dubbeltelling of fictieve nulwaarden

- Iedere snapshot heeft één unieke UTC-tijdstempel. Een identieke herhaling is idempotent; de tellerbaseline wordt niet opnieuw gebruikt voor extra energie.
- Een afwijkende snapshot met hetzelfde tijdstip is een duurzame kwaliteitsfout: de dag blijft geblokkeerd, ook na latere geldige samples.
- SQLite `BEGIN IMMEDIATE` bewaart snapshot en interval in één transactie. Een procesherstart leest dezelfde laatste baseline terug. De CLI gebruikt daarnaast een bestandsslot over ingestie, export en bestandvervanging, zodat een oudere exporter geen nieuwer rapport kan overschrijven.
- Een nieuwe HA-sessie verbreekt het interval, ook als tellerstanden zijn hersteld. De helper begint na HA-start leeg; de startup-actie maakt een nieuw sessie-ID. Er wordt geen verbruik tijdens de herstart verzonnen.
- `unknown`, `unavailable`, ontbrekende entiteiten, verkeerde eenheden, herstelde states, oude/toekomstige bronrapporten en niet-eindige getallen leveren nooit nulmetingen op.
- Alle bronnen moeten sinds het vorige snapshot opnieuw hebben gerapporteerd. Een onveranderd tellergetal met een **nieuw** bronrapport mag een echte nuldelta zijn. Een oude state die alleen opnieuw wordt uitgelezen is geen bevestigde nul.
- Dalende tellers, gewijzigde resetmetadata, onmogelijke sprongen, inconsistente P1-totalen en te grote tijdgaten blokkeren het interval. Een geldige teller na een fout is alleen een nieuwe baseline; de ontbrekende energie wordt niet overbrugd.
- Tariefwissels (ook wissel-en-terug via `last_changed`) worden niet achteraf evenredig verdeeld. De huidige simulatorsensor heeft geen eigen tariefregister of betrouwbare tariefwissel-watermark; het overgangsinterval wordt afgewezen.

## Instellingen die eerst bevestigd moeten worden

De productieconfiguratie is bewust geblokkeerd:

1. Vul in `tariff_mapping` in welke P1-code `normal` en welke `offpeak` betekent. Bevestig dit aan de hand van contract en meter; zet daarna pas `mapping_confirmed` aan. Er is geen aangenomen 1/2-verdeling.
2. Vul voor alle vier richtingen `max_power_kw` in op basis van de aansluiting en de toepasselijke simulatorgrenzen. De collector gebruikt die uitsluitend voor sprongdetectie; het zijn geen berekende verbruikswaarden.
3. Controleer de broncadans en timestampafstemming. De voorgestelde grenzen zijn 90 s maximale bronleeftijd, 10 s maximaal timestampverschil en 90 s tussen snapshots bij een minuutpoll. Dit zijn conservatieve kwaliteitsinstellingen, geen bewijs van synchronisatie. Versoepel ze niet om fouten te laten verdwijnen.
4. `pairing_confirmed` blijft uit totdat is aangetoond dat de simulator dezelfde P1-bronperiode heeft verwerkt als de fysieke tellers in de snapshot. **Een kleine `last_reported`-afstand bewijst dit niet.** Als de simulator achterloopt, is een verwerkings-watermark of een aanpassing van de snapshot-timing nodig; er worden geen kosten vrijgegeven op basis van alleen een tijdtolerantie.
5. Contracttarieven blijven afzonderlijk te bevestigen in `tariffs.json`. Een correcte collector maakt ontbrekende contractgegevens niet geldig.

## Dagdekking en grenzen

Tijden worden intern in UTC opgeslagen; daggrenzen zijn Europe/Amsterdam, inclusief zomer-/wintertijd. Er wordt niet geïnterpoleerd bij middernacht. Een interval over een niet-bemonsterde daggrens wordt afgewezen, omdat de energie vóór/na die grens niet bekend is.

De dag-export is standaard alleen geldig vanaf een echte middernachtbaseline, met een aaneengesloten keten tot de laatste waarneming. Een gat, reset, herstart, onzekere tariefgrens of configuratiewijziging in die keten blokkeert de hele dag. Een momentopname waarvan de tellerwaarden pas na middernacht gerapporteerd zijn is geen gegarandeerde middernachtmeterstand. Met de huidige asynchrone sensoren kan volledige dagdekking daarom onhaalbaar blijven zonder extra bron-watermarks/grensmetingen. Dit is een expliciete beperking, geen geschatte nul.

`allow_partial_first_day` is standaard uit. Voor expliciete lokale analyse kan deze **vóór de eerste meting** worden aangezet. Dan mag uitsluitend het eerste aaneengesloten installatievenster worden uitgevoerd met `coverage_kind: contiguous_partial_day` en de echte `measured_from`. Geen gaten later in de dag worden weggeknipt. De financiële kern controleert en bewaart dat label. Gebruik zo'n gedeeltelijk rapport pas in het dashboard wanneer de meetperiode zichtbaar wordt getoond; schakel dit niet in om volledige dagdekking te suggereren.

Voor de gewone export betekent `coverage_confirmed` dekking van het expliciet aangegeven meetvenster; bij een gedeeltelijke eerste dag is dat uitdrukkelijk niet sinds 00:00. De rekenkern weigert ongemarkeerde gedeeltelijke periodes. Tot 2027 blijven dagelijkse eurobedragen wegens jaarlijkse saldering geblokkeerd. De collector genereert geen jaarlijkse salderingsverdeling of staffelkosten; `scope: billing` vraagt nog de gegevens beschreven in FINANCE.md.

## Herstel en beheer

Een collector-procesherstart gebruikt de opgeslagen baseline en telt een identieke heraanbieding niet dubbel. Een onderbreking die groter is dan de toegestane intervalduur wordt wel als gat geregistreerd. Bij een ongeldige CLI-invoer wordt een eerdere succesvolle `observations.json` vervangen door een onbeschikbare uitvoer. Als de exportmap zelf niet schrijfbaar is, kan dat niet: de opdracht faalt en de bestaande financiële sensor blokkeert na maximaal 15 minuten oude invoer. Er worden geen data verwijderd of automatische reparaties uitgevoerd.

Wis de SQLite-database niet om een fout te verbergen. Bewaar bij een back-up ook de consistente database-inhoud: gebruik SQLite's backup-API of maak een back-up terwijl de collector stilstaat en neem de benodigde WAL-bestanden mee. De huidige implementatie heeft geen automatische retentie; de journaalbestanden groeien door. Bij later beheer kan gecontroleerde archivering worden toegevoegd.

Een wijziging van collectorinstellingen krijgt een andere configuratiehash en verbreekt de keten. Eerdere bedragen worden niet stilzwijgend onder nieuwe tariefmapping herberekend. Een beschadigde database wordt niet automatisch opnieuw aangemaakt.

## Lokaal testen

```sh
python3 -m unittest discover -s tests -v
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_energy_dashboard.py
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_interval_collector.py
```

De unittest-suite gebruikt uitsluitend tijdelijke SQLite-bestanden en synthetische tellerstanden. De aanvullende validator controleert YAML, native Jinja-snapshots, ontbrekende states en shell-argumentcodering. Dit is geen volledige HA-schema-/runtimecontrole.

Voor een gecontroleerde lokale replay van een echt of zelf gemaakt testsnapshot:

```sh
python3 config/energy_finance/collector.py \
  --config /tmp/confirmed-test-collector.json \
  --database /tmp/stalman-intervals.sqlite \
  --sample /tmp/snapshot.json \
  --output /tmp/stalman-observations.json
```

Gebruik voor lokale tests aparte instellingen en tijdelijke paden; schrijf geen testsnapshots in productie-runtimebestanden.

## Latere installatie — alleen na toestemming

Er is nu niets geïnstalleerd. Controleer voor installatie de back-up, actieve versies, rechten en helper-/automationnaamconflicten. De benodigde nieuwe bestanden zijn `collector.py`, `collector.json` en het afzonderlijke package. Ook de financiële rekenkern en het bestaande energiepackage bevatten ondersteuning voor meetvenstermetadata. Hoofdconfiguratie hoeft alleen een extra package-include te krijgen, zorgvuldig samengevoegd met bestaande packages:

```yaml
homeassistant:
  packages:
    stalman_intervallen: !include packages/energie_intervalcollector.yaml
```

Installeer of activeer die automation pas nadat de instellingen en koppeling zijn gecontroleerd. Voer eerst HA-configuratiecontrole uit; een eventuele herstart vereist afzonderlijke toestemming. Laat het oorspronkelijke UI-dashboard en integraties intact. De huidige opdracht bevat daarvoor geen toestemming.

## Officiële referenties

- [HA state-object en last_reported](https://www.home-assistant.io/docs/configuration/state_object/)
- [HA state-machine: onveranderde waarden kunnen opnieuw rapporteren](https://contributors.home-assistant.io/core/internals/states/)
- [Shell Command: templates, argumenten, response en timeout](https://www.home-assistant.io/integrations/shell_command/)
