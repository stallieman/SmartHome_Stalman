# SmartHome Stalman

Docker-based Home Assistant configuration for a smart-home energy dashboard.

## Included

- Home Assistant Docker Compose service using host networking
- Core YAML configuration, automations, scripts, and scenes
- Energy dashboard source mappings
- Built-in Home Assistant automation and script blueprints

## Initial setup

1. Copy `config/secrets.example.yaml` to `config/secrets.yaml` and replace the example values.
2. Start Home Assistant:

   ```sh
   docker compose up -d
   ```

3. Open Home Assistant at `http://localhost:8123` and complete setup.

## Bring the container back up

Run all commands from the project directory:

```sh
cd /home/stallieman/containers/homeassistant
```

Check the current state:

```sh
docker compose ps --all
```

If the container is stopped or missing, create or start it in the background:

```sh
docker compose up -d
```

Wait a moment, then verify that its status is `Up`:

```sh
docker compose ps
```

Home Assistant should then be available at `http://localhost:8123`.

If the container is running but Home Assistant is not responding, restart it and follow its logs:

```sh
docker compose restart homeassistant
docker compose logs --tail=100 --follow homeassistant
```

Press `Ctrl-C` to stop following the logs; this does not stop the container. The Compose configuration uses `restart: unless-stopped`, so Docker will normally bring Home Assistant back after a reboot or unexpected failure.

The repository intentionally excludes credentials, certificates, databases, logs, and other machine-specific runtime state.

## Ring Camera's

Afzonderlijk mobile-first cameradashboard met standaardkaarten, livebeeld op verzoek,
bewegings- en deurbelgebeurtenissen en alleen bij lage batterij een waarschuwing.
Zie [gebruik en veilig deployen](docs/RING_DASHBOARD.md). Bestaande dashboards blijven behouden.

## Energie & Thuisbatterij · YAML-dashboard

Nieuw afzonderlijk donker dashboard met tabbladen Energie, Simulatie en Analyse.
Gebruikt uitsluitend ingebouwde kaarten; het bestaande dashboard blijft behouden.

Zie [installatie en beheer](docs/ENERGIE_DASHBOARD.md),
[gebruikte entiteiten](docs/ENTITIES.md) en [validatieresultaten](docs/VALIDATION.md).
Activatie op de server vereist afzonderlijke expliciete toestemming.

De [financiële handleiding](docs/FINANCE.md) beschrijft de Essent-contractinvoer,
jaarlijkse saldering, regels vanaf 2027 en de vergelijking met de virtuele batterij.
Onbevestigde contract- of meetgegevens blokkeren euro-uitkomsten.

De [intervalverzamelaar](docs/INTERVAL_COLLECTOR.md) koppelt P1- en simulatie-tellerstanden
zonder dubbeltellingen. Het aparte HA-package is lokaal voorbereid en nog niet geactiveerd.

Het [synchronisatieonderzoek](docs/BATTERY_SYNC.md) bevat een lokaal, standaard uitgeschakeld
auditvoorstel voor exacte simulatie-meetvensters, gevalideerd met een geïsoleerde HA-runtimeproef.
Het voorstel is niet geïnstalleerd en is niet klaar voor directe productie-installatie.

## AI-dagrapport

Afzonderlijke read-only dagtaak met lokale HA-statistiekaggregatie, optionele GPT-4.1-mini-analyse,
Telegram-fallback en een lokaal maandbudget van maximaal USD 0,50. Externe gegevensdeling vereist
expliciete selectie per sensor. Geen wijzigingen aan bestaande HA-automatiseringen of batterijberekeningen.
Zie [installatie, privacy en beperkingen](docs/AI_DAGRAPPORT.md). Niet live geïnstalleerd.
