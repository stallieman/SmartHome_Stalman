# AI-dagrapport — eerste versie

Losse, kortlopende Ubuntu-taak; geen HA-package, automation, extra container of database. Python 3.11+ en één dependency: `websocket-client`. De Windows-pc is niet nodig. Geen installatie of echte API-aanroep is tijdens ontwikkeling uitgevoerd.

## Werking en grenzen

1. Dagelijks rond 06:15 Europe/Amsterdam wordt gisteren uitgelezen, plus de dertig volledige kalenderdagen daarvoor. De timer draait niet op het dubbel/overgeslagen DST-uur. Een gemiste timer wordt na het starten ingehaald voor gisteren; oudere gemiste rapporten worden niet automatisch verstuurd.
2. De collector gebruikt uitsluitend de HA-WebSocket-leesopdrachten `get_states`, `recorder/list_statistic_ids` en `recorder/statistics_during_period`. Geen serviceaanroepen, state-wijzigingen, notificatieacties of configuratie-aanpassingen in HA.
3. Cumulatieve numerieke sensoren gebruiken uurlijkse statistiek-`change`, niet absolute tellerstanden. Numerieke metingen gebruiken het tijdgewogen daggemiddelde en min/max. Eenheden en elk verwacht uurbucket worden gecontroleerd. Kalenderdagen bevatten 23, 24 of 25 uur.
4. De 7-/30-daagse referentie sluit de rapportdag uit en vereist alle respectievelijke referentiedagen. Een ontbrekend of ongeldig bucket maakt de betreffende dag incompleet, niet nul. Voor nulreferenties volgt geen fictief percentage.
5. Een compacte lokale JSON-samenvatting wordt opgeslagen. Alleen sensoren met expliciet `share_with_ai: true` gaan naar OpenAI. Telegram heeft de afzonderlijke toestemming `share_with_telegram: true`. Beide staan in het voorbeeld **uit**.
6. GPT-4.1 mini selecteert maximaal vier patronen en voorzichtige controleadviezen. Patronen zijn vooraf lokaal berekend: meer dan tien procent boven/onder de 7-/30-daagse referentie, stabiel tegenover zeven dagen, of onvoldoende gegevens. Antwoorden zijn gestructureerde JSON; onbekende sensoren, ongefundeerde patronen en vrije tekst worden afgewezen. De leesbare Nederlandse formuleringen en alle getallen komen uit lokale code. Dit voorkomt verzonnen getallen/oorzaken, maar is bewust beperkter dan vrije AI-tekst.
7. Bij AI-uitval, ontbrekende OpenAI-key, tokenlimiet of onvoldoende budget wordt alleen het lokale cijferoverzicht verstuurd. Bij volledige HA-uitval worden waarden onbeschikbaar vermeld en wordt geen AI-kostenpost gemaakt. Als Telegram ontbreekt of uitstaat wordt geen nutteloze AI-aanvraag uitgevoerd.

Volledige uurbucketdekking bewijst niet dat een fysieke sensor voortdurend werkte: HA kan bij een stagnerende teller nog statistieken hebben. Deze eerste versie doet geen fijnmazige uptime-attestatie. Controleer sensorkwaliteit in HA. Er zijn geen causale conclusies, individuele apparaatidentificatie, financiële bedragen of batterijsimulatieberekeningen. De bestaande Marstek- en financiële bestanden blijven ongewijzigd.

Uitbreiden kan zonder Python-aanpassing: voeg een sensor aan de JSON toe met eigen alias, entity-ID, statistic-ID, label, eenheid en `kind` (`total_increasing` of `measurement`). Er vindt geen automatische externe publicatie van nieuw ontdekte entiteiten plaats. Niet-numerieke aanwezigheid/licht-/camera-events vereisen later een aparte aggregatie; beelden worden nooit verstuurd. Gebruik voor kWh bij voorkeur een levenslange teller, geen dagelijks resetbare zon-dagteller. De voorbeeld-ID's zijn de repositoryverwijzingen, geen bevestiging dat deze op de server nog geldig zijn.

## Kosten, betrouwbaarheid en opslag

- Vast model `gpt-4.1-mini`, zonder tools, webzoekopdrachten, conversatiehistorie of retrylus. Prijsbasis: USD 0,40/miljoen inputtokens en USD 1,60/miljoen outputtokens. Controleer deze bij installatie tegen de [officiële prijslijst](https://developers.openai.com/api/docs/pricing). Bij gewijzigde prijzen eerst constants in `daily.py` aanpassen; de lokale kostenraming is geen provider-side factuurlimiet.
- Standaard maximaal 6.000 conservatief geraamde inputtokens en 600 outputtokens. De volledige UTF-8-requestlengte plus framingmarge wordt als bovengrens voor input gereserveerd. Ook schema/instructies tellen mee. Grotere invoer leidt tot fallback, niet stilzwijgend verlies van sensoren. Bij 3.200 werkelijk gebruikte inputtokens en 500 outputtokens is dertig dagen circa USD 0,0624.
- Het lokale maandbudget is maximaal **USD 0,50**, berekend per kalendermaand in Amsterdam. De volledige maximale aanvraagkosten worden vóór verzending atomair gereserveerd. Geldige werkelijk gerapporteerde usage vervangt de reservering; bij timeout, onzekere usage of crash blijft de reservering staan. Er volgt maximaal één **poging** per uitvoeringskalenderdag (strikter dan één succes). Eerdere succesvolle analyse van dezelfde ongewijzigde input kan zonder nieuwe aanvraag worden hergebruikt.
- Eén bestandslock beschermt collectie, budget en verzending tegen gelijktijdige uitvoeringen. De status wordt met `fsync` en atomische vervanging vastgelegd. Bestanden zijn 0600, de servicestatusmap 0700. De service heeft geen schrijfrechten op de code of HA-configuratie.
- Telegram wordt zonder HTML/Markdown-parsemodus en zonder linkpreviews verstuurd, begrensd tot één kort bericht. Na bevestiging volgt geen dubbele verzending. Na een timeout/crash tijdens verzending kan niet worden vastgesteld of Telegram het bericht ontving: de status wordt `uncertain` of blijft `sending` en automatische herverzending stopt. Na een expliciete afwijzing mag een volgende handmatige start opnieuw verzenden, zonder nieuwe AI-kosten voor gecachte input. Er is geen automatische netwerkretry.
- `/var/lib/stalman-ai-analyst/state.json` bevat kostenreserveringen, echte tokenusage indien beschikbaar, AI-cache en verzendstatus. `summary-YYYY-MM-DD.json` bevat lokale meetaggregaten. Geen ruwe HA-attributen of sleutels worden bewaard. Maak een consistente backup wanneer de service niet actief is. **Wis of reset de status niet**: anders vervalt de lokale budget-/duplicaatadministratie. Bestaande rapporten zonder status of corrupte status blokkeren uitvoering. Ontbreken zowel status als rapporten, dan is verlies niet van een nieuwe installatie te onderscheiden; restore dus altijd de hele map.
- HA-token blijft uitsluitend in de collector; het model krijgt alleen geselecteerde aggregaten. De allowlist blokkeert schrijfacties vanuit deze toepassing. Een standaard niet-beheerderaccount is in HA niet automatisch server-side read-only; richt waar mogelijk een echt read-only permissiebeleid in. Deze applicatie maakt/wijzigt geen accounts of rollen.
- OpenAI gebruikt API-data standaard niet voor training. `store: false` is ingesteld, maar sluit tijdelijke abuse-monitoringretentie niet uit. Zie [gegevensbeleid](https://developers.openai.com/api/docs/guides/your-data). Ook Telegram ontvangt uitsluitend expliciet geselecteerde meetgegevens; gebruik bij voorkeur een privéchat.

## Installatie op Ubuntu — uitsluitend handmatig

Voer onderstaande stappen op de Ubuntu-host uit vanuit deze repository. Geen bestaande HA-bestanden vervangen en HA niet herstarten.

### 1. Account, Python en code

Als Python 3.11+ of venv ontbreekt, installeer die eerst via de gebruikelijke Ubuntu-beheerprocedure. De commands hieronder gebruiken `/usr/bin/python3`; controleer dat dit ten minste 3.11 is. Er wordt geen HA-omgeving aangepast.

```bash
/usr/bin/python3 --version
sudo useradd --system --user-group --home-dir /var/lib/stalman-ai-analyst --shell /usr/sbin/nologin stalman-ai
sudo install -d -m 0755 /opt/stalman-ai-analyst
sudo install -m 0644 config/ai_analyst/daily.py config/ai_analyst/ha.py config/ai_analyst/requirements.txt /opt/stalman-ai-analyst/
sudo /usr/bin/python3 -m venv /opt/stalman-ai-analyst/.venv
sudo /opt/stalman-ai-analyst/.venv/bin/python -m pip install -r /opt/stalman-ai-analyst/requirements.txt
sudo install -d -o stalman-ai -g stalman-ai -m 0700 /var/lib/stalman-ai-analyst
sudo install -o root -g stalman-ai -m 0640 config/ai_analyst/config.example.json /etc/stalman-ai-analyst.json
sudoedit /etc/stalman-ai-analyst.json
```

Bestaat het serviceaccount al, sla `useradd` over. Bij updates alleen de nieuwe code vervangen terwijl de service niet draait; overschrijf geen bestaande configuratie of status.

Configureer:

- `ha_url`: het bereikbare HA-basisadres. Op dezelfde Ubuntu-host met host-networking kan `http://127.0.0.1:8123` werken; bij andere hosts HTTPS gebruiken.
- Exacte entity-/statistic-ID's en eenheden volgens HA **Ontwikkelaarstools → Statistieken/Statussen**. Verwijder ongewenste sensoren. De repo bevat ook oudere P1-ID's met `energy` in plaats van `energie`; kies de werkelijk aanwezige ID's. Geen automatische gok/fallback.
- Zet per gewenste sensor afzonderlijk `share_with_ai` en/of `share_with_telegram` op `true`. Voor verzending moet minstens één sensor voor Telegram geselecteerd zijn. Selecteer geen persoonlijke gegevens die niet extern gedeeld mogen worden.
- Laat `timezone`, model en budget staan. Voor testen zonder AI mag `ai.enabled` op `false`.

### 2. Credentials buiten Git

Maak een apart HA-account/token met de minst mogelijke rechten. Een niet-beheerderaccount alleen is geen afgedwongen read-only rol; laat een HA-beheerder het passende beleid en de leestoegang op bovengenoemde drie commands verifiëren. Gebruik geen beheerdertoken als gemakkelijke vervanging. De code roept ongeacht tokenrechten geen schrijfopdrachten aan.

Maak een Telegram-bot via BotFather, start de privéchat met de bot en bepaal het numerieke chat-ID. Geen webhook, inkomende Telegram-commandos of HA-Telegram-integratie nodig. Configureer een aparte OpenAI-projectkey; schakel optionele gegevensdeling niet in.

```bash
sudo install -o root -g root -m 0600 /dev/null /etc/stalman-ai-analyst.env
sudoedit /etc/stalman-ai-analyst.env
```

Voer de volgende variabelen in met de echte waarden **alleen in dit lokale bestand**; geen `export`, geen spaties rond `=`, geen placeholders laten staan. Het bestand wordt door systemd als root gelezen en aan de service doorgegeven. Toon het niet in terminaloutput, commits of supportlogs.

```ini
HA_TOKEN=<apart-HA-token>
OPENAI_API_KEY=<OpenAI-projectkey>
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_CHAT_ID=<numeriek-chat-id>
```

OpenAI-key mag ontbreken wanneer bewust alleen fallback wordt gebruikt. HA-token is altijd nodig; Telegram-credentials zijn nodig zodra verzending aanstaat.

### 3. Eerst uitsluitend lokale validatie

Dit leest HA, schrijft lokale aggregaten en maakt **geen** OpenAI-/Telegram-aanroep. De transient unit voorkomt tokens in shellcommandos of procesargumenten.

```bash
sudo systemd-run --unit=stalman-ai-analyst-local --wait --pipe \
  --property=User=stalman-ai --property=Group=stalman-ai \
  --property=EnvironmentFile=/etc/stalman-ai-analyst.env \
  --property=StateDirectory=stalman-ai-analyst \
  --property=StateDirectoryMode=0700 --property=UMask=0077 \
  /opt/stalman-ai-analyst/.venv/bin/python /opt/stalman-ai-analyst/daily.py \
  --config /etc/stalman-ai-analyst.json --state-dir /var/lib/stalman-ai-analyst --local-only
```

Controleer lokaal de nieuwste `summary-*.json` in de statusmap: juiste rapportdag, gemeten eenheden, `quality`, beschikbare uurbuckets en referentiedagen. Niet-OK waarden worden niet verzonnen. Bij minder dan dertig dagen historie ontbreekt de 30-daagse vergelijking terecht. Deel deze bestanden niet ongeredigeerd.

### 4. Service testen en timer inschakelen

Een normale servicestart doet een echte Telegram-verzending en, indien toegestaan/beschikbaar, **één betaalde AI-aanvraag**. Zet voor een kosteloze Telegram-proef eerst `ai.enabled: false`; het bericht van die datum wordt daarna niet nogmaals verstuurd.

```bash
sudo install -m 0644 systemd/stalman-ai-analyst.service systemd/stalman-ai-analyst.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/stalman-ai-analyst.service /etc/systemd/system/stalman-ai-analyst.timer
sudo systemctl daemon-reload
sudo systemctl start stalman-ai-analyst.service
sudo journalctl -u stalman-ai-analyst.service --no-pager -n 30
sudo systemctl enable --now stalman-ai-analyst.timer
systemctl list-timers --all --no-pager stalman-ai-analyst.timer
```

De timer heeft `Persistent=true` en maximaal twee minuten spreiding. Na een storing kan handmatig opnieuw starten; er is geen automatische retrylus. Voor een historische proef ondersteunt de CLI `--date YYYY-MM-DD` (uitsluitend vóór vandaag); ook dan geldt de AI-limiet voor de **uitvoeringsdag**, en wordt de normale verzend-/budgetstatus bijgehouden. Bij twijfel over een onzekere Telegram-levering eerst de chat controleren en niet blind status wissen.

Stoppen zonder HA te beïnvloeden:

```bash
sudo systemctl disable --now stalman-ai-analyst.timer
```

Bewaar status/configuratie/credentials voor herstel; geen HA-restart of wijzigingen aan energie-/batterijpackages nodig.

## Offline tests

Alle externe API's worden gemockt. Vanuit de repository met de projectinterpreter:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_ai_*.py'
.venv/bin/python -m py_compile config/ai_analyst/daily.py config/ai_analyst/ha.py
```
