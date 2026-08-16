# SmartHome Stalman

Docker-based Home Assistant configuration for a smart-home energy dashboard.

## Included

- Home Assistant Docker Compose service using host networking
- Core YAML configuration, automations, scripts, and scenes
- Energy dashboard source mappings
- Built-in Home Assistant automation and script blueprints

## Run

1. Copy `config/secrets.example.yaml` to `config/secrets.yaml` and replace the example values.
2. Start Home Assistant:

   ```sh
   docker compose up -d
   ```

3. Open Home Assistant at `http://localhost:8123` and complete setup.

The repository intentionally excludes credentials, certificates, databases, logs, and other machine-specific runtime state.
