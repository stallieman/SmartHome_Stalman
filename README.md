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
