# Essent en de virtuele Marstek — financiële vergelijking

Ontwikkeld op 31 oktober 2026, uitsluitend lokaal. Geen serverwijzigingen of herstart. Alle euro-uitkomsten zijn **schattingen op gemeten energie**; de Marstek-variant is **simulatie**, dus geen gerealiseerde besparing van een fysieke batterij. Er is geen gemeten factuurbedrag of terugverdientijd afgeleid.

## Huidig contract: ingevoerd en nog te bevestigen

Officiële bronnen:

- [Essent Thuisvoordeel](https://www.essent.nl/klanten/thuisvoordeel): korting op het leveringstarief inclusief btw, niet op energiebelasting/netbeheerkosten; geen korting bij dynamisch contract.
- [Actievoorwaarden Thuisvoordeel](https://www.essent.nl/-/media/essent/documenten/essent/particulier/pdf/algemeen/thuisvoordeel-voorwaarden.pdf): toepassing na saldering. De tekst was via de zoekindex beschikbaar; direct ophalen gaf HTTP 403.
- [Rijksoverheid — einde saldering](https://www.rijksoverheid.nl/themas/klimaat-milieu-en-natuur/energie-thuis/salderingsregeling): jaarlijks salderen tot en met 31 december 2026; vanaf 1 januari 2027 niet meer.
- [ACM ConsuWijzer](https://consument.acm.nl/elektriciteit-en-gas/duurzame-energie/wat-is-salderen): saldering inclusief belasting en btw; daarna belasting/btw over alle afname.
- [Essent terugleverkosten](https://www.essent.nl/klantenservice/contract/terugleverkosten): vóór 2027 staffels; tarieven vanaf 2027 verschillen per klant en staan in de contractbevestiging/brief. Rechtstreeks ophalen gaf 403; relevante passages waren via de zoekindex beschikbaar.
- [Rijksoverheid — opbouw energierekening](https://www.rijksoverheid.nl/documenten/vraag-en-antwoord/energie-thuis/opbouw-energierekening): 21% btw, ook over energiebelasting. Dit is geen bewijs van de btw-status of periode van de specifieke aangeleverde bedragen.

De door de gebruiker opgegeven bedragen staan nu afzonderlijk in `tariffs.json` als 2026- en 2027-plan. Het historische saldo is uitsluitend vastgelegd als referentie (26-03-2024 t/m 25-03-2025): 3.133 kWh import, 2.366 kWh export en 767 kWh netto import.

### 2026: jaarlijks salderen

De huidige contractregels tellen op:

| Component | Normaal | Dal |
|---|---:|---:|
| Variabele levering vóór korting | € 0,20189/kWh | € 0,19826/kWh |
| Energiebelasting | € 0,11085/kWh | € 0,11085/kWh |
| Opgegeven totaal | € 0,31274/kWh | € 0,30911/kWh |
| Thuisvoordeel-korting | 10% op levering | 10% op levering |
| Effectief opgegeven | **€ 0,292551/kWh** | **€ 0,289284/kWh** |

De uitkomst is exact `levering × 0,90 + energiebelasting`; de korting wordt niet op belasting toegepast. De calculator bewaart de componenten intern exclusief btw: de opgegeven componenten worden voor de reconstructie door 1,21 gedeeld, de korting wordt toegepast en daarna wordt 21% btw eenmaal toegevoegd. Dat reconcilieert met de opgegeven brutototalen en levert de opgegeven effectieve tarieven op. De huidige tariefregel in de config blijft desondanks geblokkeerd totdat de contractnota bevestigt dat de broncomponenten inclusief 21% btw zijn en de precieze geldigheidsperiode geeft. De opgegeven effectieve tarieven zijn daarmee een gevalideerd rekenresultaat onder die expliciete btw-basis, geen onafhankelijke verificatie van de contractnota.

De terugleververgoeding boven jaarlijkse saldering is € 0,15/kWh, door de gebruiker opgegeven als niet aan btw onderworpen. De kosten van € 0,48970 per dag horen bij de bekende band 1.251–1.500 jaarlijkse teruglever-kWh. Dit is slechts één staffelband. De volledige staffel, btw-/kasbasis, bepaling van het jaarlijkse volume en het aantal factureerbare dagen zijn niet bekend. We rekenen deze dagprijs niet lineair per kWh om en vullen geen bedrag in; voor een volledige jaarnota vraagt de bestaande kern een expliciet bevestigd totaalbedrag per scenario.

### 2027: geen saldering

De contractinvoer vermeldt vanaf 1 januari 2027 € 0,08343/kWh terugleververgoeding (geen btw) en € 0,08092/kWh terugleverkosten. De btw-/kasbasis van die kosten is niet bevestigd. De normale en dal-importtarieven voor 2027 ontbreken volledig; de 2026-tarieven zijn niet doorgetrokken. Het eind van contract-/tariefgeldigheid is onbekend.

### Vaste kosten

Opgegeven per dag: vaste levering € 0,34490, netbeheer € 1,30365 en vermindering energiebelasting −€ 1,72317; rekenkundige som −€ 0,07462/dag. De geldigheidsperiode en btw-/factuurbasis zijn niet bevestigd. De rekenkern rapporteert deze posten apart en voegt ze alleen toe aan totalen wanneer bedrag, periode en btw-basis bevestigd zijn en de meetperiode volledige kalendergrenzen heeft. Vaste kosten zijn gelijk voor beide scenario’s en veranderen de batterijbesparing niet.

## Bestanden

- `config/energy_finance/compare.py`: zelfstandige rekenkern en JSON-commandoregeladapter; uitsluitend Python-standaardbibliotheek, geen netwerk of HA-token.
- `config/energy_finance/tariffs.json`: eenvoudig te wijzigen contractperiodes en beëindigingsdatum saldering.
- `config/energy_finance/observations.example.json`: leeg invoerschema; geen fictieve dagelijkse meetdata.
- `config/packages/energie_thuisbatterij.yaml`: command_line-sensor en geldtemplates.
- `tests/test_energy_finance.py`: uitsluitend synthetische rekentests.

Runtimebestand `observations.json` is Git-genegeerd. Het wordt bewust niet aangemaakt met nullen of voorbeeldverbruik. Een ontbrekend bestand geeft JSON-status `unavailable`, geen € 0,00.

## Tarieven configureren

Alle wijzigingen zijn lokale voorbereiding; installatie vereist afzonderlijke toestemming.

Per plan:

1. `valid_from` is inclusief, `valid_until` exclusief. Vul de echte contract-/belastingperiode in. Er moet precies één plan de volledige ingevoerde periode dekken. Overlappende plannen en een periode die een tarief- of wetswijziging kruist worden geweigerd.
2. Vul `vat_fraction` expliciet in. In het 2026-contractvoorstel is 21% gebruikt om te controleren of de brutocomponenten de opgegeven effectieve tarieven reproduceren, maar de contractnota moet de btw-basis bevestigen voordat `vat_basis_confirmed` of `confirmed` wordt aangezet.
3. `delivery_ex_vat` en `energy_tax_ex_vat` zijn vóór Thuisvoordeel en exclusief btw. De contractwaarden zijn afzonderlijk opgeslagen als brutocomponenten en voor de bestaande formule exact door 1,21 gedeeld. Voeg btw nooit opnieuw toe aan een brutoprijs. `quote_includes_vat` maakt expliciet dat de quote voor de reconstructie inclusief btw is.
4. `quote_includes_vat` en `quote_includes_discount` bepalen hoe `quoted_total` met die componenten wordt gereconstrueerd. De controle accepteert hoogstens € 0,00001/kWh afrondingsverschil. De korting wordt nooit tweemaal toegepast.
5. `delivery_discount_fraction` is 0,10 en geldt uitsluitend op de variabele levering. De rekenkern kort een al als discounted gemarkeerde quote niet nogmaals.
6. `export_credit_cash_per_kwh` en `export_fee_cash_per_kwh` zijn kasbedragen; pas er geen algemene btw-factor op toe. De bekende exportvergoedingen zijn als geen-btw gemarkeerd. De btw-/kasbasis van de 2026-staffelbedragen en 2027-kosten blijft onbevestigd.
7. Contractdatums en deels bekende staffels blijven expliciet incompleet. Zet `confirmed`, `validity_confirmed`, `cash_basis_confirmed` of de btw-basis nooit op true zolang de contractnota de betreffende gegevens niet bevestigt. De runtime levert dan `unavailable`, geen nulbedrag.

De historische referentie 2024–2025 is uitsluitend `3133 − 2366 = 767 kWh`. De rekenkern leest deze referentie niet als waarnemingen en genereert er geen dagverbruik mee.

## Meetgegevens en periode

Vul een echte `observations.json` volgens het lege schema, met getallen als decimale strings. `start` is de lokale kalenderdatum inclusief; `end` exclusief. `observed_until` is de laatste gezamenlijke waarneming met tijdzone. Tijdzone voor de vergelijking is Europe/Amsterdam.

- `without.import_kwh.normal/offpeak`: verschillen van de werkelijke P1-telwerken over de meetperiode, niet de absolute meterstanden.
- `without.export_kwh`: werkelijke teruglevering over diezelfde periode.
- `with.import_kwh.normal/offpeak` en `with.export_kwh`: verschillen van de gesimuleerde P1-meters, over exact dezelfde periode en tariefmomenten.
- Bevestig dekking en gelijktijdigheid expliciet met `coverage_confirmed` en `paired_grid_deltas_confirmed`. Resetdagen, ontbrekende intervallen en een andere beginbasis vereisen nieuwe correcte invoer; zet deze vlaggen dan niet aan.

Bestaande bronnen: P1 import/export, P1-tarief 1/2 en de gesimuleerde import/export zijn eerder via het entity-register vastgesteld. De simulator heeft geen bevestigde eigen normaal/dal-telwerken. **Automatische gegevensaanvoer is daarom nog niet aangesloten.** Er zijn gesynchroniseerde intervalverschillen nodig die aan het op dat moment geldende tarief zijn toegewezen, plus bevestiging welke P1-tariefcode normaal/dal is. Verdeel simulator-import nooit naar verhouding van fysieke import en kies niet het huidige tarief voor een hele dag. Gebruik Growatt niet als extra financiële opbrengst: PV-zelfverbruik zit al in de P1-import/export.

Een aanleverproces mag uitsluitend echte waarnemingen leveren, liefst door een compleet JSON-bestand atomair te vervangen. De command_line-sensor leest dit elke 300 seconden. Deze code schrijft geen metingen, baselines of tarieven terug.

## Formules

Effectief importtarief per tariefgroep (bedragen in de formule ex btw):

```
(levering_ex_btw × (1 − korting) + energiebelasting_ex_btw) × (1 + btw)
```

Na einde saldering, afzonderlijk voor zonder en met batterij:

```
importkosten = som(import_kWh_per_tarief × effectief_importtarief)
exportopbrengst = alle_export_kWh × vergoeding_op_kasbasis
terugleverkosten = alle_export_kWh × kosten_op_kasbasis
variabele_kosten = importkosten − exportopbrengst + terugleverkosten
variabele_besparing = variabele_kosten_zonder − variabele_kosten_met
```

Tot einde saldering is `scope: billing` en een complete afrekenperiode vereist. Vul per scenario `netted_import_kwh.normal/offpeak` in volgens de bevestigde Essent-verrekenwijze; de som moet exact `min(totale_import, totale_export)` zijn en mag import per groep niet overschrijden. De rekenkern raadt geen verdeling. Importkosten worden berekend over resterende afname, zodat Thuisvoordeel na saldering geldt. Alleen overschotexport krijgt vergoeding. Voor terugleverkosten is per scenario het expliciete volledige-periodebedrag `export_charges_eur` plus bevestiging nodig, bepaald met de toepasselijke staffel en looptijd. Geen staffeltarief wordt als lineair kWh-tarief behandeld.

De rapportvelden `without_eur`/`with_eur` blijven variabele kosten voor compatibiliteit; `without_variable_eur`/`with_variable_eur` labelen dit expliciet. De gedeelde `fixed_costs_eur` wordt alleen meegerekend in `without_total_eur` en `with_total_eur` als vaste kosten en de hele periode zijn bevestigd. `saving_eur` is altijd alleen het verschil in variabele kosten; vaste bedragen tellen niet als batterijbesparing.

Een afrekenperiode met tarief-/belastingwijzigingen of die 2027 kruist wordt geblokkeerd. Saldering mag niet per dag of per willekeurige subperiode worden herhaald. Een volledige meerperioden-verrekening vergt de contractuele verdeelregels; de code doet daar geen aanname over.

Gebruik geen aparte laadverliezenfactor of extra besparing uit `total_energy_saved`: de gesimuleerde netimport/export bevat laden, ontladen en verliezen al. Capaciteit, efficiëntie en laadstrategie horen in Battery Simulator. Een eind-SoC die afwijkt van de begin-SoC maakt de uitkomst een periodekasstroom, geen stationaire jaaropbrengst. Waardeer de resterende batterij-inhoud niet nogmaals als verdiend geld.

Zolang vaste kosten of hun btw-basis/geldigheid onbevestigd zijn, toont de dashboardvergelijking alleen variabele energiekosten en blijven totale kosten unavailable. Voor dezelfde aansluiting en periode zijn vaste bedragen gelijk in beide scenario's en vallen ze uit het verschil. Aanschaf, onderhoud en degradatiekosten zijn niet afgetrokken; geen terugverdientijd.

## Home Assistant en dashboard

De oude enkelvoudige import-/exporttariefhelpers blijven voor compatibiliteit bestaan, maar sturen geen geldberekeningen meer aan. Ook de oude bevestigingsschakelaar activeert geen berekening. Contractbevestiging staat nu bij het betreffende gedateerde plan.

- `sensor.stalman_financiele_vergelijking`: status plus reden, periode, tijdstip en kostenattributen.
- `sensor.stalman_kosten_zonder_batterij_vandaag`: geschatte variabele kosten op werkelijke energie.
- `sensor.stalman_kosten_met_batterij_vandaag`: geschatte variabele kosten met virtuele batterij.
- `sensor.stalman_batterijbesparing_vandaag`: verschil, alleen voor vandaag na einde saldering en invoer hoogstens 15 minuten oud.
- `sensor.stalman_besparingsscenario`: verschil voor een volledige afrekenperiode; periodedatums staan op de bronsensor.
- `sensor.stalman_afrekening_kosten_zonder_batterij` en `sensor.stalman_afrekening_kosten_met_simulatie`: variabele kosten voor dezelfde volledige afrekenperiode.
- `sensor.stalman_totaal_afrekening_zonder_batterij` en `sensor.stalman_totaal_afrekening_met_simulatie`: variabele plus vaste kosten, alleen als vaste kosten, btw-basis en datumdekking bevestigd zijn.

Monetaire templates hebben geen `state_class`: gewijzigde contractinvoer herwaardeert de geselecteerde periode en mag niet tot cumulatieve Recorder-besparingen leiden. Het dashboard toont variabele kosten apart van totale kosten inclusief vaste posten; vaste posten veranderen het besparingsverschil niet. Het tabblad Overzicht en het volledige batterijtabblad zijn behouden; de financiële secties wijzen nu naar de contractjaarplannen en gekozen meet-/afrekenperiode. Een historische dag kan lokaal wel worden berekend, maar verschijnt niet als ‘vandaag’.

## Lokaal testen en latere installatie

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate_energy_dashboard.py
python3 config/energy_finance/compare.py \
  --config config/energy_finance/tariffs.json \
  --input config/energy_finance/observations.example.json
```

De tweede opdracht hoort `unavailable` te geven: contract- en meetgegevens zijn onvolledig. De actuele 2026 effective-rate assertions en salderingsscenario zijn synthetische tests; zij maken de productieconfiguratie niet confirmed. Voor de YAML-/HA-templatecontrole:

```sh
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_energy_dashboard.py
```

Voor latere installatie, uitsluitend na toestemming: controleer back-up en actieve versies, plaats dashboard, package, rekenkern en tarieven onder `/config`; vul alleen geverifieerde echte waarnemingen in. Hoofdconfiguratie, oorspronkelijk UI-dashboard en Docker blijven ongewijzigd. Eerst Home Assistant-configuratiecontrole, pas daarna een toegestane herstart. Het eerder gebruikte `docker exec ... check_config` vereist nog steeds bevoegde beheertoegang; daarvoor worden geen rechten verhoogd.

## Nog nodig

Contractnota met geldigheidsdatums, btw-basis van de 2026-componenten, toepasselijke 2027 importtarieven, btw-/kasbasis van terugleverkosten, volledige 2026 staffeltabel en factureerbare dagen, en de contractuele normaal/dal-verdeling van jaarlijkse saldering. De P1-registers 1/2 zijn aanwezig, maar hun normaal/dal-mapping is niet betrouwbaar bevestigd; `mapping_confirmed` blijft false en de auditpolicy staat uit. Ook is gekoppelde, aaneengesloten P1-/simulatoraanvoer nodig. Tot bevestiging blijft **Nog niet beschikbaar** de correcte uitkomst.

2026- en 2027-plannen staan afzonderlijk in de config, maar de command-line-rekenkern rekent steeds één aangeleverde meet-/afrekenperiode tegelijk. Zij maakt geen vergelijking door 2026-verbruik te kopiëren naar 2027 of door historische jaarreferenties als simulatie te gebruiken.

## Intervalverzamelaar

Een lokale implementatie met een afzonderlijk HA-package is nu voorbereid. Zie [INTERVAL_COLLECTOR.md](INTERVAL_COLLECTOR.md) voor de tellerbronnen, SQLite-baselines, tarief- en restartdetectie, gedeelde meetvensters en de beperkingen rond asynchrone bronnen en daggrenzen. Deze is niet geïnstalleerd. Mapping en bronafstemming blijven onbevestigd. De rekenkern accepteert uitsluitend een expliciet gemarkeerd gedeeltelijk eerste-dagvenster; meetvenster en dekkingssoort worden in de financiële rapportmetadata behouden. Zonder die markering is een gedeeltelijke periode ongeldig.

De bronbewuste collector-revisie kan inmiddels P1 en simulator afzonderlijk registreren, maar bevestigt **geen** financiële meetvensters: onderzoek van de geïnstalleerde simulator toont dat verwerkte P1-grenzen ontbreken. De oude `pairing_confirmed`-vlag werkt niet meer als toestemming. Zie INTERVAL_COLLECTOR.md voor de vereiste simulatorbatchgegevens; tot die beschikbaar zijn blijven collectorbedragen onbeschikbaar.

## Voorgestelde atomair geattesteerde meetvensters

Zie [BATTERY_SYNC.md](BATTERY_SYNC.md). De lokale rekenkern ondersteunt nu scope `window` voor één expliciet gecertificeerd meetvenster. Deze scope is gescheiden van `day` en `billing`; geldbedragen verschijnen in aparte venstersensoren, met zichtbaar begin/einde. Vóór het einde van saldering blijft ook deze scope financieel geblokkeerd. De auditpolicy staat uit en de noodzakelijke producent bestaat alleen als lokaal voorstel. Ongewijzigde sensoren kunnen nog steeds geen certificering geven.
