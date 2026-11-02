# Historische importkosten — indicatieve raming

Dit afzonderlijke pad berekent uitsluitend bruto P1-importkosten vóór saldering. Home Assistant levert
uurmutaties via de ingebouwde actie `recorder.get_statistics`; de Pythonmodule leest Recorder niet direct.
Tarief 1 wordt via de bevestigde mapping in `tariffs.json` als dal gebruikt en tarief 2 als normaal.

`tariffs.json` blijft de enige tariefbron. De module gebruikt `compare.py` voor dezelfde reconstructie van
levering, 10% leveringskorting, energiebelasting en btw. Zij zet bevestigingsvlaggen alleen op een tijdelijke
kopie om de bekende rekenkundige samenhang te valideren. Het resultaat blijft `classification: indicatief` en
rapporteert de echte bevestigingsstatus van ieder plan.

De meetgrens `2026-10-30T20:36:47+01:00` is uitsluitend de eerste beschikbare P1-waarneming. Zij is geen
contractdatum. Alleen volledige UTC-uurvakken binnen de gevraagde periode worden gewaardeerd. Gedeeltelijke
grensuren worden apart vermeld en uitgesloten. Een ontbrekend of dubbel binnenuur, negatieve mutatie,
ongeldige mapping of ongeldig tarief blokkeert alle kostenvelden.

Niet inbegrepen: saldering, exportvergoeding, terugleverkosten, vaste kosten en batterijbesparing. De
automatisering `Stalman historische importkosten dagelijks` voert het bestaande script elke dag om 06:15 lokale
Home Assistant-tijd uit voor de vorige lokale kalenderdag. Beide tijdgrenzen zijn tijdzonebewust; een lokale
dag kan door zomer-/wintertijd 23 of 25 uur bevatten.

Het script wist bij iedere uitvoering eerst de compacte JSON-helper. Alleen een geldige, volledige berekening
voor gisteren wordt als bedrag opgeslagen. De template-sensor controleert status, datum en uurdekking opnieuw;
een oude of onvolledige uitkomst wordt dus niet als actuele waarde getoond. De helper is begrensd op 255
tekens. Het energiedashboard toont uitsluitend bedrag, datum en dekking, zonder financiële batterijclaims.

De checkout bevat de package- en dashboardwijzigingen; deze zijn niet naar de actieve Home Assistant-installatie
gedeployed. Configuratiecontrole, installatie en herstart vereisen afzonderlijk akkoord.
