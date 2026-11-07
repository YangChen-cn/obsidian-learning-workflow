# SPDX-License-Identifier: GPL-3.0-only
import copy
import argparse
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import obsidian_setup as setup  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_versions_are_pinned_and_complete(self):
        versions = setup.validate_versions()
        ids = {plugin["id"] for plugin in versions["plugins"]}
        self.assertEqual(
            ids,
            {"obsidian-meta-bind-plugin", "quickadd", "flashcard-studio"},
        )
        self.assertGreaterEqual(versions["obsidian"]["minimum"], "1.13.1")

    def test_flashcard_settings_keep_markdown_as_source(self):
        config = setup.validate_configs()
        settings = config["flashcard"]["settings"]
        self.assertEqual(settings["dataStore"], "NOTES")
        self.assertTrue(settings["typeAnswers"])
        self.assertEqual(settings["flashcardTags"], ["#flashcards"])
        self.assertEqual(
            {
                key: settings[key]
                for key in (
                    "flashcardAgainText",
                    "flashcardHardText",
                    "flashcardGoodText",
                    "flashcardEasyText",
                )
            },
            {
                "flashcardAgainText": "重来",
                "flashcardHardText": "困难",
                "flashcardGoodText": "良好",
                "flashcardEasyText": "简单",
            },
        )


class MergeTests(unittest.TestCase):
    def test_deep_merge_preserves_unrelated_user_keys(self):
        existing = {
            "settings": {"typeAnswers": False, "reviewLogFolder": "old", "custom": 7},
            "welcomeShown": True,
        }
        overlay = {"settings": {"typeAnswers": True, "reviewLogFolder": "new"}}
        merged = setup.deep_merge(existing, overlay)
        self.assertTrue(merged["settings"]["typeAnswers"])
        self.assertEqual(merged["settings"]["reviewLogFolder"], "new")
        self.assertEqual(merged["settings"]["custom"], 7)
        self.assertTrue(merged["welcomeShown"])
        self.assertFalse(existing["settings"]["typeAnswers"], "input must not be mutated")

    def test_merge_choices_preserves_custom_nested_choices_and_is_idempotent(self):
        existing = [
            {"id": "keep", "name": "Keep"},
            {"id": "replace", "name": "Old", "choices": [
                {"id": "user-child", "name": "My own command"},
                {"id": "managed-child", "name": "Old managed command"},
            ]},
        ]
        incoming = [{"id": "replace", "name": "New", "choices": [
            {"id": "managed-child", "name": "Updated managed command"},
            {"id": "fresh", "name": "New managed command"},
        ]}]
        merged = setup.merge_choices(existing, incoming)
        self.assertEqual([choice["id"] for choice in merged], ["keep", "replace"])
        self.assertEqual(merged[1]["name"], "New")
        self.assertEqual([choice["id"] for choice in merged[1]["choices"]],
                         ["user-child", "managed-child", "fresh"])
        self.assertEqual(merged[1]["choices"][0]["name"], "My own command")
        self.assertEqual(merged[1]["choices"][1]["name"], "Updated managed command")
        self.assertEqual(existing[1]["name"], "Old")
        self.assertEqual(merged, setup.merge_choices(copy.deepcopy(existing), incoming))
        self.assertEqual(merged, setup.merge_choices(merged, incoming))

    def test_choice_index_rejects_duplicate_ids(self):
        with self.assertRaises(setup.SetupError):
            setup.choice_index([{"id": "same"}, {"id": "same"}])

    def test_progress_validation_accepts_each_real_user_stage_state(self):
        text = ('---\nstage_1: done\nstage_2: "in-progress"\n'
                "stage_3: 'planned'\nstage_4: planned # untouched\nstage_5: done\n---\n")
        self.assertEqual(setup.validate_stage_properties(text), [])
        self.assertTrue(setup.validate_stage_properties(text.replace("stage_5: done", "stage_5: invalid")))
        self.assertTrue(setup.validate_stage_properties(text.replace("stage_5: done\n", "")))
        self.assertTrue(setup.validate_stage_properties(text.replace("stage_5: done", "stage_5: done\nstage_5: planned")))

    def test_check_accepts_progress_and_reports_stale_nested_command(self):
        expected = [{"id": "parent", "name": "观察", "type": "Multi", "command": True,
                     "choices": [{"id": "stage", "name": "阶段一", "type": "Capture", "command": True,
                                  "captureTo": "02 Projects/demo/Experiments/Practice.md",
                                  "insertAfter": {"enabled": True, "after": "## 阶段一"}}]}]
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            obsidian = vault / ".obsidian"
            quickadd = obsidian / "plugins/quickadd"
            quickadd.mkdir(parents=True)
            (quickadd / "manifest.json").write_text('{"id":"quickadd","version":"2.33.1"}')
            (quickadd / "data.json").write_text(json.dumps({"choices": expected}))
            (obsidian / "community-plugins.json").write_text('["quickadd"]')
            (obsidian / "core-plugins.json").write_text('{"bases":true}')
            source_css = vault / "workbench.css"
            source_css.write_text(".learning-workbench { color: inherit; }\n")
            snippet = obsidian / "snippets/learning-workbench.css"
            snippet.parent.mkdir()
            snippet.write_bytes(source_css.read_bytes())
            appearance = obsidian / "appearance.json"
            appearance.write_text('{"enabledCssSnippets":["learning-workbench"]}')
            exp = vault / expected[0]["choices"][0]["captureTo"]
            exp.parent.mkdir(parents=True)
            exp.write_text('---\nstage_1: done\nstage_2: in-progress\nstage_3: planned\n'
                           'stage_4: planned\nstage_5: planned\n---\n## 学习控制台\n## 阶段一\n')
            versions = {"obsidian": {"minimum": "1.13.1"},
                        "plugins": [{"id": "quickadd", "version": "2.33.1", "assets": {}}]}
            configs = {"quickadd": {"choices": expected}, "choices": setup.choice_index(expected)}
            args = argparse.Namespace(vault=vault, require_content=True, skip_app_check=False)
            with patch.object(setup, "validate_versions", return_value=versions), \
                 patch.object(setup, "validate_configs", return_value=configs), \
                 patch.object(setup, "app_version", return_value="1.14.5"), \
                 patch.object(setup, "CONTENT_FILES", []), \
                 patch.object(setup, "REQUIRED_TOKENS", {}), \
                 patch.object(setup, "WORKBENCH_CSS", source_css), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(setup.cmd_check(args), 0)
                snippet.write_text("outdated snippet")
                self.assertEqual(setup.cmd_check(args), 1)
                self.assertIn("Workbench CSS snippet missing or outdated", errors.getvalue())
                snippet.write_bytes(source_css.read_bytes())
                appearance.write_text('{"enabledCssSnippets":["another-snippet"]}')
                self.assertEqual(setup.cmd_check(args), 1)
                self.assertIn("Workbench CSS snippet is not enabled", errors.getvalue())
                appearance.write_text('{"enabledCssSnippets":["learning-workbench"]}')
                altered = copy.deepcopy(expected)
                altered[0]["choices"][0]["captureTo"] = "missing.md"
                (quickadd / "data.json").write_text(json.dumps({"choices": altered}))
                self.assertEqual(setup.cmd_check(args), 1)
                self.assertIn("阶段一", errors.getvalue())
                self.assertIn("make obsidian-apply", errors.getvalue())
                altered[0]["choices"] = []
                (quickadd / "data.json").write_text(json.dumps({"choices": altered}))
                self.assertEqual(setup.cmd_check(args), 1)

    def test_community_plugin_list_is_merged_without_dropping_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            obsidian = Path(tmp) / ".obsidian"
            obsidian.mkdir()
            (obsidian / "community-plugins.json").write_text(
                json.dumps(["obsidian-local-rest-api"]),
                encoding="utf-8",
            )
            added = setup.ensure_plugin_list(obsidian, ["quickadd"])
            self.assertEqual(added, ["quickadd"])
            data = json.loads((obsidian / "community-plugins.json").read_text(encoding="utf-8"))
            self.assertEqual(data, ["obsidian-local-rest-api", "quickadd"])


class WorkbenchSnippetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "vault"
        self.obsidian = self.vault / ".obsidian"
        self.plugins = self.obsidian / "plugins"
        for name in ("quickadd", "obsidian-meta-bind-plugin", "flashcard-studio"):
            folder = self.plugins / name
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text('{}')
        self.quickadd = self.plugins / "quickadd/data.json"
        self.quickadd.write_text(json.dumps({"choices": [{"id": "parent", "name": "Old", "choices": [
            {"id": "custom", "name": "User custom child"}]}], "customSetting": True}))
        (self.plugins / "obsidian-meta-bind-plugin/data.json").write_text('{"userSetting":true}')
        (self.plugins / "flashcard-studio/data.json").write_text('{"settings":{"reviewHistory":"preserve"}}')
        (self.obsidian / "core-plugins.json").write_text('{"bases":true}')
        (self.obsidian / "community-plugins.json").write_text(
            '["quickadd","obsidian-meta-bind-plugin","flashcard-studio","obsidian-local-rest-api"]')
        self.appearance = self.obsidian / "appearance.json"
        self.appearance.write_text('{"cssTheme":"My theme","baseFontSize":18,'
                                   '"enabledCssSnippets":["my-snippet"]}')
        self.snippet = self.obsidian / "snippets/learning-workbench.css"
        self.snippet.parent.mkdir()
        self.snippet.write_text("old custom snippet content")
        self.source = self.root / "workbench.css"
        self.source.write_text(".learning-workbench { color: inherit; }\n")
        self.versions = {"plugins": [{"id": name} for name in
                         ("quickadd", "obsidian-meta-bind-plugin", "flashcard-studio")]}
        self.configs = {"quickadd": {"choices": [{"id": "parent", "name": "Managed", "choices": [
            {"id": "managed-child", "name": "Managed child"}]}]},
            "meta_bind": {"enableJs": False}, "flashcard": {"settings": {"typeAnswers": True}}}

    def apply(self, *, dry_run=False):
        with patch.object(setup, "validate_versions", return_value=self.versions), \
             patch.object(setup, "validate_configs", return_value=self.configs), \
             patch.object(setup, "WORKBENCH_CSS", self.source), \
             contextlib.redirect_stdout(io.StringIO()):
            return setup.cmd_apply(argparse.Namespace(vault=self.vault, dry_run=dry_run))

    def test_apply_preserves_theme_other_snippets_and_is_idempotent(self):
        original_appearance = self.appearance.read_bytes()
        self.assertEqual(self.apply(), 0)
        settings = json.loads(self.appearance.read_text())
        self.assertEqual(settings["cssTheme"], "My theme")
        self.assertEqual(settings["baseFontSize"], 18)
        self.assertEqual(settings["enabledCssSnippets"], ["my-snippet", "learning-workbench"])
        self.assertEqual(self.snippet.read_bytes(), self.source.read_bytes())
        choices = json.loads(self.quickadd.read_text())["choices"][0]["choices"]
        self.assertEqual([choice["id"] for choice in choices], ["custom", "managed-child"])
        backups = list((self.obsidian / "backups").glob("obsidian-setup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "appearance.json").read_bytes(), original_appearance)
        self.assertEqual((backups[0] / "snippets/learning-workbench.css").read_text(),
                         "old custom snippet content")
        watched = [self.snippet, self.appearance, self.quickadd,
                   self.plugins / "obsidian-meta-bind-plugin/data.json",
                   self.plugins / "flashcard-studio/data.json"]
        previous = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched}
        self.assertEqual(self.apply(), 0)
        self.assertEqual(previous, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in watched})
        self.assertEqual(len(list((self.obsidian / "backups").glob("obsidian-setup-*"))), 1)

    def test_dry_run_changes_nothing_and_rejects_existing_snippet_symlink(self):
        previous = {path: path.read_bytes() for path in (self.quickadd, self.appearance, self.snippet)}
        self.assertEqual(self.apply(dry_run=True), 0)
        self.assertEqual(previous, {path: path.read_bytes() for path in previous})
        self.assertFalse((self.obsidian / "backups").exists())
        external = self.root / "user-snippet.css"
        external.write_text("user-owned")
        self.snippet.unlink()
        self.snippet.symlink_to(external)
        with self.assertRaises(setup.SetupError):
            self.apply()
        self.assertTrue(self.snippet.is_symlink())
        self.assertEqual(external.read_text(), "user-owned")
        self.assertEqual(self.quickadd.read_bytes(), previous[self.quickadd])
        self.assertEqual(self.appearance.read_bytes(), previous[self.appearance])
        self.snippet.unlink()
        self.snippet.write_bytes(previous[self.snippet])
        external_appearance = self.root / "user-appearance.json"
        external_appearance.write_text('{"cssTheme":"linked theme"}')
        self.appearance.unlink()
        self.appearance.symlink_to(external_appearance)
        with self.assertRaises(setup.SetupError):
            self.apply()
        self.assertTrue(self.appearance.is_symlink())
        self.assertEqual(external_appearance.read_text(), '{"cssTheme":"linked theme"}')
        self.assertEqual(self.quickadd.read_bytes(), previous[self.quickadd])


class InstallationTests(unittest.TestCase):
    @staticmethod
    def assets(plugin_id="quickadd", version="2.33.1"):
        return {"main.js": b"new plugin code", "styles.css": b"new css",
                "manifest.json": json.dumps({"id": plugin_id, "version": version}).encode()}

    def test_install_command_preserves_each_plugins_data_with_mocked_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            obsidian = vault / ".obsidian"
            plugins_dir = obsidian / "plugins"
            plugins_dir.mkdir(parents=True)
            (obsidian / "core-plugins.json").write_text('{"bases":true}')
            (obsidian / "community-plugins.json").write_text('["obsidian-local-rest-api"]')
            rest = plugins_dir / "obsidian-local-rest-api/data.json"
            rest.parent.mkdir()
            rest.write_text("other plugin settings")
            plugins = []
            payloads = {}
            for plugin_id in ("quickadd", "flashcard-studio", "obsidian-meta-bind-plugin"):
                plugin_dir = plugins_dir / plugin_id
                plugin_dir.mkdir()
                (plugin_dir / "data.json").write_text("existing " + plugin_id)
                (plugin_dir / "review-history.json").write_text("history " + plugin_id)
                assets = self.assets(plugin_id=plugin_id)
                plugins.append({"id": plugin_id, "repo": "example/" + plugin_id, "version": "2.33.1",
                                "assets": {name: hashlib.sha256(data).hexdigest()
                                           for name, data in assets.items()}})
                for name, data in assets.items():
                    url = f"https://github.com/example/{plugin_id}/releases/download/2.33.1/{name}"
                    payloads[url] = data
            args = argparse.Namespace(vault=vault, timeout=5, dry_run=False)
            with patch.object(setup, "validate_versions", return_value={"plugins": plugins}), \
                 patch.object(setup, "download_bytes", side_effect=lambda url, timeout: payloads[url]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(setup.cmd_install(args), 0)
            for plugin in plugins:
                plugin_id = plugin["id"]
                self.assertEqual((plugins_dir / plugin_id / "data.json").read_text(), "existing " + plugin_id)
                self.assertEqual((plugins_dir / plugin_id / "review-history.json").read_text(), "history " + plugin_id)
                self.assertEqual((plugins_dir / plugin_id / "main.js").read_bytes(), b"new plugin code")
            self.assertEqual(rest.read_text(), "other plugin settings")
            self.assertIn("obsidian-local-rest-api", json.loads((obsidian / "community-plugins.json").read_text()))

    def test_reinstall_keeps_runtime_data_reviews_other_files_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".obsidian/plugins/quickadd"
            target.mkdir(parents=True)
            (target / "data.json").write_bytes(b'{"choices":[{"name":"My existing choice"}]}')
            (target / "main.js").write_bytes(b"old plugin code")
            (target / "manifest.json").write_bytes(b'{"id":"quickadd","version":"old"}')
            history = target / "history/reviews.json"
            history.parent.mkdir()
            history.write_bytes(b'{"review":"existing"}')
            other = target.parent / "obsidian-local-rest-api/data.json"
            other.parent.mkdir()
            other.write_bytes(b"unchanged other plugin")
            backup = root / ".obsidian/backups/test"
            setup.install_plugin_assets(target, {"id": "quickadd", "version": "2.33.1"},
                                        self.assets(), backup)
            self.assertEqual((target / "data.json").read_bytes(), b'{"choices":[{"name":"My existing choice"}]}')
            self.assertEqual(history.read_bytes(), b'{"review":"existing"}')
            self.assertEqual(other.read_bytes(), b"unchanged other plugin")
            self.assertEqual((target / "main.js").read_bytes(), b"new plugin code")
            self.assertEqual((backup / "plugins/quickadd/main.js").read_bytes(), b"old plugin code")
            self.assertEqual((backup / "plugins/quickadd/history/reviews.json").read_bytes(),
                             b'{"review":"existing"}')

    def test_invalid_release_preserves_existing_plugin_and_no_staging_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".obsidian/plugins/quickadd"
            target.mkdir(parents=True)
            (target / "data.json").write_text("existing settings")
            (target / "main.js").write_text("existing code")
            with self.assertRaises(setup.SetupError):
                setup.install_plugin_assets(target, {"id": "quickadd", "version": "2.33.1"},
                                            self.assets(version="wrong"), root / "backup")
            self.assertEqual((target / "data.json").read_text(), "existing settings")
            self.assertEqual((target / "main.js").read_text(), "existing code")
            self.assertEqual(list(target.parent.glob(".quickadd-install-*")), [])

    def test_data_json_cannot_be_supplied_as_a_release_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "plugins/quickadd"
            target.mkdir(parents=True)
            (target / "data.json").write_text("user settings")
            assets = self.assets()
            assets["data.json"] = b"unexpected replacement"
            with self.assertRaises(setup.SetupError):
                setup.install_plugin_assets(target, {"id": "quickadd", "version": "2.33.1"},
                                            assets, root / "backup")
            self.assertEqual((target / "data.json").read_text(), "user settings")

    def test_release_asset_symlink_is_not_followed_when_reinstalling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / ".obsidian/plugins/quickadd"
            target.mkdir(parents=True)
            other_file = root / "unrelated.txt"
            other_file.write_text("must not be overwritten")
            (target / "main.js").symlink_to(other_file)
            setup.install_plugin_assets(target, {"id": "quickadd", "version": "2.33.1"},
                                        self.assets(), root / "backup")
            self.assertEqual(other_file.read_text(), "must not be overwritten")
            self.assertFalse((target / "main.js").is_symlink())
            self.assertEqual((target / "main.js").read_bytes(), b"new plugin code")


if __name__ == "__main__":
    unittest.main()
