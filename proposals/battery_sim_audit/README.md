# Auditvoorstel — niet geïnstalleerd

Dit is een lokale, versiegebonden instrumentatievoorstel voor upstream Battery Simulator v2.9.0, commit `4cb396ff635f235787b42a51734ffef4168c330e`.

- `upstream-v2.9.0.patch`: kleine import-/decoratorwijzigingen; geen gewijzigde batterijmethod bodies.
- `stalman_audit.py`: begeleidende observatiehooks; geen batterijrekenmodel.
- `prepare_patch.py`: weigert onbekende bronhashes en schrijft uitsluitend een nieuwe afzonderlijke kopie.
- `LICENSE.upstream.txt`: MIT-licentie voor de upstream patchcontext.

Dit voorstel is niet klaar voor directe productie-installatie. Zie [onderzoeksrapport en beperkingen](../../docs/BATTERY_SYNC.md). Een geïsoleerde HA 2026.10.4-runtimeproef is lokaal geslaagd; dat installeert of activeert niets. Niets hier wordt automatisch door Home Assistant geladen.

Voor een afzonderlijke reviewkopie:

```sh
python3 proposals/battery_sim_audit/prepare_patch.py \
  --source /pad/naar/lokale-originele/__init__.py \
  --output /tmp/battery-sim-audit-review.py
```

Plaats deze uitvoer niet op de actieve server zonder afzonderlijke toestemming. Een volgende HACS-update kan private hooks vervangen; de hashbinding vereist dan een nieuwe beoordeling.
