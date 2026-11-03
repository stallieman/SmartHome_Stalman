# Energie & Thuisbatterij

Afzonderlijk YAML-dashboard voor Home Assistant 2026.10.4, voorbereid op 30 oktober 2026. De bestaande storage-dashboarddefinitie blijft behouden. Geen HACS-kaarten nodig.

## Bestanden

- `config/dashboards/energie_thuisbatterij.yaml`: drie tabbladen, 44 ingebouwde kaarten.
- `config/packages/energie_thuisbatterij.yaml`: negen templates, een command_line-adapter en bestaande invoervelden.
- `config/themes/stalman_nacht.yaml`: donker thema met mintgroene en amberkleurige accenten.
- `docs/activation.example.yaml`: te beoordelen registratiefragment; niet automatisch geladen.
- `docs/ENTITIES.md`: alle 27 gebruikte entiteiten, inclusief 6 nieuwe lokale helpers/templates.
- `scripts/validate_energy_dashboard.py`: offline controles zonder servertoegang.

## Ontwerp en betekenis

**Energie:** actuele woningbelasting, gesigneerd netvermogen, zonnevermogen, net/woning/zon-verdeling, elektriciteit, zonneproductie en gas. De datumkiezer stuurt de energiekaarten via `energy_stalman`. Deze gebruiken de bestaande centrale energieconfiguratie: P1-import/export, Growatt levenslange productie en gasmeter. Geen batterij toevoegen aan die werkelijke stromen.

**Simulatie:** SoC, opgeslagen energie, laad-/ontlaadvermogen, status, 24-uursverloop en 7-daagse SoC-statistieken. Totalen tonen laden, ontladen, bespaarde import en cycli sinds simulatorstart/reset. Ontwerpparameters komen uit de opdracht, niet uit uitgelezen integratieopties. Er zijn geen simulatorbedienings- of resetknoppen.

**Analyse:** dagelijkse verandering van werkelijke en gesimuleerde import over 14 dagen, met afzonderlijk de cumulatieve referentiemeters. Vergelijk alleen overlappende volledige dagen. Gesimuleerde meters beginnen bij de oorspronkelijke meterstand en kunnen later opnieuw worden gestart; trek absolute totalen niet blind van elkaar af.

Het woningvermogen is `max(0, P1-netvermogen + Growatt-vermogen)` in W. Dit veronderstelt dat Growatt alle zonneproductie vertegenwoordigt en er geen fysieke batterij achter de P1 zit. Negatieve uitkomsten door verschillende meetmomenten worden op nul begrensd. De bronwaarden blijven zichtbaar. Gebruik dit niet als nauwkeurige gesynchroniseerde verbruiksmeting.

Sections toont maximaal drie kolommen en loopt op smalle schermen door in één kolom. Geen vaste schermbreedtes of externe lettertypen. Het thema is aan iedere view gekoppeld; het bestaande gebruikersdashboard wordt niet van thema veranderd.

## Financiële grenzen

De financiële rekenregels zijn vervangen door de [Essent-vergelijking](FINANCE.md). Deze gebruikt afzonderlijke gemeten en gesimuleerde netimport/export per tariefgroep en periode. Oude tariefhelpers activeren geen berekening meer. Ontbrekende contract- en meetgegevens blokkeren bedragen; er wordt geen terugverdientijd berekend.

## Installatie — pas na expliciete toestemming

Deze stappen zijn **niet uitgevoerd**. De lokale hoofdconfiguratie is niet gewijzigd en de server heeft geen schrijfacties ontvangen.

1. Laat de voorgenomen activatie goedkeuren. Maak vooraf via de eigen beheerprocedure een herstelbare configuratiebackup. Laat `.storage` onaangeroerd.
2. Plaats na toestemming uitsluitend de drie nieuwe dashboard-, package- en themabestanden in de overeenkomstige mappen onder `/home/stallieman/SmartHome_Stalman/config`. Gebruik geen complete repository-sync die runtimebestanden zou kunnen overschrijven.
3. Voeg de twee blokken uit `docs/activation.example.yaml` zorgvuldig samen met de actuele `configuration.yaml`. Maak geen dubbele `homeassistant:` of `lovelace:` sleutels. Als er al packages/dashboards via includes bestaan, voeg de vermeldingen op de juiste plek samen. Het fragment is een voorbeeld, geen vervanging van de hoofdconfiguratie. Laat de standaard Lovelace-modus behouden; alleen het nieuwe dashboard krijgt `mode: yaml`.
4. Controleer of `frontend.themes: !include_dir_merge_named themes` actief is. Dit staat al in de lokale hoofdconfiguratie; de serverhoofdconfiguratie is niet gelezen. Gebruik een bestaande theme-include wanneer aanwezig.
5. Voer via Home Assistant **Ontwikkelaarstools → YAML → Configuratie controleren** uit. Bij fouten niet herstarten. Pas na een geslaagde controle en toestemming Home Assistant herstarten om package en dashboardregistratie te laden. Docker-roottoegang is hiervoor niet nodig. Bij afwezigheid van deze beheerrechten: laat de beheerder deze stap doen.
6. Open het nieuwe zijbalkdashboard, pad `/energie-thuisbatterij-yaml/energie`. Het bestaande ‘Energie & Thuisbatterij’ blijft daarnaast beschikbaar. Controleer dat beide nieuwe template-ID’s exact overeenkomen met de inventaris; bestaande naamconflicten kunnen een suffix veroorzaken.
7. Controleer desktop en iPhone (circa 390 px breed): leesbaarheid, grafieken, scrollvolgorde, donker thema. Verifieer P1-teken, Growatt-eenheid en actualiteit; SoC en vermogen horen bij **simulatie**. Vergelijk datumselectie met de ingebouwde Energie-pagina. Lege historie is toegestaan zolang de bron nog geen statistieken heeft.
8. Vul financiële contract- en meetinvoer alleen volgens FINANCE.md in; de oude tariefhelpers worden niet meer gebruikt. Houd terugverdientijd op ‘nog niet beschikbaar’.

## Beheer en herstel

Bewerk voortaan de YAML in Git. Dashboardkaartwijzigingen kunnen na deployment en browserverversing zichtbaar worden; bij configuratie- of helperwijzigingen opnieuw de configuratie controleren en de betreffende herlaad/herstartprocedure gebruiken. Themawijzigingen kunnen via `frontend.reload_themes` worden geladen. Pas geen gegenereerde `.storage/lovelace.*` bestanden aan.

Voor terugdraaien: verwijder na toestemming uitsluitend de registratie van het nieuwe YAML-dashboard en het nieuwe package uit de hoofdconfiguratie, controleer en herstart. Het oorspronkelijke dashboard en de integraties blijven beschikbaar. Verwijder geen Recorder-gegevens of helpers via runtimebestanden.

Commit nooit `.storage`, secrets, databases of logs bij dashboardwijzigingen. De repository bevatte al een gevolgde `.storage/energy`; die is tijdens deze opdracht niet gewijzigd of opnieuw toegevoegd.

## Validatie en beperkingen

Zie [VALIDATION.md](VALIDATION.md). De entiteiten zijn read-only in het register gecontroleerd; dit is geen live beschikbaarheidscontrole. Er zijn geen API-tokens gelezen of gebruikt. Docker-toegang was in de eerdere controle geweigerd; er zijn geen Docker-commando's met verhoogde rechten geprobeerd.

Ontbrekend: bevestigde tarieven, aanschafkosten, geverifieerde laadstrategie, gelijktijdigheid/actualiteit van metingen, statistiekdekking en een representatieve jaarbesparing. De interface maakt de beperkingen zichtbaar. Een echte frontend-/iPhone-controle en HA-schema-validatie wachten op de goedgekeurde activatie.

## Bronnen

Gecontroleerd tegen de officiële documentatie met versieaanduiding 2026.10.4:

- [Energiekaarten en datumcollecties](https://www.home-assistant.io/dashboards/energy/)
- [Sections en responsieve indeling](https://www.home-assistant.io/dashboards/sections/)
- [Afzonderlijke YAML-dashboards](https://www.home-assistant.io/dashboards/dashboards/)
- [Templates en beschikbaarheid](https://www.home-assistant.io/integrations/template/)
- [Thema’s](https://www.home-assistant.io/integrations/frontend/)
- [Getalhelpers en herstellen van invoer](https://www.home-assistant.io/integrations/input_number/)

De geïnstalleerde Battery Simulator-broncode (`sensor.py` en gerichte energieberekeningen in `__init__.py`) is alleen gelezen om de eenheden, herstelwerking en totalen te duiden. Er is geen integratiecode gekopieerd of aangepast.


## Herontwerp Overzicht

Het eerste tabblad heet nu **Overzicht**; het bestaande pad `energie` is behouden. De overige twee YAML-views zijn inhoudelijk exact gelijk aan commit `f9baab7` (in deze repository heten die **Simulatie** en **Analyse**; er zijn lokaal geen views met de namen Grafieken of Batterij & €). Er zijn geen tabbladen vervangen of toegevoegd.

Vijf secties vormen maximaal twee kolommen: Actueel, Kantoor · P115 (Tapo-stekker: schakelaar, huidig gebruik, verbruik vandaag/deze maand, spanning, stroom en wifi-signaal; bediening alleen via more-info), Vandaag, Energiestromen en Verbruik. Op de iPhone worden secties onder elkaar geplaatst; de cijferkaarten staan per twee. Native Markdown-kaarten gebruiken grote cijfers en expliciete eenheden. Kleuren en thema blijven behouden. Netto P1-vermogen toont + voor afname en − voor teruglevering. De batterijkaart bevat zowel SoC als laad-/ontlaadvermogen in W en het label simulatie.

Vijf nieuwe `utility_meter`-dagmeters volgen import, export, zonneproductie, bespaarde import en geladen batterij-energie. Een aanvullende template bepaalt huisverbruik als import + zon − export; de geldtemplate krijgt haar uitkomst uitsluitend uit de gecontroleerde Essent-vergelijking (zie FINANCE.md). De eerste dag bevat alleen metingen sinds installatie; dit staat kort in de interface. Er wordt geen eerdere daghistorie gereconstrueerd. Verlies van brondata maakt nieuwe templates onbeschikbaar. Laat de simulator niet resetten midden op een vergelijkingsdag.

De energiestroomvisualisatie en daggrafiek gebruiken centrale Recorder-statistieken, met een eigen collectie `energy_stalman_overzicht` zonder datumkiezer. Ze tonen standaard vandaag. De dagmeters kunnen op de eerste installatiedag minder historie bevatten dan die energiekaarten. De grafiek toont elektriciteitsverbruik in kWh per tijdvak; actuele W staan bovenaan. De virtuele batterij wordt niet aan de werkelijke energiestromen toegevoegd.

De besparingskaart toont **Nog niet beschikbaar** bij ontbrekende brondata, onbevestigde contracttarieven of een dagperiode waarvoor jaarlijkse saldering geldt. Een bevestigde nulprijs is wel toegestaan. De uitkomst blijft een scenario, geen werkelijke eurobesparing. Tarieven, saldering en laadstrategie moeten nog worden bevestigd.

Voor installatie van deze revisie zijn alleen de dashboard-YAML en package-YAML veranderd. Er zijn geen wijzigingen nodig aan hoofdconfiguratie, dashboardregistratie of thema als de eerdere installatie actief is. Nieuwe dagmeters vereisen configuratiecontrole en een passende herlaad-/herstartprocedure, uitsluitend na afzonderlijke toestemming. Er is tijdens dit herontwerp niets op Ubuntu gewijzigd.

Aanvullende bronnen: [Utility Meter en eerste onvolledige cyclus](https://www.home-assistant.io/integrations/utility_meter/) en [Markdown-kaarten met templates](https://www.home-assistant.io/dashboards/markdown/).

De financiële analyse bevat nu afzonderlijke kaarten voor een geattesteerd meetvenster; het begin/einde blijft zichtbaar en de bedragen worden niet als dag- of jaartotaal gepresenteerd. Auditproducent en toestemming staan uit. Zie BATTERY_SYNC.md.
