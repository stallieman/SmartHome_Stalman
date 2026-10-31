"""Fail-closed, host-local deployment. No SSH, privilege escalation or image pulls."""
import sys
sys.dont_write_bytecode = True

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:23f4dfbb69ce76315dbc4de7915504f1c2dcecd7ca2648113a493a385972e133"
SOURCE = {
    "__init__.py": "a85306a06262e5d9ec27099b302dd5e9b24c0b3717ce0e547e30f3b381ce32b6",
    "sensor.py": "c6a137075d962c43fc88246ba078b81ce98269dbe2f7ae0379ba0cddad129724",
    "const.py": "c84a30d515e842897364b6a96b4ca1144932f278e24f91bef8e0f59a64932dbc",
    "helpers.py": "8d5bd7d6772cf9093798a3c383c1c0ec68a8f6d1f2da6d8a30e5b19623019b9e",
}
ENTRY = "01M678WZZ6M086SEWQ1QENFZ8Z"
PREFIX = "custom_components/battery_sim/"
CORE_FILES = ("collector.py", "batch_contract.py", "compare.py", "collector.json", "tariffs.json")
RESTORE_ROOT = Path("/root/.local/state/stalman-audit")
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
CONFIG_DIRECTORY_MODE = 0o755
CONFIG_FILE_MODE = 0o644
# HA Core 2026.10.4 writes CDN-fetched integration images here via
# hass.config.cache_path("brands"). Core defines .cache as temporary,
# regenerable data. This exception is only used for old-backup comparison.
REBUILDABLE_BACKUP_CACHE = PurePosixPath(".cache/brands/integrations")
RECORDER_DATABASE = "home-assistant_v2.db"
RECORDER_SIDECARS = frozenset({RECORDER_DATABASE + "-wal", RECORDER_DATABASE + "-shm"})
CURRENT_RUNTIME_FILES = frozenset({
    "home-assistant.log.fault",
    *RECORDER_SIDECARS,
})
SOURCE_COMPONENTS = {
    "__init__.py": "Battery simulator initializer",
    "sensor.py": "Battery simulator sensor module",
    "const.py": "Battery simulator constants module",
    "helpers.py": "Battery simulator helpers module",
}
MANAGED_COMPONENTS = {
    "configuration.yaml": "Home Assistant configuration",
    "packages/energie_thuisbatterij.yaml": "Energy package configuration",
    PREFIX + "__init__.py": "Battery simulator initializer",
    PREFIX + "stalman_audit.py": "Battery audit helper",
    "energy_finance/collector.py": "Energy collector module",
    "energy_finance/batch_contract.py": "Energy batch contract module",
    "energy_finance/compare.py": "Energy comparison module",
    "energy_finance/collector.json": "Energy collector policy",
    "energy_finance/tariffs.json": "Energy tariff policy",
    "packages/energie_audit_adapter.yaml": "Audit adapter package",
    "packages/energie_intervalcollector.yaml": "Interval collector package",
}


class Stop(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Stop(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require_regular_file(path, component):
    if path.is_symlink():
        raise Stop(f"{component}: symlink is not allowed.")
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise Stop(f"{component}: required file is missing.") from exc
    except PermissionError as exc:
        raise Stop(f"{component}: file metadata is unreadable.") from exc
    except OSError as exc:
        raise Stop(f"{component}: file metadata cannot be inspected.") from exc
    require(stat.S_ISREG(info.st_mode), f"{component}: expected a regular file, but found another file type.")


def open_regular(path, component):
    require_regular_file(path, component)
    try:
        return path.open("rb")
    except PermissionError as exc:
        raise Stop(f"{component}: file is unreadable.") from exc
    except OSError as exc:
        raise Stop(f"{component}: file cannot be opened safely.") from exc


def file_digest(path, component="Hash input"):
    value = hashlib.sha256()
    with open_regular(path, component) as stream:
        try:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
        except PermissionError as exc:
            raise Stop(f"{component}: file is unreadable.") from exc
        except OSError as exc:
            raise Stop(f"{component}: file cannot be read safely.") from exc
    return value.hexdigest()


def stream_digest(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def require_root(args):
    require(args.authorize_root, "Root execution requires --authorize-root; the script never invokes sudo itself.")
    require(os.geteuid() == 0, "Run this operation explicitly as root, for example via sudo.")


def identity(mode, uid=None, gid=None):
    return {"uid": os.geteuid() if uid is None else uid,
            "gid": os.getegid() if gid is None else gid, "mode": mode}


def require_metadata(path, expected, label):
    info = path.stat()
    require(info.st_uid == expected["uid"] and info.st_gid == expected["gid"]
            and stat.S_IMODE(info.st_mode) == expected["mode"], label)


def ensure_directory(path, info):
    missing = []
    current = path
    while not current.exists():
        require(not current.is_symlink(), "Destination directory must not be a symlink.")
        missing.append(current)
        current = current.parent
    require(current.is_dir() and not current.is_symlink(), "Destination parent must be a real directory.")
    for directory in reversed(missing):
        directory.mkdir(mode=info["mode"])
        os.chown(directory, info["uid"], info["gid"])
        os.chmod(directory, info["mode"])
    require(path.is_dir() and not path.is_symlink(), "Destination directory must be a real directory.")
    require_metadata(path, info, "Destination directory metadata differs from the approved policy.")


def manifest_digest(manifest):
    return digest(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())


def backup_comparison_manifest(manifest):
    def retained(name):
        path = PurePosixPath(name)
        return REBUILDABLE_BACKUP_CACHE not in path.parents
    return {name: value for name, value in manifest.items() if retained(name)}


def allowed_current_runtime_file(name, entry):
    if name not in CURRENT_RUNTIME_FILES or entry["type"] != "file":
        return False
    # HA opens this file at startup and removes it after a clean exit when empty.
    # Preserve and review actual fault output instead of classifying it as transient.
    if name == "home-assistant.log.fault":
        return entry["size"] == 0 and entry["sha256"] == digest(b"")
    # SQLite WAL may hold committed data not yet in the main DB; SHM is a
    # rebuildable index (sqlite.org/wal.html). Allow only extra live paths here,
    # never delete/checkpoint them or filter the complete stopped snapshot.
    return True


def filesystem_manifest(root):
    require(root.is_dir() and not root.is_symlink(), "Configuration root must be a real directory.")
    result = {".": {"type": "directory", "size": 0, "sha256": None}}

    def denied(error):
        raise Stop("Cannot read the complete configuration for backup comparison.") from error

    for parent, directories, files in os.walk(root, followlinks=False, onerror=denied):
        for name in directories:
            path = Path(parent) / name
            require(path.is_dir() and not path.is_symlink(), "Unsupported entry in configuration tree.")
            relative = path.relative_to(root).as_posix()
            result[relative] = {"type": "directory", "size": 0, "sha256": None}
        for name in files:
            path = Path(parent) / name
            require(path.is_file() and not path.is_symlink(), "Unsupported entry in configuration tree.")
            info = path.stat()
            result[path.relative_to(root).as_posix()] = {
                "type": "file", "size": info.st_size,
                "sha256": file_digest(path, "Current configuration member")}
    return result


def archive_manifest(path):
    members = []
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                name = PurePosixPath(member.name.removeprefix("./"))
                require(member.name and not name.is_absolute() and ".." not in name.parts
                        and not member.issym() and not member.islnk(),
                        "Backup contains unsafe member paths or links.")
                require(member.isfile() or member.isdir(), "Backup contains unsupported entry types.")
                members.append((name, member, archive.extractfile(member) if member.isfile() else None))
                if member.isfile():
                    require(members[-1][2] is not None, "Backup member cannot be read.")
                    members[-1] = (name, member, stream_digest(members[-1][2]))
        roots = {name.parent for name, member, value in members
                 if member.isfile() and name.name == "configuration.yaml" and name.parent.name == "config"}
        require(len(roots) == 1, "Backup must contain exactly one complete config root.")
        root = roots.pop()
        result = {}
        for name, member, value in members:
            if name == root:
                relative = "."
            elif root in name.parents:
                relative = name.relative_to(root).as_posix()
            else:
                require(member.isdir() and (name in root.parents), "Backup contains files outside the config root.")
                continue
            require(relative not in result, "Backup contains duplicate configuration paths.")
            result[relative] = {"type": "file" if member.isfile() else "directory",
                                "size": member.size if member.isfile() else 0,
                                "sha256": value if member.isfile() else None}
        require(result.get(".", {}).get("type") == "directory", "Backup config root is incomplete.")
        return result
    except PermissionError as exc:
        raise Stop("Confirmed backup is unreadable; backup validation failed.") from exc
    except (OSError, tarfile.TarError) as exc:
        raise Stop("Confirmed backup could not be read; backup validation failed.") from exc


def command(args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stop("Command unavailable or timed out; output suppressed.") from exc
    require(result.returncode == 0, "Command failed; output suppressed. Stop and review privately.")
    return result.stdout


def yaml_module():
    try:
        import yaml
    except ImportError as exc:
        raise Stop("PyYAML is required; no dependency is installed automatically.") from exc
    return yaml


def json_document(data, component):
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Stop(f"{component}: JSON parse failed.") from exc


def plain_yaml(data, component="YAML document"):
    yaml = yaml_module()
    try:
        return yaml.safe_load(data)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Stop(f"{component}: YAML parse failed.") from exc


def regular(path, component="Required input"):
    with open_regular(path, component) as stream:
        try:
            return stream.read()
        except PermissionError as exc:
            raise Stop(f"{component}: file is unreadable.") from exc
        except OSError as exc:
            raise Stop(f"{component}: file cannot be read safely.") from exc


def managed_component(relative):
    return MANAGED_COMPONENTS.get(relative, "Managed deployment file")


def safe_tree(root, require_readable=False):
    require(root.is_dir() and not root.is_symlink(), "Configuration root must be a real directory.")
    size = 0
    def denied(error):
        raise Stop("Cannot inspect complete configuration tree.") from error
    for parent, directories, files in os.walk(root, followlinks=False, onerror=denied):
        for name in directories + files:
            path = Path(parent) / name
            require(not path.is_symlink(), "Symlink in configuration; review required.")
            info = path.stat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "Special file in configuration.")
            if stat.S_ISDIR(info.st_mode):
                require(os.access(path, os.R_OK | os.X_OK), "Unreadable configuration directory.")
            if stat.S_ISREG(info.st_mode):
                if require_readable:
                    require(os.access(path, os.R_OK), "Unreadable configuration file; backup impossible.")
                size += info.st_size
    return size


def writable(path):
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    require(not parent.is_symlink(), "Destination parent must not be a symlink.")
    info = parent.stat()
    groups = {*os.getgroups(), os.getegid()}
    can_write = (os.geteuid() == 0 or
                 (info.st_uid == os.geteuid() and info.st_mode & stat.S_IWUSR) or
                 (info.st_gid in groups and info.st_mode & stat.S_IWGRP) or
                 info.st_mode & stat.S_IWOTH)
    can_search = (os.geteuid() == 0 or
                  (info.st_uid == os.geteuid() and info.st_mode & stat.S_IXUSR) or
                  (info.st_gid in groups and info.st_mode & stat.S_IXGRP) or
                  info.st_mode & stat.S_IXOTH)
    require(can_write and can_search, "Destination parent permissions do not allow writes.")
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), "Destination must be a regular, non-symlink file.")
        info = path.stat()
        if os.geteuid() != 0:
            require(info.st_uid == os.geteuid() and info.st_gid in {*os.getgroups(), os.getegid()},
                    "Cannot preserve destination ownership with current rights.")


def verify_writable(path):
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    fd, probe = tempfile.mkstemp(prefix=".audit-write-check-", dir=parent)
    try:
        info = path.stat() if path.exists() else None
        if info:
            os.fchown(fd, info.st_uid, info.st_gid)
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(b"probe")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
        os.unlink(probe)


def container(args, running=True):
    output = command(["docker", "inspect", "--format",
                      "{{json .State.Running}}\n{{json .Image}}\n{{json .Mounts}}", args.container])
    lines = output.decode().splitlines()
    require(len(lines) == 3, "Unexpected container inspection response.")
    actual_running = json.loads(lines[0])
    require((running is None or actual_running is running) and json.loads(lines[1]) == IMAGE,
            "Unexpected container state or image ID.")
    mounts = [m for m in json.loads(lines[2]) if m.get("Destination") == "/config"]
    require(len(mounts) == 1 and mounts[0].get("Type") == "bind" and mounts[0].get("RW") is True
            and Path(mounts[0]["Source"]).resolve() == args.config, "Unexpected /config mount.")
    runtime = json.loads(command(["docker", "image", "inspect", "--format",
                                  '{"os":"{{.Os}}","arch":"{{.Architecture}}"}', IMAGE]))
    require(runtime == {"os": "linux", "arch": "arm64"}, "Unexpected image architecture.")
    return actual_running


def runtime_check(args, require_running=None):
    running = container(args, running=require_running)
    if running:
        dependencies = json.loads(command(["docker", "exec", args.container, "python3", "-B", "-c",
            "import json,os,sqlite3,zoneinfo;from homeassistant.const import __version__;"
            "print(json.dumps({'version':__version__,'uid':os.geteuid()}))"]))
        require(dependencies["version"] == "2026.10.4" and dependencies["uid"] in (0, os.geteuid()),
                "Unexpected runtime version or file-access identity.")
    return running


def battery(root):
    component = "Home Assistant storage metadata"
    data = json_document(regular(root / ".storage/core.config_entries", component), component)
    try:
        entries = [e for e in data["data"]["entries"] if e.get("domain") == "battery_sim"]
        require(len(entries) == 1 and entries[0].get("entry_id") == ENTRY, "Unexpected battery binding.")
        entry = entries[0]
        values = entry["data"]
        expected = {"size_kwh": 5.12, "max_charge_rate_kw": 2.5, "max_discharge_rate_kw": .8,
                    "charge_efficiency": .91, "discharge_efficiency": .91, "update_frequency": 60}
        require(all(values.get(k) == v for k, v in expected.items()) and not entry.get("options"),
                "Battery settings differ from approved Marstek configuration.")
        require(not values.get("solar_entity_id") and not values.get("solar_energy_sensor"),
                "Additional solar input unsupported.")
        inputs = values.get("input_list", [])
        require(len(inputs) == 2, "Unexpected source count.")
        for role in ("import", "export"):
            matches = [i for i in inputs if i.get("sensor_type") == role.title()]
            require(len(matches) == 1 and matches[0].get("sensor_id") == f"sensor.p1_meter_energie_{role}"
                    and matches[0].get("simulated_sensor") == f"simulated_sensor.p1_meter_energie_{role}"
                    and matches[0].get("tariff_type") == "No tariff information",
                    "Unexpected P1 source configuration.")
    except (AttributeError, KeyError, TypeError) as exc:
        raise Stop(f"{component}: unexpected JSON structure.") from exc
    return digest(json.dumps(entry, sort_keys=True).encode())


def backup_check(path, root):
    component = "Confirmed backup archive"
    require_regular_file(path, component)
    required = {"configuration.yaml", ".storage/core.config_entries", "packages/energie_thuisbatterij.yaml",
                *[PREFIX + name for name in SOURCE]}
    try:
        archive_hash = file_digest(path, component)
        archived = archive_manifest(path)
        current = filesystem_manifest(root)
    except PermissionError as exc:
        raise Stop("Confirmed backup is unreadable; backup validation failed.") from exc
    except OSError as exc:
        raise Stop("Confirmed backup could not be read; backup validation failed.") from exc
    archived_comparison = backup_comparison_manifest(archived)
    current_comparison = backup_comparison_manifest(current)
    archived_names = set(archived_comparison)
    current_names = set(current_comparison)
    for manifest in (archived, current):
        database = manifest.get(RECORDER_DATABASE)
        require(database is not None and database["type"] == "file" and database["size"] > 0
                and bool(database["sha256"]), "Recorder main database is missing or invalid.")
    fault_log = current.get("home-assistant.log.fault")
    require(fault_log is None or allowed_current_runtime_file("home-assistant.log.fault", fault_log),
            "Current Home Assistant fault log is not empty; review it before deployment.")
    require(RECORDER_SIDECARS.isdisjoint(archived_names),
            "Stopped backup unexpectedly contains Recorder WAL runtime sidecars.")
    added_while_running = current_names - archived_names
    require(not (archived_names - current_names)
            and all(allowed_current_runtime_file(name, current_comparison[name])
                    for name in added_while_running),
            "Backup manifest does not cover the complete current configuration.")
    require(RECORDER_DATABASE + "-shm" not in added_while_running
            or RECORDER_DATABASE + "-wal" in current_names,
            "Recorder shared-memory sidecar exists without its WAL.")
    require(all(archived_comparison[name]["type"] == current_comparison[name]["type"]
                for name in archived_names & current_names),
            "Backup manifest contains different configuration entry types.")
    require(required <= set(archived), "Backup is missing required original configuration members.")
    require(all(archived[name] == current[name] for name in required),
            "Backup differs from current deployment-critical configuration; create a current backup.")
    require(all(archived[PREFIX + name]["sha256"] == expected for name, expected in SOURCE.items()),
            "Backup source differs from approved original.")
    return {"sha256": archive_hash, "manifest_sha256": manifest_digest(archived), "entries": len(archived)}


def transform(source):
    component = "Repository patch transformer"
    path = ROOT / "proposals/battery_sim_audit/prepare_patch.py"
    module = type(sys)("audit_prepare")
    try:
        exec(compile(regular(path, component), str(path), "exec"), module.__dict__)
        return module.transform(source).encode()
    except (KeyError, SyntaxError, UnicodeError, ValueError) as exc:
        raise Stop(f"{component}: source transformation failed validation.") from exc


def add_includes(raw):
    component = "Home Assistant configuration"
    yaml = yaml_module()
    try:
        node = yaml.compose(raw)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise Stop(f"{component}: YAML parse failed.") from exc
    def mapping(item, name):
        require(isinstance(item, yaml.MappingNode), "Expected block YAML mapping.")
        matches = [v for k, v in item.value if k.value == name]
        require(len(matches) == 1, "Expected one existing package mapping.")
        return matches[0]
    packages = mapping(mapping(node, "homeassistant"), "packages")
    require(isinstance(packages, yaml.MappingNode) and not packages.flow_style, "Package includes must use block mapping.")
    require(all(k.value not in ("stalman_audit", "stalman_intervalcollector") for k, v in packages.value),
            "Audit package registration already exists.")
    require(any(k.value == "stalman_energie" and v.tag == "!include"
                and v.value == "packages/energie_thuisbatterij.yaml" for k, v in packages.value),
            "Unexpected existing energy package include.")
    try:
        lines = raw.decode().splitlines(keepends=True)
    except UnicodeDecodeError as exc:
        raise Stop(f"{component}: YAML text is not valid UTF-8.") from exc
    indent = " " * packages.value[0][0].start_mark.column
    end = packages.value[-1][1].end_mark.line + 1
    lines[end:end] = [f"{indent}stalman_audit: !include packages/energie_audit_adapter.yaml\n",
                      f"{indent}stalman_intervalcollector: !include packages/energie_intervalcollector.yaml\n"]
    result = "".join(lines).encode()
    try:
        yaml.compose(result)
    except yaml.YAMLError as exc:
        raise Stop(f"{component}: generated YAML parse failed.") from exc
    return result


def candidate(args):
    root = args.config
    files = {}
    initializer = "Battery simulator initializer"
    original = regular(root / (PREFIX + "__init__.py"), initializer)
    files[PREFIX + "__init__.py"] = transform(original)
    files[PREFIX + "stalman_audit.py"] = regular(
        ROOT / "proposals/battery_sim_audit/stalman_audit.py", "Repository battery audit helper")
    for name in CORE_FILES:
        relative = "energy_finance/" + name
        files[relative] = regular(ROOT / "config/energy_finance" / name, managed_component(relative))
    policy_component = "Energy collector policy"
    policy = json_document(files["energy_finance/collector.json"], policy_component)
    try:
        require(policy["audit"]["enabled"] is False and policy["audit"]["battery_id"] == ENTRY
                and policy["audit"]["expected_helper_sha256"] == digest(files[PREFIX + "stalman_audit.py"]),
                "Unexpected repository audit policy.")
        # Audit-only collection is approved by --apply; contract/monetary activation stays off.
        policy["audit"]["enabled"] = True
    except (AttributeError, KeyError, TypeError) as exc:
        raise Stop(f"{policy_component}: unexpected JSON structure.") from exc
    files["energy_finance/collector.json"] = (json.dumps(policy, indent=2) + "\n").encode()
    tariff_component = "Energy tariff policy"
    tariffs = json_document(files["energy_finance/tariffs.json"], tariff_component)
    try:
        require(all(p.get("confirmed") is False for p in tariffs["plans"])
                and tariffs["fixed_daily_costs"].get("confirmed") is False,
                "Financial activation is not allowed.")
    except (AttributeError, KeyError, TypeError) as exc:
        raise Stop(f"{tariff_component}: unexpected JSON structure.") from exc
    for name in ("energie_audit_adapter.yaml", "energie_intervalcollector.yaml"):
        relative = "packages/" + name
        files[relative] = regular(ROOT / "config/packages" / name, managed_component(relative))
    config_component = "Home Assistant configuration"
    files["configuration.yaml"] = add_includes(regular(root / "configuration.yaml", config_component))
    yaml = yaml_module()
    package_component = "Active energy package"
    planned_component = "Repository energy package"
    current = plain_yaml(regular(root / "packages/energie_thuisbatterij.yaml", package_component),
                         package_component)
    planned = plain_yaml(regular(ROOT / "config/packages/energie_thuisbatterij.yaml", planned_component),
                         planned_component)
    require(isinstance(current, dict) and "command_line" not in current,
            "Unexpected existing financial command sensor.")
    try:
        sensors = {s["unique_id"]: s for block in planned["template"] for s in block.get("sensor", [])
                   if s.get("device_class") == "monetary"}
        for block in current.get("template", []):
            for index, sensor in enumerate(block.get("sensor", [])):
                key = sensor.get("unique_id")
                if key in sensors:
                    block["sensor"][index] = sensors.pop(key)
        current.setdefault("template", []).append({"sensor": list(sensors.values())})
        current["command_line"] = planned["command_line"]
    except (AttributeError, KeyError, TypeError) as exc:
        raise Stop("Energy package candidate: unexpected YAML structure.") from exc
    files["packages/energie_thuisbatterij.yaml"] = yaml.safe_dump(current, allow_unicode=True, sort_keys=False).encode()
    for relative in files:
        if relative not in ("configuration.yaml", "packages/energie_thuisbatterij.yaml", PREFIX + "__init__.py"):
            require(not (root / relative).exists(), "New deployment path already exists; no overwrite allowed.")
    require(not (root / "energy_finance").exists(), "Financial runtime directory already exists.")
    return files


def metadata(path, component="Managed deployment file"):
    if not path.exists() and not path.is_symlink():
        return None
    data = regular(path, component)
    info = path.stat()
    return {"sha256": digest(data), "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}


def atomic(path, data, info, directory_info=None):
    require(info is not None, "Destination file metadata policy is required.")
    if not path.parent.exists():
        require(directory_info is not None, "Destination directory metadata policy is required.")
        ensure_directory(path.parent, directory_info)
    fd, temporary = tempfile.mkstemp(prefix=".audit-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), info["uid"], info["gid"])
            os.fchmod(stream.fileno(), info["mode"])
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def open_lock(path, file_info, directory_info):
    if not path.parent.exists():
        ensure_directory(path.parent, directory_info)
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), "Deployment lock must be a regular file.")
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                         file_info["mode"])
    os.fchown(descriptor, file_info["uid"], file_info["gid"])
    os.fchmod(descriptor, file_info["mode"])
    require_metadata(path, file_info, "Deployment lock metadata differs from the approved policy.")
    return os.fdopen(descriptor, "a+")


def create_snapshot(config, destination, private_file, private_directory):
    ensure_directory(destination.parent, private_directory)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                         private_file["mode"])
    try:
        os.fchown(descriptor, private_file["uid"], private_file["gid"])
        os.fchmod(descriptor, private_file["mode"])
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                archive.add(config, arcname="config")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    require_metadata(destination, private_file, "Restore snapshot metadata differs from the approved policy.")
    snapshot_manifest = archive_manifest(destination)
    current_manifest = filesystem_manifest(config)
    require(snapshot_manifest == current_manifest,
            "Stopped configuration changed while creating the restore snapshot.")
    return {"sha256": file_digest(destination, "Restore snapshot archive"),
            "manifest_sha256": manifest_digest(snapshot_manifest), "entries": len(snapshot_manifest)}


def validate_private_tree(root, file_info, directory_info):
    require_metadata(root, directory_info, "Restore point must be private and owned by root.")
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            path = Path(parent) / name
            require(path.is_dir() and not path.is_symlink(), "Unsafe restore-point directory.")
            require_metadata(path, directory_info, "Restore-point directory metadata is unsafe.")
        for name in files:
            path = Path(parent) / name
            require(path.is_file() and not path.is_symlink(), "Unsafe restore-point file.")
            require_metadata(path, file_info, "Restore-point file metadata is unsafe.")


def check_config(stage):
    command(["docker", "run", "--rm", "--pull=never", "--network", "none", "--read-only",
             "--tmpfs", "/tmp", "--tmpfs", "/run", "-v", f"{stage}:/config:rw",
             "--entrypoint", "python3", IMAGE, "-m", "homeassistant", "--script", "check_config",
             "--config", "/config"], timeout=180)


def health(args):
    probe = """import json,sqlite3
from pathlib import Path
p=Path('/config/energy_finance')
if not (p/'intervals.sqlite').exists() or not (p/'observations.json').exists():
 print(json.dumps({'audit':False}));raise SystemExit(0)
c=sqlite3.connect('file:'+str(p/'intervals.sqlite')+'?mode=ro',uri=True)
r=c.execute('SELECT payload FROM audit_packets_v1 ORDER BY end_ts DESC LIMIT 1').fetchone()
b=json.loads(r[0]) if r else {}
o=json.loads((p/'observations.json').read_text())
print(json.dumps({'audit':bool(b.get('valid')),'sequence':b.get('sequence',0),'paired':o.get('paired_grid_deltas_confirmed') is True}))
"""
    deadline = time.monotonic() + args.health_timeout
    while True:
        container(args)
        result = json.loads(command(["docker", "exec", args.container, "python3", "-B", "-c", probe], timeout=15))
        if result.get("audit") and result.get("sequence", 0) > 0 and result.get("paired"):
            require(battery(args.config) == args.battery_fingerprint, "Battery settings changed during deployment.")
            require(all(file_digest(args.config / PREFIX / n, SOURCE_COMPONENTS[n]) == value
                        for n, value in SOURCE.items() if n != "__init__.py"),
                    "Supporting source changed during deployment.")
            component = "Installed energy tariff policy"
            tariffs = json_document(regular(args.config / "energy_finance/tariffs.json", component), component)
            require(all(p.get("confirmed") is False for p in tariffs["plans"]), "Unexpected monetary activation.")
            return
        require(time.monotonic() < deadline, "Audit health not proven. Stop; use explicit rollback after review.")
        time.sleep(5)


def wait_core(args):
    probe = """import json,urllib.request,urllib.error
try:
 r=urllib.request.urlopen('http://127.0.0.1:8123/',timeout=3)
 print(json.dumps({'ready':r.status==200}))
except (urllib.error.URLError,TimeoutError):
 print(json.dumps({'ready':False}))
"""
    deadline = time.monotonic() + args.health_timeout
    while True:
        container(args)
        if json.loads(command(["docker", "exec", args.container, "python3", "-B", "-c", probe], timeout=10)).get("ready"):
            return
        require(time.monotonic() < deadline, "Core HTTP readiness not proven; stop for review.")
        time.sleep(5)


def preflight(args, files=None, require_readable=False):
    version = regular(args.config / ".HA_VERSION", "Home Assistant version marker")
    require(version.strip() == b"2026.10.4", "Unexpected HA configuration version.")
    size = safe_tree(args.config, require_readable=require_readable)
    args.battery_fingerprint = battery(args.config)
    required = max(1024 ** 3, 3 * size + 256 * 1024 ** 2)
    storage = getattr(args, "restore_point", None) or args.restore_root
    while not storage.exists():
        storage = storage.parent
    require(all(shutil.disk_usage(path).free >= required for path in (args.config, storage)),
            "Insufficient space for staging and restore point.")
    if files:
        for relative in files:
            writable(args.config / relative)


def capture_files(root, names):
    snapshot = {}
    for name in names:
        path = root / name
        component = managed_component(name)
        info = metadata(path, component)
        snapshot[name] = None if info is None else {"info": info, "data": regular(path, component)}
    return snapshot


def restore_files(root, snapshot, allowed_hashes, directory_info):
    for name, state in snapshot.items():
        current = metadata(root / name)
        current_hash = current["sha256"] if current else None
        require(current_hash in allowed_hashes[name], "Managed file drift prevents automatic recovery.")
    for name, state in snapshot.items():
        path = root / name
        if state is None:
            if path.exists() or path.is_symlink():
                require(path.is_file() and not path.is_symlink(), "Refusing to remove a non-regular recovery target.")
                path.unlink()
        else:
            atomic(path, state["data"], state["info"], directory_info)


def allow_hashes(*snapshots):
    result = {}
    for snapshot in snapshots:
        for name, state in snapshot.items():
            result.setdefault(name, set()).add(state["info"]["sha256"] if state else None)
    return result


def ensure_running(args, desired):
    current = container(args, running=None)
    if current != desired:
        command(["docker", "start" if desired else "stop", args.container])
    container(args, running=desired)


def recover_transaction(args, was_running, snapshot, allowed, restore_changes, directory_info):
    if not restore_changes:
        if was_running:
            ensure_running(args, True)
        return
    try:
        current = container(args, running=None)
        if current:
            command(["docker", "stop", "--time", "-1", args.container], timeout=180)
            container(args, running=False)
        if restore_changes:
            restore_files(args.config, snapshot, allowed, directory_info)
    except BaseException as recovery_error:
        try:
            if was_running:
                ensure_running(args, True)
        except BaseException:
            pass
        raise Stop("Automatic recovery was incomplete; inspect the container and managed files before proceeding.") from recovery_error
    if was_running:
        ensure_running(args, True)


def install(args):
    require_root(args)
    require(args.restore_root == RESTORE_ROOT, "Use the fixed private restore root /root/.local/state/stalman-audit.")
    preflight(args, require_readable=args.apply)
    for name, expected in SOURCE.items():
        component = SOURCE_COMPONENTS[name]
        require(digest(regular(args.config / PREFIX / name, component)) == expected,
                f"{component}: installed source hash mismatch.")
    backup_evidence = backup_check(args.backup, args.config)
    original_inputs = {n: metadata(args.config / n, managed_component(n)) for n in
                       ("configuration.yaml", "packages/energie_thuisbatterij.yaml", PREFIX + "__init__.py")}
    files = candidate(args)
    require(all(metadata(args.config / n, managed_component(n)) == v for n, v in original_inputs.items()),
            "Files changed while building candidate.")
    require(args.restore_root.is_absolute() and args.restore_root.resolve() == args.restore_root
            and not args.restore_root.is_relative_to(args.config) and not args.restore_root.is_relative_to(ROOT),
            "Restore root must be a real path outside /config and the source repository.")
    owner = metadata(args.config / "configuration.yaml", "Home Assistant configuration")
    config_file = identity(CONFIG_FILE_MODE, owner["uid"], owner["gid"])
    config_directory = identity(CONFIG_DIRECTORY_MODE, owner["uid"], owner["gid"])
    private_file = identity(PRIVATE_FILE_MODE)
    private_directory = identity(PRIVATE_DIRECTORY_MODE)
    writable(args.restore_root / ".probe")
    if args.restore_root.exists():
        require_metadata(args.restore_root, private_directory,
                         "Restore root must be private and owned by root.")
    preflight(args, files, require_readable=args.apply)
    before = {name: metadata(args.config / name, managed_component(name)) for name in files}
    planned = {name: state if state is not None else config_file for name, state in before.items()}
    if not args.apply:
        print(f"DRY-RUN: preflight passed; {len(files)} files planned. No writes, stop, validation container or restart.")
        return
    require(args.authorize_runtime_check, "--apply requires --authorize-runtime-check for the separate runtime preflight.")
    for relative in files:
        verify_writable(args.config / relative)
    verify_writable(args.restore_root / ".probe")
    runtime_check(args, require_running=True)
    ensure_directory(args.restore_root, private_directory)
    with open_lock(args.restore_root / ".deployment.lock", private_file, private_directory) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(args, files)
        require(all(metadata(args.config / n, managed_component(n)) == v for n, v in before.items()),
                "Configuration changed during preflight.")
        point = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=args.restore_root))
        os.chown(point, private_directory["uid"], private_directory["gid"])
        os.chmod(point, private_directory["mode"])
        require_metadata(point, private_directory, "Restore point metadata differs from the approved policy.")
        print("Private restore point:", point)
        original_files = capture_files(args.config, files)
        after_hashes = {name: {digest(data)} for name, data in files.items()}
        recovery_hashes = allow_hashes(original_files)
        for name, hashes in after_hashes.items():
            recovery_hashes[name].update(hashes)
        stage = point / "stage"
        shutil.copytree(args.config, stage)
        for name, data in files.items():
            atomic(stage / name, data, planned[name], config_directory)
        check_config(stage)
        shutil.rmtree(stage)
        changed = False
        was_running = True
        manifest = None
        try:
            command(["docker", "stop", "--time", "-1", args.container], timeout=180)
            container(args, running=False)
            require(all(file_digest(args.config / PREFIX / n, SOURCE_COMPONENTS[n]) == value
                        for n, value in SOURCE.items()), "Source changed during staging.")
            require(battery(args.config) == args.battery_fingerprint, "Battery configuration changed at shutdown.")
            require(all(metadata(args.config / n, managed_component(n)) == v for n, v in before.items()),
                    "Deployment files changed at shutdown.")
            snapshot = point / "configuration.tar.gz"
            snapshot_evidence = create_snapshot(args.config, snapshot, private_file, private_directory)
            for name, state in original_files.items():
                if state:
                    atomic(point / "originals" / name, state["data"], private_file, private_directory)
            manifest = {"config": str(args.config), "image": IMAGE, "container": args.container,
                        "battery": args.battery_fingerprint, "backup": backup_evidence,
                        "snapshot": snapshot_evidence, "before": before,
                        "after": {n: digest(data) for n, data in files.items()}, "phase": "prepared"}
            atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                   private_file, private_directory)
            changed = True
            for name, data in files.items():
                atomic(args.config / name, data, planned[name], config_directory)
            manifest["phase"] = "installed"
            atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                   private_file, private_directory)
            command(["docker", "start", args.container])
            wait_core(args)
            health(args)
            manifest["phase"] = "validated"
            atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                   private_file, private_directory)
            print("PASS: audit-only installed and observed; monetary activation remains disabled.")
        except BaseException as original_error:
            try:
                recover_transaction(args, was_running, original_files, recovery_hashes, changed, config_directory)
            except BaseException as recovery_error:
                raise Stop("Installation failed and automatic recovery was incomplete; inspect the saved restore point and container.") from recovery_error
            if manifest is not None:
                manifest["phase"] = "recovered"
                try:
                    atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                           private_file, private_directory)
                except BaseException as manifest_error:
                    raise Stop("Files and container were recovered, but restore-point metadata needs review.") from manifest_error
            raise original_error


def rollback(args):
    require_root(args)
    require(args.restore_root == RESTORE_ROOT, "Use the fixed private restore root /root/.local/state/stalman-audit.")
    point = args.restore_point
    private_file = identity(PRIVATE_FILE_MODE)
    private_directory = identity(PRIVATE_DIRECTORY_MODE)
    require(point.is_absolute() and point.resolve() == point and point.is_dir() and not point.is_symlink()
            and point.stat().st_uid == os.geteuid() and stat.S_IMODE(point.stat().st_mode) == 0o700
            and point.parent.stat().st_uid == os.geteuid() and stat.S_IMODE(point.parent.stat().st_mode) == 0o700,
            "Restore point and its deployment root must be private and owned by root.")
    validate_private_tree(point, private_file, private_directory)
    manifest_component = "Restore-point manifest"
    manifest = json_document(regular(point / "manifest.json", manifest_component), manifest_component)
    require(manifest["config"] == str(args.config) and manifest["image"] == IMAGE
            and manifest["container"] == args.container and manifest["phase"] in ("prepared", "installed", "validated"),
            "Restore point is not applicable.")
    preflight(args)
    require(args.battery_fingerprint == manifest["battery"], "Battery configuration changed; manual review required.")
    snapshot_manifest = archive_manifest(point / "configuration.tar.gz")
    require(file_digest(point / "configuration.tar.gz", "Restore snapshot archive")
            == manifest["snapshot"]["sha256"]
            and manifest_digest(snapshot_manifest) == manifest["snapshot"]["manifest_sha256"]
            and len(snapshot_manifest) == manifest["snapshot"]["entries"], "Restore snapshot is damaged.")
    allowed = {"configuration.yaml", "packages/energie_thuisbatterij.yaml",
               "packages/energie_audit_adapter.yaml", "packages/energie_intervalcollector.yaml",
               PREFIX + "__init__.py", PREFIX + "stalman_audit.py",
               *["energy_finance/" + n for n in CORE_FILES]}
    require(set(manifest["before"]) == set(manifest["after"]) == allowed, "Unexpected managed restore files.")
    owner = metadata(args.config / "configuration.yaml", "Home Assistant configuration")
    config_directory = identity(CONFIG_DIRECTORY_MODE, owner["uid"], owner["gid"])
    files = {}
    for name, info in manifest["before"].items():
        require(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts,
                "Unsafe restore path.")
        writable(args.config / name)
        current = metadata(args.config / name, managed_component(name))
        require((current is None and info is None) or (current is not None and current["sha256"] in
                (manifest["after"][name], (info or {}).get("sha256"))),
                "Installed file drift; rollback would overwrite another change.")
        if info:
            data = regular(point / "originals" / name, "Saved original " + managed_component(name))
            require(digest(data) == info["sha256"], "Original restore file is damaged.")
            files[name] = data
    if not args.apply:
        print("DRY-RUN: rollback preflight passed. No files changed or container restarted.")
        return
    require(args.authorize_runtime_check, "--apply requires --authorize-runtime-check for the separate runtime preflight.")
    for name in manifest["before"]:
        verify_writable(args.config / name)
    verify_writable(point.parent / ".deployment.lock")
    verify_writable(point / ".rollback-probe")
    running = runtime_check(args, require_running=None)
    observed_files = capture_files(args.config, manifest["before"])
    rollback_files = {
        name: None if info is None else {"info": info, "data": files[name]}
        for name, info in manifest["before"].items()
    }
    recovery_hashes = allow_hashes(observed_files, rollback_files)
    original_phase = manifest["phase"]
    with open_lock(point.parent / ".deployment.lock", private_file, private_directory) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        changed = False
        try:
            with tempfile.TemporaryDirectory(prefix="rollback-check-", dir=point) as temporary:
                stage = Path(temporary) / "config"
                shutil.copytree(args.config, stage)
                for name, info in manifest["before"].items():
                    if info:
                        atomic(stage / name, files[name], info, config_directory)
                    elif (stage / name).exists():
                        (stage / name).unlink()
                check_config(stage)
            require(all(metadata(args.config / n, managed_component(n)) == observed_files[n]["info"]
                        if observed_files[n] else metadata(args.config / n, managed_component(n)) is None
                        for n in observed_files),
                    "Files changed during rollback validation.")
            if running:
                command(["docker", "stop", "--time", "-1", args.container], timeout=180)
                container(args, running=False)
            require(battery(args.config) == manifest["battery"], "Battery configuration changed at rollback shutdown.")
            changed = True
            restore_files(args.config, rollback_files, recovery_hashes, config_directory)
            if running:
                command(["docker", "start", args.container])
                wait_core(args)
                container(args)
                require(battery(args.config) == manifest["battery"],
                        "Battery binding/settings differ after rollback.")
            manifest["phase"] = "rolled_back"
            atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                   private_file, private_directory)
            print("PASS: original managed files restored; runtime databases and .storage were not overwritten.")
        except BaseException as original_error:
            try:
                recover_transaction(args, running, observed_files, recovery_hashes, changed, config_directory)
            except BaseException as recovery_error:
                raise Stop("Rollback failed and automatic recovery was incomplete; inspect the saved restore point and container.") from recovery_error
            if manifest["phase"] != original_phase:
                manifest["phase"] = original_phase
                try:
                    atomic(point / "manifest.json", json.dumps(manifest, indent=2).encode(),
                           private_file, private_directory)
                except BaseException as manifest_error:
                    raise Stop("Rollback state was recovered, but restore-point metadata needs review.") from manifest_error
            raise original_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "rollback", "runtime-check"))
    parser.add_argument("--apply", action="store_true", help="Explicitly allow writes and the controlled container stop/start")
    parser.add_argument("--authorize-root", action="store_true",
                        help="Acknowledge explicit root execution; this script never invokes sudo")
    parser.add_argument("--authorize-runtime-check", action="store_true",
                        help="Explicitly authorize read-only Docker inspection and runtime checks")
    parser.add_argument("--config", type=Path, default=Path("/home/stallieman/SmartHome_Stalman/config"))
    parser.add_argument("--container", default="homeassistant")
    parser.add_argument("--backup", type=Path, default=Path("/home/stallieman/homeassistant-backup-20261031.tar.gz"))
    parser.add_argument("--restore-root", type=Path, default=RESTORE_ROOT)
    parser.add_argument("--restore-point", type=Path)
    parser.add_argument("--health-timeout", type=int, default=180)
    args = parser.parse_args(argv)
    require(args.config.is_absolute() and args.config.resolve() == args.config, "Use the real absolute configuration path.")
    require(30 <= args.health_timeout <= 600, "Health timeout must be 30..600 seconds.")
    if args.action == "runtime-check":
        require_root(args)
        require(args.authorize_runtime_check, "Runtime checks require --authorize-runtime-check.")
        running = runtime_check(args, require_running=None)
        print(f"PASS: runtime identity verified; container running={running}.")
    elif args.action == "rollback":
        require(args.restore_point is not None, "Rollback requires --restore-point; no automatic selection.")
        rollback(args)
    else:
        install(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("STOP:", str(exc) if isinstance(exc, Stop) else "Unexpected local failure; details suppressed.", file=sys.stderr)
        raise SystemExit(1)
