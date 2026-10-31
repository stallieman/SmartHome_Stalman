# Essent en de virtuele Marstek — financiële vergelijking

Ontwikkeld op 31 oktober 2026, uitsluitend lokaal. Geen serverwijzigingen of herstart. Alle euro-uitkomsten zijn **schattingen op gemeten energie**; de batterijvariant is **simulatie**. Er is geen gemeten factuurbedrag of terugverdientijd afgeleid.

## Wat is bevestigd en wat niet?

Officiële bronnen:

- [Essent Thuisvoordeel](https://www.essent.nl/klanten/thuisvoordeel): korting op het leveringstarief inclusief btw, niet op energiebelasting/netbeheerkosten; geen korting bij dynamisch contract.
- [Actievoorwaarden Thuisvoordeel](https://www.essent.nl/-/media/essent/documenten/essent/particulier/pdf/algemeen/thuisvoordeel-voorwaarden.pdf): toepassing na saldering. De tekst was via de zoekindex beschikbaar; direct ophalen gaf HTTP 403.
- [Rijksoverheid — einde saldering](https://www.rijksoverheid.nl/themas/klimaat-milieu-en-natuur/energie-thuis/salderingsregeling): jaarlijks salderen tot en met 31 december 2026; vanaf 1 januari 2027 niet meer.
- [ACM ConsuWijzer](https://consument.acm.nl/elektriciteit-en-gas/duurzame-energie/wat-is-salderen): saldering inclusief belasting en btw; daarna belasting/btw over alle afname.
- [Essent terugleverkosten](https://www.essent.nl/klantenservice/contract/terugleverkosten): vóór 2027 staffels; tarieven vanaf 2027 verschillen per klant en staan in de contractbevestiging/brief. Rechtstreeks ophalen gaf 403; relevante passages waren via de zoekindex beschikbaar.
- [Rijksoverheid — opbouw energierekening](https://www.rijksoverheid.nl/documenten/vraag-en-antwoord/energie-thuis/opbouw-energierekening): 21% btw, ook over energiebelasting. Dit is geen bewijs van de btw-status of periode van de specifieke aangeleverde bedragen.

De opgegeven € 0,31274 en € 0,30911 staan als **onbevestigde contractinvoer** in `tariffs.json`. De exacte geldigheidsperiode, levering/belasting-splitsing, btw-basis en eventuele al verwerkte korting ontbreken. Er is geen publieke bron gevonden die deze bedragen aan dit contract koppelt. Daarom is geen belastingbedrag van een willekeurig jaar ingevuld.

€ 0,08343 vergoeding en € 0,08092 terugleverkosten staan alleen in het onbevestigde plan vanaf 2027. Hun einde en btw-/kasbasis moeten uit de contractbrief blijken. Alleen wanneer beide bedragen dezelfde kasbasis hebben, is het rekenkundige netto verschil € 0,00251/kWh. Dit is geen automatisch toegepast tarief. Huidige importtarieven worden niet naar 2027 gekopieerd.

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
2. Vul `vat_fraction` expliciet in, bijvoorbeeld de daadwerkelijk toepasselijke btw-fractie. Vul beide tariefgroepen in; de eenheid is EUR/kWh.
3. `delivery_ex_vat` en `energy_tax_ex_vat` zijn vóór Thuisvoordeel en exclusief btw. Het leveringstarief bevat geen belasting. Voeg geen btw meer toe aan componenten die al inclusief btw zijn; reken die eerst aantoonbaar terug.
4. `quote_includes_vat` en `quote_includes_discount` bepalen hoe `quoted_total` met die componenten wordt gereconstrueerd. De controle accepteert hoogstens € 0,00001/kWh afrondingsverschil. De korting wordt nooit tweemaal toegepast.
5. `delivery_discount_fraction` staat op de opgegeven 0,10. Bevestig contracttype, recht op korting, eventuele maximumgrens en de geldigheidsperiode. De rekenkern ondersteunt één constant kortingspercentage op alle netto gefactureerde levering binnen het plan; andere kortingsregels vereisen een uitbreiding.
6. `export_credit_cash_per_kwh` en, na saldering, `export_fee_cash_per_kwh` zijn de **werkelijke eurobedragen die het huishouden ontvangt/betaalt**, na toepasselijke btw-behandeling. Een vergoeding buiten de btw en een inclusief-btw kostenpost mogen dus niet met een generieke btw-factor worden bewerkt. Zet `cash_basis_confirmed` pas aan na contractcontrole.
7. Zet `confirmed` pas op `true` als alle onderdelen zijn gecontroleerd. Ontbrekende of afwijkende componenten blokkeren de berekening.

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

Effectief importtarief per tariefgroep:

```
(levering_ex_btw × (1 − korting) + energiebelasting_ex_btw) × (1 + btw)
```

Na einde saldering, afzonderlijk voor zonder en met batterij:

```
importkosten = som(import_kWh_per_tarief × effectief_importtarief)
exportopbrengst = alle_export_kWh × vergoeding_op_kasbasis
terugleverkosten = alle_export_kWh × kosten_op_kasbasis
variabele_kosten = importkosten − exportopbrengst + terugleverkosten
besparing = kosten_zonder − kosten_met
```

Tot einde saldering is `scope: billing` en een complete afrekenperiode vereist. Vul per scenario `netted_import_kwh.normal/offpeak` in volgens de bevestigde Essent-verrekenwijze; de som moet exact `min(totale_import, totale_export)` zijn en mag import per groep niet overschrijden. De rekenkern raadt geen verdeling. Importkosten worden berekend over resterende afname, zodat Thuisvoordeel na saldering geldt. Alleen overschotexport krijgt vergoeding. Voor terugleverkosten is per scenario het expliciete volledige-periodebedrag `export_charges_eur` plus bevestiging nodig, bepaald met de toepasselijke staffel en looptijd. Geen staffeltarief wordt als lineair kWh-tarief behandeld. De gesimuleerde staffelkosten zijn een contractberekening, geen gemeten betaling.

Een afrekenperiode met tarief-/belastingwijzigingen of die 2027 kruist wordt geblokkeerd. Saldering mag niet per dag of per willekeurige subperiode worden herhaald. Een volledige meerperioden-verrekening vergt de contractuele verdeelregels; de code doet daar geen aanname over.

Gebruik geen aparte laadverliezenfactor of extra besparing uit `total_energy_saved`: de gesimuleerde netimport/export bevat laden, ontladen en verliezen al. Capaciteit, efficiëntie en laadstrategie horen in Battery Simulator. Een eind-SoC die afwijkt van de begin-SoC maakt de uitkomst een periodekasstroom, geen stationaire jaaropbrengst. Waardeer de resterende batterij-inhoud niet nogmaals als verdiend geld.

Vaste levering, netbeheer en belastingvermindering ontbreken bewust in deze **variabele kostenvergelijking**. Voor dezelfde aansluiting en periode zijn ze in beide scenario's gelijk en vallen ze uit het verschil. De getoonde kosten zijn dus geen volledige energierekening. Aanschaf, onderhoud en degradatiekosten zijn niet afgetrokken; geen terugverdientijd.

## Home Assistant en dashboard

De oude enkelvoudige import-/exporttariefhelpers blijven voor compatibiliteit bestaan, maar sturen geen geldberekeningen meer aan. Ook de oude bevestigingsschakelaar activeert geen berekening. Contractbevestiging staat nu bij het betreffende gedateerde plan.

- `sensor.stalman_financiele_vergelijking`: status plus reden, periode, tijdstip en kostenattributen.
- `sensor.stalman_kosten_zonder_batterij_vandaag`: geschatte variabele kosten op werkelijke energie.
- `sensor.stalman_kosten_met_batterij_vandaag`: geschatte variabele kosten met virtuele batterij.
- `sensor.stalman_batterijbesparing_vandaag`: verschil, alleen voor vandaag na einde saldering en invoer hoogstens 15 minuten oud.
- `sensor.stalman_besparingsscenario`: verschil voor een volledige afrekenperiode; periodedatums staan op de bronsensor.

Monetaire templates hebben geen `state_class`: gewijzigde contractinvoer herwaardeert de geselecteerde periode en mag niet tot cumulatieve Recorder-besparingen leiden. Het tabblad Overzicht en het volledige batterijtabblad zijn behouden; de financiële secties wijzen nu naar de nieuwe vergelijking. Een historische dag kan lokaal wel worden berekend, maar verschijnt niet als ‘vandaag’.

## Lokaal testen en latere installatie

```sh
python3 -m unittest discover -s tests -v
python3 config/energy_finance/compare.py \
  --config config/energy_finance/tariffs.json \
  --input config/energy_finance/observations.example.json
```

De tweede opdracht hoort nu `unavailable` te geven: gegevens zijn onbevestigd. Voor de YAML-/HA-templatecontrole:

```sh
/private/tmp/stalman-dashboard-venv/bin/python scripts/validate_energy_dashboard.py
```

Voor latere installatie, uitsluitend na toestemming: controleer back-up en actieve versies, plaats dashboard, package, rekenkern en tarieven onder `/config`; vul alleen geverifieerde echte waarnemingen in. Hoofdconfiguratie, oorspronkelijk UI-dashboard en Docker blijven ongewijzigd. Eerst Home Assistant-configuratiecontrole, pas daarna een toegestane herstart. Het eerder gebruikte `docker exec ... check_config` vereist nog steeds bevoegde beheertoegang; daarvoor worden geen rechten verhoogd.

## Nog nodig

Contractblad met exacte ingangs-/einddatums, levering/belasting en btw-specificatie, reeds verwerkte korting, 2027-importtarieven, cash-basis van vergoeding/kosten, vóór-2027 staffel en normaal/dal-salderingsregels, en een betrouwbare gekoppelde intervalaanvoer met simulator-tariefverdeling. Tot die tijd is **Nog niet beschikbaar** de correcte uitkomst.

## Intervalverzamelaar

Een lokale implementatie met een afzonderlijk HA-package is nu voorbereid. Zie [INTERVAL_COLLECTOR.md](INTERVAL_COLLECTOR.md) voor de tellerbronnen, SQLite-baselines, tarief- en restartdetectie, gedeelde meetvensters en de beperkingen rond asynchrone bronnen en daggrenzen. Deze is niet geïnstalleerd. Mapping en bronafstemming blijven onbevestigd. De rekenkern accepteert uitsluitend een expliciet gemarkeerd gedeeltelijk eerste-dagvenster; meetvenster en dekkingssoort worden in de financiële rapportmetadata behouden. Zonder die markering is een gedeeltelijke periode ongeldig.

De bronbewuste collector-revisie kan inmiddels P1 en simulator afzonderlijk registreren, maar bevestigt **geen** financiële meetvensters: onderzoek van de geïnstalleerde simulator toont dat verwerkte P1-grenzen ontbreken. De oude `pairing_confirmed`-vlag werkt niet meer als toestemming. Zie INTERVAL_COLLECTOR.md voor de vereiste simulatorbatchgegevens; tot die beschikbaar zijn blijven collectorbedragen onbeschikbaar.
