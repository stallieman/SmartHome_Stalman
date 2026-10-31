# Ring Camera's

Afzonderlijk YAML-dashboard met uitsluitend standaardkaarten voor Home Assistant 2026.10.4. Pad: `/ring-cameras/overzicht`.

## Bestanden en registratie

- [Dashboard](../config/dashboards/ring_cameras.yaml): Sections, maximaal twee kolommen; op smalle schermen Voordeur, Tuin en daarna activiteit.
- [Hoofdconfiguratie](../config/configuration.yaml): extra registratie onder `lovelace.dashboards.ring-cameras`.

De server heeft ook een bestaande registratie `energie-thuisbatterij-yaml` en een energiepackage die niet in de lokale hoofdconfiguratie staan. Voeg bij deployment uitsluitend de Ring-registratie samen met de actuele serverconfiguratie. Overschrijf de hoofdconfiguratie nooit vanuit deze checkout. Bestaande storage-dashboards blijven ongewijzigd.

## Gedrag

- Camerakaarten tonen een voorbeeld uit de laatste opname, niet een permanent livebeeld. Tik opent de standaard cameradetails voor livebeeld. Een voorbeeld kan oud zijn en is geen bewijs van actuele bereikbaarheid. Ontbreekt de opname-URL (`none` of een lege string), dan verschijnt alleen een compacte knop ‘Livebeeld openen’, zonder lege afbeeldingskaart. Dit wordt via standaard template-zichtbaarheidsvoorwaarden bepaald.
- Gebeurtenissen worden als tijdstempel weergegeven. Gedurende de eerste minuut na een ontvangen gebeurtenis verschijnt nadruk; een melding betekent niet dat beweging nog actief is. De tijdvergelijking wordt door `now()` iedere minuut ververst.
- `unknown` en `unavailable` worden niet als gebeurtenis geïnterpreteerd. Zonder geldig tijdstempel staat er dat nog geen gebeurtenis ontvangen is. Dit kan na herstart voorkomen en zegt niets over eerdere Ring-cloudactiviteit.
- De gezamenlijke Activity-kaart toont maximaal de afgelopen 24 uur voor uitsluitend aanbellen en beweging. De sectie blijft verborgen zolang alle drie gebeurtenisentiteiten onbekend/onbeschikbaar zijn. HA-recorderhistorie is geen Ring-opnamebibliotheek; een geldig oud tijdstempel garandeert geen activiteit binnen deze 24 uur.
- Batterijwaarschuwingen verschijnen alleen bij een numerieke waarde onder 20%. Onbekende waarden worden niet als nul geïnterpreteerd.
- Bij onbekende/onbeschikbare camera wordt de afbeelding verborgen en een waarschuwing getoond. Dit bewijst niet dat de fysieke camera offline is.
- Uitgeschakelde bewegingsdetectie wordt gemeld. Het dashboard bevat geen schakelaars, sirenebediening, volumecontrole of andere apparaatbedieningen.
- De aparte laatste-opname-entiteiten blijven uitgeschakeld. Geen integratiewijzigingen, helpers, automations, HACS, externe diensten of nieuw thema nodig.

## Gecontroleerde bronnen

Via de bestaande aangemelde HA-browsersessie op 31 oktober 2026: beide livecamera-entiteiten `idle`, batterij Voordeur 54% en Tuin 94%, beide bewegingsdetectieschakelaars `on`; de drie gebeurtenisentiteiten `unknown`. Dit is een momentopname, geen permanente status.

## Uitgevoerde validatie en activatie

Op 31 oktober 2026 is na afzonderlijk akkoord uitsluitend het Ring-dashboardbestand geplaatst en de Ring-registratie aan de bestaande serverconfiguratie toegevoegd. De configuratiecontrole meldde `valid`, zonder fouten of waarschuwingen. Home Assistant is via de bestaande aangemelde beheersessie herstart. Een herstelkopie van de voorafgaande serverconfiguratie staat buiten Git onder `/home/stallieman/.ring-dashboard-backup.yL1LDM/configuration.yaml`.

Gecontroleerd:

- YAML-syntaxis, registratie, uitsluitend standaardkaarten, bestaande entiteitsnamen en livebeeld uitsluitend op verzoek.
- Beide camera-afbeeldingen laden na de eerste Ring-update. Direct na de herstart gaf de voorbeeldweergave aanvankelijk HTTP 500; daarom is een ontbrekende opname-URL expliciet afgevangen. Een aanwezige maar verlopen URL kan alsnog een laadfout geven.
- Beide cameradetails spelen daadwerkelijk video af op 1920×1080 (`readyState=4`, niet gepauzeerd). De details zijn daarna gesloten; op het overzicht zijn geen actieve videospelers achtergebleven.
- Desktop toont twee camerakolommen; een browserviewport van 390×844 CSS-pixels toont Voordeur boven Tuin, zonder horizontale overflow. Dit is viewportvalidatie, geen fysieke iPhone/Safari-test.
- De Markdown-templates renderen op de echte HA-backend. Aanvullend zijn ontbrekende voorbeeld-URLs en recente gebeurtenistijdstempels met uitsluitend tijdelijke template-invoer getest; geen echte entiteiten gewijzigd.
- De activiteitsectie is verborgen zolang alle drie gebeurtenisentiteiten onbekend zijn. Een fysieke aanbeldruk, echte bewegingsmelding en de daardoor opgebouwde historie zijn niet getest.

Geen bestaande dashboards, automations of Ring-integratie-instellingen gewijzigd. Geen commits of pushes uitgevoerd.

De officiële Ring-integratie ondersteunt in deze release livebeeld via WebRTC. Communicatie loopt via de Ring-cloud; tweerichtingsaudio wordt niet ondersteund. Opnameweergave vereist passende Ring-abonnementsdekking. Realtimegebeurtenissen vereisen uitgaand TCP 5228. Geen tokens of tijdelijke videolinks opnemen in bestanden of uitvoer.

## Deployment en herstel

Alleen na expliciete toestemming: plaats uitsluitend het dashboardbestand op de server, voeg de dashboardregistratie toe zonder bestaande YAML-blokken te vervangen, controleer de HA-configuratie en herstart Home Assistant via de bestaande beheersessie. Valideer daarna iPhone-/desktopweergave en de bestaande dashboards. Livebeeld start pas bij het openen van cameradetails; doe dit alleen als test gewenst is.

Bewaar vóór de serverconfiguratiewijziging een herstelkopie buiten Git. Voor terugdraaien: verwijder alleen de Ring-registratie en het Ring-dashboardbestand, controleer de configuratie en herstart. Geen `.storage`-bestanden aanpassen.

## Bronnen

- [Ring](https://www.home-assistant.io/integrations/ring/)
- [Picture entity](https://www.home-assistant.io/dashboards/picture-entity/)
- [Sections](https://www.home-assistant.io/dashboards/sections/)
- [Activity](https://www.home-assistant.io/dashboards/logbook/)
