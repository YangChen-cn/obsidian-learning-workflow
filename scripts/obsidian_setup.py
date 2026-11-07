#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Inspect, install and apply the tracked Obsidian workbench configuration.

The vault's ``.obsidian/`` directory is intentionally local-only. This tool
keeps the reproducible part in ``obsidian/`` and merges only the keys the
workbench owns into the local plugin settings, backing up every file it
changes. It never reads or writes the Local REST API key.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
from learning import vault_for

DEFAULT_VAULT = vault_for(ROOT)
CONFIG_DIR = ROOT / "obsidian"
VERSIONS_FILE = CONFIG_DIR / "versions.json"
QUICKADD_CONFIG = CONFIG_DIR / "quickadd.choices.json"
META_BIND_CONFIG = CONFIG_DIR / "meta-bind.settings.json"
FLASHCARD_CONFIG = CONFIG_DIR / "flashcard-studio.settings.json"
WORKBENCH_CSS = CONFIG_DIR / "workbench.css"
WORKBENCH_SNIPPET = "learning-workbench"

PLUGIN_CONFIGS = [
    ("quickadd", "QuickAdd", QUICKADD_CONFIG),
    ("obsidian-meta-bind-plugin", "Meta Bind", META_BIND_CONFIG),
    ("flashcard-studio", "Flashcard Studio", FLASHCARD_CONFIG),
]

CONTENT_FILES = ["00 Dashboard/学习工作台.base", "00 Dashboard/Home.md", "04 Flashcards/示例题库.md"]
REQUIRED_TOKENS = {"00 Dashboard/Home.md": ["## 学习工作台"],
                   "04 Flashcards/示例题库.md": ["#flashcards", "::", "=="]}


class SetupError(RuntimeError):
    """A reproducible setup problem that the operator must fix."""


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise SetupError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SetupError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def write_bytes(path: Path, data: bytes) -> None:
    """Replace the tracked CSS snippet atomically without following symlinks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def workbench_snippet_paths(vault: Path) -> tuple[Path, Path]:
    return (vault / ".obsidian/snippets" / f"{WORKBENCH_SNIPPET}.css",
            vault / ".obsidian/appearance.json")


def check_workbench_snippet(vault: Path) -> list[str]:
    """Check both the installed bytes and the user's enabled-snippets list."""
    target, appearance = workbench_snippet_paths(vault)
    if not WORKBENCH_CSS.is_file():
        return [f"Tracked workbench CSS missing: {WORKBENCH_CSS}"]
    errors = []
    if target.parent.is_symlink() or target.is_symlink():
        errors.append("Workbench CSS path is a symlink; inspect it before running make obsidian-apply")
    elif not target.is_file() or target.read_bytes() != WORKBENCH_CSS.read_bytes():
        errors.append("Workbench CSS snippet missing or outdated; run make obsidian-apply")
    try:
        settings = load_json(appearance) if appearance.is_file() else {}
        enabled = settings.get("enabledCssSnippets", []) if isinstance(settings, dict) else []
        if not isinstance(enabled, list) or WORKBENCH_SNIPPET not in enabled:
            errors.append("Workbench CSS snippet is not enabled; run make obsidian-apply")
    except SetupError as exc:
        errors.append(str(exc))
    return errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in value.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def app_version() -> str | None:
    plist = Path("/Applications/Obsidian.app/Contents/Info.plist")
    if not plist.exists():
        return None
    try:
        with plist.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None
    value = data.get("CFBundleShortVersionString")
    return str(value) if value else None


def deep_merge(base: Any, overlay: Any) -> Any:
    """Return a copy of base with overlay merged recursively; lists replace."""
    result = copy.deepcopy(base)
    if not isinstance(result, dict) or not isinstance(overlay, dict):
        return copy.deepcopy(overlay)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def merge_choices(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    """Update managed choices recursively without discarding unrelated children.

    Matching ids receive the tracked fields; unmatched children remain in their
    original order, and new managed children are appended. We cannot distinguish
    an old removed managed id from a user-created one, so neither is deleted.
    """
    if not isinstance(existing, list) or not isinstance(incoming, list):
        raise SetupError("QuickAdd choices must be lists; existing data was not changed")
    result = copy.deepcopy(existing)
    positions = {
        choice.get("id"): index
        for index, choice in enumerate(result)
        if isinstance(choice, dict) and choice.get("id")
    }
    for choice in incoming:
        if not isinstance(choice, dict) or not choice.get("id"):
            raise SetupError("every QuickAdd choice needs a stable id")
        choice_id = choice["id"]
        if choice_id in positions:
            index = positions[choice_id]
            previous = result[index]
            updated = copy.deepcopy(choice)
            if isinstance(choice.get("choices"), list) and isinstance(previous.get("choices"), list):
                updated["choices"] = merge_choices(previous["choices"], choice["choices"])
            result[index] = updated
        else:
            positions[choice_id] = len(result)
            result.append(copy.deepcopy(choice))
    return result


def validate_stage_properties(text: str) -> list[str]:
    """Validate user-editable progress without assuming the initial state."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ["实验: missing frontmatter"]
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return ["实验: unterminated frontmatter"]
    found: dict[str, list[str]] = {}
    for line in lines[1:end]:
        match = re.match(r"^(stage_[1-5]):[ \t]*(.*)$", line)
        if not match:
            continue
        value = re.sub(r"\s+#.*$", "", match.group(2)).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        found.setdefault(match.group(1), []).append(value)
    errors = []
    for number in range(1, 6):
        name = f"stage_{number}"
        values = found.get(name, [])
        if len(values) != 1 or values[0] not in {"planned", "in-progress", "done"}:
            errors.append(f"实验: {name} must appear once with planned, in-progress or done")
    return errors


def config_contains(actual: Any, expected: Any) -> bool:
    """Allow plugin-added defaults while checking the fields the kit manages."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and config_contains(actual[key], value)
            for key, value in expected.items()
        )
    return actual == expected


def managed_choice_errors(live: Any, expected: dict[str, dict[str, Any]]) -> list[str]:
    """Detect stale or missing live commands, including nested capture actions."""
    if not isinstance(live, list):
        raise SetupError("QuickAdd choices must be a list")
    live_index = choice_index(live)
    errors = []
    # UI expansion and extra user children are not managed command behavior.
    ignored = {"choices", "collapsed"}
    for choice_id, choice in expected.items():
        observed = live_index.get(choice_id)
        expected_fields = {key: value for key, value in choice.items() if key not in ignored}
        if observed is None or not config_contains(observed, expected_fields):
            errors.append(
                f"QuickAdd command missing or outdated: {choice.get('name', choice_id)}; "
                "run make obsidian-apply and reload QuickAdd"
            )
    return errors


def choice_index(choices: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        choice_id = choice.get("id")
        if choice_id:
            if choice_id in index:
                raise SetupError(f"duplicate QuickAdd choice id: {choice_id}")
            index[choice_id] = choice
        children = choice.get("choices")
        if isinstance(children, list):
            for child_id, child in choice_index(children).items():
                if child_id in index:
                    raise SetupError(f"duplicate QuickAdd choice id: {child_id}")
                index[child_id] = child
    return index


def validate_versions() -> dict[str, Any]:
    versions = load_json(VERSIONS_FILE)
    if versions.get("schema") != 1:
        raise SetupError("obsidian/versions.json schema must be 1")
    obsidian = versions.get("obsidian", {})
    for key in ("minimum", "tested"):
        if not isinstance(obsidian.get(key), str):
            raise SetupError(f"versions.obsidian.{key} must be a string")
    plugins = versions.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise SetupError("versions.plugins must be a non-empty list")
    seen: set[str] = set()
    for plugin in plugins:
        for key in ("id", "version", "minAppVersion", "repo", "assets"):
            if key not in plugin:
                raise SetupError(f"versions plugin missing {key}: {plugin!r}")
        if plugin["id"] in seen:
            raise SetupError(f"duplicate plugin id: {plugin['id']}")
        seen.add(plugin["id"])
        if not isinstance(plugin["assets"], dict) or set(plugin["assets"]) != {"main.js", "manifest.json", "styles.css"}:
            raise SetupError(f"{plugin['id']}: only the three release assets may be installed")
        for asset in ("main.js", "manifest.json", "styles.css"):
            digest = plugin["assets"].get(asset)
            if not isinstance(digest, str) or len(digest) != 64:
                raise SetupError(f"invalid SHA256 for {plugin['id']}/{asset}")
    return versions


def validate_configs() -> dict[str, Any]:
    quickadd = load_json(QUICKADD_CONFIG)
    choices = quickadd.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SetupError("obsidian/quickadd.choices.json needs a non-empty choices list")
    index = choice_index(choices)
    for capture_id, choice in index.items():
        if choice.get("type") == "Capture":
            target = choice.get("captureTo")
            if not isinstance(target, str) or not target:
                raise SetupError(f"Capture {capture_id} has no captureTo")
            after = choice.get("insertAfter", {})
            if after.get("enabled") and not after.get("after"):
                raise SetupError(f"Capture {capture_id} has insertAfter without heading")

    meta_bind = load_json(META_BIND_CONFIG)
    if meta_bind.get("enableJs") is not False:
        raise SetupError("Meta Bind package must keep enableJs false")

    flashcard = load_json(FLASHCARD_CONFIG)
    settings = flashcard.get("settings")
    if not isinstance(settings, dict) or settings.get("typeAnswers") is not True:
        raise SetupError("Flashcard Studio package must enable typed answers")
    if "#flashcards" not in settings.get("flashcardTags", []):
        raise SetupError("Flashcard Studio package must use the #flashcards tag")

    return {"quickadd": quickadd, "choices": index, "meta_bind": meta_bind, "flashcard": flashcard}


def plugin_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    path = plugin_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        return load_json(path)
    except SetupError:
        return None


def plugin_backup_root(vault: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S")
    return vault / ".obsidian" / "backups" / f"obsidian-setup-{stamp}-{os.getpid()}"


def backup_path(vault: Path, backup_root: Path, path: Path) -> Path:
    try:
        relative = path.relative_to(vault / ".obsidian")
    except ValueError as exc:
        raise SetupError(f"refusing to back up outside the vault config: {path}") from exc
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def ensure_plugin_list(
    obsidian_dir: Path,
    plugin_ids: list[str],
    backup_root: Path | None = None,
) -> list[str]:
    path = obsidian_dir / "community-plugins.json"
    existing = load_json(path) if path.exists() else []
    if not isinstance(existing, list):
        raise SetupError("community-plugins.json must be a JSON list")
    result = [str(item) for item in existing]
    added: list[str] = []
    for plugin_id in plugin_ids:
        if plugin_id not in result:
            result.append(plugin_id)
            added.append(plugin_id)
    if result != existing:
        if backup_root is not None and path.exists():
            backup_path(obsidian_dir.parent, backup_root, path)
        write_json(path, result)
    return added


def ensure_bases_core(obsidian_dir: Path, backup_root: Path | None = None) -> bool:
    path = obsidian_dir / "core-plugins.json"
    existing = load_json(path) if path.exists() else {}
    if not isinstance(existing, dict):
        raise SetupError("core-plugins.json must be a JSON object")
    if existing.get("bases") is True:
        return False
    existing["bases"] = True
    if backup_root is not None and path.exists():
        backup_path(obsidian_dir.parent, backup_root, path)
    write_json(path, existing)
    return True


def cmd_check(args: argparse.Namespace) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        versions = validate_versions()
        configs = validate_configs()
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    vault = args.vault
    obsidian_dir = vault / ".obsidian"
    plugins_dir = obsidian_dir / "plugins"
    if not vault.is_dir():
        errors.append(f"vault not found: {vault}")

    installed_app = app_version()
    minimum = versions["obsidian"]["minimum"]
    if args.skip_app_check:
        print("Obsidian app version: not checked (vault-only mode)")
    elif installed_app is None:
        errors.append("Obsidian.app not found in /Applications")
    elif version_tuple(installed_app) < version_tuple(minimum):
        errors.append(f"Obsidian {installed_app} is older than required {minimum}")
    else:
        print(f"Obsidian: {installed_app} (>= {minimum})")

    community: list[str] = []
    community_path = obsidian_dir / "community-plugins.json"
    if community_path.exists():
        try:
            loaded = load_json(community_path)
            if isinstance(loaded, list):
                community = [str(item) for item in loaded]
        except SetupError as exc:
            errors.append(str(exc))

    for plugin in versions["plugins"]:
        plugin_id = plugin["id"]
        plugin_dir = plugins_dir / plugin_id
        manifest = plugin_manifest(plugin_dir)
        if manifest is None:
            errors.append(f"{plugin_id}: plugin or manifest missing")
            continue
        if manifest.get("version") != plugin["version"]:
            errors.append(
                f"{plugin_id}: installed {manifest.get('version')} != pinned {plugin['version']}"
            )
        for asset, expected in plugin["assets"].items():
            path = plugin_dir / asset
            if not path.exists():
                errors.append(f"{plugin_id}: missing asset {asset}")
            else:
                actual = sha256_file(path)
                if actual != expected:
                    errors.append(f"{plugin_id}: SHA256 mismatch for {asset}")
        if plugin_id not in community:
            errors.append(f"{plugin_id}: not in community-plugins.json")
        else:
            print(f"{plugin_id}: {plugin['version']} pinned and enabled")

    core_path = obsidian_dir / "core-plugins.json"
    if not core_path.exists():
        errors.append("core-plugins.json missing; enable the Bases core plugin")
    else:
        try:
            core = load_json(core_path)
            if core.get("bases") is not True:
                errors.append("Bases core plugin is not enabled")
        except SetupError as exc:
            errors.append(str(exc))

    errors.extend(check_workbench_snippet(vault))

    quickadd_data_path = plugins_dir / "quickadd" / "data.json"
    if quickadd_data_path.exists():
        try:
            quickadd_data = load_json(quickadd_data_path)
            live = {
                choice.get("id")
                for choice in quickadd_data.get("choices", [])
                if isinstance(choice, dict)
            }
            expected = {
                choice.get("id")
                for choice in configs["quickadd"].get("choices", [])
                if isinstance(choice, dict)
            }
            missing = expected - live
            if missing:
                warnings.append(
                    "QuickAdd choices not applied yet: " + ", ".join(sorted(str(x) for x in missing))
                )
        except SetupError as exc:
            warnings.append(str(exc))
    else:
        warnings.append("QuickAdd data.json missing; run apply after first launch")

    if args.require_content:
        for relative in CONTENT_FILES:
            if not (vault / relative).is_file():
                errors.append(f"missing content: {relative}")
        for relative, tokens in REQUIRED_TOKENS.items():
            path = Path(relative)
            if not path.is_absolute():
                path = vault / relative.removeprefix("vault/")
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for token in tokens:
                if token not in text:
                    errors.append(f"{path.relative_to(vault)}: missing marker {token!r}")

        try:
            quickadd_data = load_json(quickadd_data_path)
            live_index = choice_index(quickadd_data.get("choices", []))
            errors.extend(managed_choice_errors(quickadd_data.get("choices", []), configs["choices"]))
            for choice_id, choice in configs["choices"].items():
                if choice.get("type") == "Capture" and choice.get("command"):
                    target = vault / choice["captureTo"]
                    if not target.is_file():
                        errors.append(f"QuickAdd target missing: {choice['captureTo']}")
                        continue
                    after = choice.get("insertAfter", {})
                    if after.get("enabled"):
                        heading = after["after"]
                        if heading not in target.read_text(encoding="utf-8"):
                            errors.append(
                                f"QuickAdd heading not found in {choice['captureTo']}: {heading}"
                            )
            if not live_index:
                errors.append("QuickAdd has no applied choices")
        except SetupError as exc:
            errors.append(str(exc))

    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("Obsidian workbench check: OK")
    return 0


def _read_or_empty(path: Path) -> Any:
    return load_json(path) if path.exists() else {}


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        versions = validate_versions()
        configs = validate_configs()
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    vault = args.vault
    obsidian_dir = vault / ".obsidian"
    plugins_dir = obsidian_dir / "plugins"
    if not obsidian_dir.is_dir():
        print(f"ERROR: not an Obsidian vault: {vault}", file=sys.stderr)
        return 1

    for plugin in versions["plugins"]:
        if plugin_manifest(plugins_dir / plugin["id"]) is None:
            print(
                f"ERROR: {plugin['id']} is not installed; run: "
                f"python3 scripts/obsidian_setup.py --vault {shlex.quote(str(vault))} install",
                file=sys.stderr,
            )
            return 1

    planned: list[tuple[str, Path, Any, str]] = []
    quickadd_target = plugins_dir / "quickadd" / "data.json"
    existing = _read_or_empty(quickadd_target)
    if not isinstance(existing, dict):
        raise SetupError("QuickAdd data.json must be a JSON object")
    merged = copy.deepcopy(existing)
    merged["choices"] = merge_choices(existing.get("choices", []), configs["quickadd"]["choices"])
    choice_index(merged["choices"])
    planned.append(("QuickAdd choices", quickadd_target, merged, "merge choices by id"))

    meta_target = plugins_dir / "obsidian-meta-bind-plugin" / "data.json"
    planned.append(
        (
            "Meta Bind settings",
            meta_target,
            deep_merge(_read_or_empty(meta_target), configs["meta_bind"]),
            "merge workbench keys",
        )
    )

    flash_target = plugins_dir / "flashcard-studio" / "data.json"
    planned.append(
        (
            "Flashcard Studio settings",
            flash_target,
            deep_merge(_read_or_empty(flash_target), configs["flashcard"]),
            "merge workbench keys",
        )
    )

    if not WORKBENCH_CSS.is_file():
        raise SetupError(f"tracked workbench CSS missing: {WORKBENCH_CSS}")
    css_content = WORKBENCH_CSS.read_bytes()
    snippet_target, appearance_target = workbench_snippet_paths(vault)
    if (snippet_target.parent.is_symlink() or snippet_target.is_symlink()
            or (snippet_target.exists() and not snippet_target.is_file())):
        raise SetupError(f"workbench snippet must be a regular file; preserving existing path: {snippet_target}")
    if appearance_target.is_symlink():
        raise SetupError(f"appearance.json is a symlink; preserving existing path: {appearance_target}")
    current_appearance = _read_or_empty(appearance_target)
    if not isinstance(current_appearance, dict):
        raise SetupError("appearance.json must be a JSON object; existing settings were not changed")
    enabled = current_appearance.get("enabledCssSnippets", [])
    if not isinstance(enabled, list):
        raise SetupError("appearance.json enabledCssSnippets must be a list; existing settings were not changed")
    appearance = copy.deepcopy(current_appearance)
    appearance["enabledCssSnippets"] = list(enabled)
    if WORKBENCH_SNIPPET not in appearance["enabledCssSnippets"]:
        appearance["enabledCssSnippets"].append(WORKBENCH_SNIPPET)
    planned.append(("Workbench appearance", appearance_target, appearance, "enable snippet"))

    if args.dry_run:
        for label, path, _data, how in planned:
            print(f"WOULD {label}: {path} ({how})")
        print(f"WOULD Workbench CSS: {snippet_target} (install scoped snippet)")
        print("Dry run: no files changed")
        return 0

    backup_root = plugin_backup_root(vault)
    for label, path, data, how in planned:
        if path.exists() and load_json(path) == data:
            print(f"{label}: unchanged ({path})")
            continue
        backup = backup_path(vault, backup_root, path) if path.exists() else None
        write_json(path, data)
        suffix = f" (backup: {backup})" if backup else " (created)"
        print(f"{label}: {path}{suffix} [{how}]")

    if snippet_target.is_file() and snippet_target.read_bytes() == css_content:
        print(f"Workbench CSS: unchanged ({snippet_target})")
    else:
        backup = backup_path(vault, backup_root, snippet_target) if snippet_target.exists() else None
        write_bytes(snippet_target, css_content)
        suffix = f" (backup: {backup})" if backup else " (created)"
        print(f"Workbench CSS: {snippet_target}{suffix} [install scoped snippet]")

    changed_bases = ensure_bases_core(obsidian_dir, backup_root)
    if changed_bases:
        print("Bases core plugin: enabled")

    added = ensure_plugin_list(
        obsidian_dir, [p["id"] for p in versions["plugins"]], backup_root
    )
    if added:
        print("Enabled community plugins: " + ", ".join(added))
    if backup_root.exists():
        print(f"Backups: {backup_root}")
    print("Restart or reload Obsidian so QuickAdd and the other plugins read the new files.")
    return 0


def download_bytes(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "learning-obsidian-setup/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def install_plugin_assets(target: Path, plugin: dict[str, Any], assets: dict[str, bytes],
                          backup_root: Path) -> None:
    """Atomically replace release assets while retaining plugin-owned data.

    Plugin data.json, review history and any other runtime files are part of the
    existing directory, not release assets. A backup is kept even on success.
    """
    if set(assets) != {"main.js", "manifest.json", "styles.css"}:
        raise SetupError(f"{plugin['id']}: refusing to replace files outside the pinned release assets")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise SetupError(f"refusing to replace non-directory or symlink plugin: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    exists = target.is_dir()
    if exists:
        backup = backup_root / "plugins" / plugin["id"]
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, backup, symlinks=True)
        print(f"Backed up {plugin['id']} to {backup}")

    temporary = Path(tempfile.mkdtemp(prefix=f".{plugin['id']}-install-", dir=target.parent))
    staging = temporary / "staging"
    previous = temporary / "previous"
    keep_temporary = False
    try:
        if exists:
            shutil.copytree(target, staging, symlinks=True)
        else:
            staging.mkdir()
        for asset, payload in assets.items():
            path = staging / asset
            # Do not write through an existing asset symlink into another file.
            if path.is_symlink():
                path.unlink()
            if path.exists() and not path.is_file():
                raise SetupError(f"plugin asset is not a regular file: {target / asset}")
            path.write_bytes(payload)
        manifest = load_json(staging / "manifest.json")
        if manifest.get("version") != plugin["version"] or manifest.get("id") != plugin["id"]:
            raise SetupError(f"{plugin['id']}: release manifest id or version does not match the pin")

        if exists:
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except OSError as exc:
            if previous.exists():
                try:
                    os.replace(previous, target)
                except OSError as rollback_exc:
                    keep_temporary = True
                    raise SetupError(
                        f"{plugin['id']}: install and restore failed; previous files are at "
                        f"{previous}, and a backup was saved under {backup_root}"
                    ) from rollback_exc
            raise SetupError(f"{plugin['id']}: could not replace release assets: {exc}") from exc
    finally:
        if not keep_temporary:
            shutil.rmtree(temporary, ignore_errors=True)


def cmd_install(args: argparse.Namespace) -> int:
    try:
        versions = validate_versions()
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    vault = args.vault
    obsidian_dir = vault / ".obsidian"
    plugins_dir = obsidian_dir / "plugins"
    if not obsidian_dir.is_dir():
        print(f"ERROR: not an Obsidian vault: {vault}", file=sys.stderr)
        return 1

    downloads: dict[str, dict[str, bytes]] = {}
    for plugin in versions["plugins"]:
        plugin_id = plugin["id"]
        assets: dict[str, bytes] = {}
        for asset, expected in plugin["assets"].items():
            url = (
                f"https://github.com/{plugin['repo']}/releases/download/"
                f"{plugin['version']}/{asset}"
            )
            if args.dry_run:
                print(f"WOULD download {asset} for {plugin_id}: {url}")
                continue
            try:
                payload = download_bytes(url, args.timeout)
            except OSError as exc:
                print(f"ERROR: download failed for {url}: {exc}", file=sys.stderr)
                return 1
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                print(
                    f"ERROR: SHA256 mismatch for {url}\n"
                    f"  expected {expected}\n  actual   {actual}",
                    file=sys.stderr,
                )
                return 1
            assets[asset] = payload
        downloads[plugin_id] = assets

    if args.dry_run:
        print("Dry run: no plugins installed")
        return 0

    backup_root = plugin_backup_root(vault)
    for plugin in versions["plugins"]:
        plugin_id = plugin["id"]
        target = plugins_dir / plugin_id
        install_plugin_assets(target, plugin, downloads[plugin_id], backup_root)
        print(f"Installed {plugin_id} {plugin['version']}")

    ensure_bases_core(obsidian_dir, backup_root)
    added = ensure_plugin_list(
        obsidian_dir, [p["id"] for p in versions["plugins"]], backup_root
    )
    if added:
        print("Enabled community plugins: " + ", ".join(added))
    print(f"Backups: {backup_root}")
    print("Start Obsidian once to generate data.json, then run: make obsidian-apply")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT, help="Obsidian vault path")
    parser.add_argument("--skip-app-check", action="store_true", help="check vault only, e.g. on Linux/Windows or CI")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="verify app, plugin pins and optional note content")
    check.add_argument(
        "--require-content",
        action="store_true",
        help="also require the workbench bases, templates and flashcards",
    )
    check.set_defaults(func=cmd_check)

    apply_cmd = sub.add_parser("apply", help="merge tracked settings into the local vault")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.set_defaults(func=cmd_apply)

    install = sub.add_parser("install", help="download the pinned plugin releases")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--timeout", type=int, default=60)
    install.set_defaults(func=cmd_install)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.vault = args.vault.expanduser().resolve()
    try:
        return int(args.func(args))
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
