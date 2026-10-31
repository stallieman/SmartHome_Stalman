# Gebruikte entiteiten

Gericht gecontroleerd via SSH op 2026-10-30. Registervermelding bevestigt geen actuele beschikbaarheid. Geen live API of geheimen gebruikt. Eenheden uit het entity-register; ontbrekende sensor-eenheden zijn als — weergegeven.

| Entiteit | Eenheid | Herkomst |
|---|---|---|
| `input_boolean.stalman_tarieven_bevestigd` | aan/uit | Nieuw lokaal package |
| `input_number.stalman_aanschafkosten` | EUR | Nieuw lokaal package |
| `input_number.stalman_exporttarief` | EUR/kWh | Nieuw lokaal package |
| `input_number.stalman_importtarief` | EUR/kWh | Nieuw lokaal package |
| `sensor.gas_meter_gas` | m³ | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_battery_cycles` | — | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_battery_energy_in` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_battery_energy_out` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_battery_mode_now` | — | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_current_charging_rate` | kW | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_current_discharging_rate` | kW | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_extra_money_earned_on_exports` | EUR | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_money_saved_on_imports` | EUR | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_simulated_sensor_p1_meter_energie_export` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_simulated_sensor_p1_meter_energie_import` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_state_of_charge` | % | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_total_energy_saved` | kWh | Bestaand · ingeschakeld |
| `sensor.marstek_venus_e_5_12kwh_3nd_gen_total_money_saved` | EUR | Bestaand · ingeschakeld |
| `sensor.p1_meter_energie_export` | kWh | Bestaand · ingeschakeld |
| `sensor.p1_meter_energie_import` | kWh | Bestaand · ingeschakeld |
| `sensor.p1_meter_vermogen` | W | Bestaand · ingeschakeld |
| `sensor.stalman_besparingsscenario` | EUR | Nieuw lokaal package |
| `sensor.stalman_total_energieopbrengst_levenslang` | kWh | Bestaand · ingeschakeld |
| `sensor.stalman_total_energy_today` | kWh | Bestaand · ingeschakeld |
| `sensor.stalman_total_output_power` | W | Bestaand · ingeschakeld |
| `sensor.stalman_woningvermogen` | W | Nieuw lokaal package |

## Nieuwe dagwaarden voor Overzicht

Deze entiteiten worden pas bij installatie van het bijgewerkte package aangemaakt.

| Entiteit | Eenheid | Berekening / bron |
|---|---|---|
| `sensor.stalman_import_vandaag` | kWh | Dagmeter: P1 import |
| `sensor.stalman_export_vandaag` | kWh | Dagmeter: P1 export |
| `sensor.stalman_zon_vandaag` | kWh | Dagmeter: Growatt levenslange productie |
| `sensor.stalman_bespaard_vandaag` | kWh | Dagmeter: Simulator bespaarde netafname |
| `sensor.stalman_geladen_vandaag` | kWh | Dagmeter: Simulator geladen energie |
| `sensor.stalman_huis_vandaag` | kWh | Import + zon − export, begrensd op nul |
| `sensor.stalman_batterijbesparing_vandaag` | EUR | Dagscenario, uitsluitend met bevestigde tarieven |

## Financiële revisie

| Entiteit | Eenheid | Bron |
|---|---|---|
| `sensor.stalman_financiele_vergelijking` | status | Lokale gecontroleerde financiële berekening |
| `sensor.stalman_kosten_zonder_batterij_vandaag` | EUR | Schatting op gemeten energie, maximaal 15 minuten oude invoer |
| `sensor.stalman_kosten_met_batterij_vandaag` | EUR | Simulatie op dezelfde meetperiode |

`stalman_batterijbesparing_vandaag` gebruikt nu het verschil tussen beide berekeningen; `stalman_besparingsscenario` toont uitsluitend een volledige afrekenperiode. De oude tariefhelpers zijn behouden voor compatibiliteit maar worden niet meer gebruikt voor geldberekeningen. Zie FINANCE.md.
