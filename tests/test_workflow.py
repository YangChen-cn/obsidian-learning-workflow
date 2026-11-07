# SPDX-License-Identifier: GPL-3.0-only
import contextlib
import io
import json
from pathlib import Path, PureWindowsPath
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import learning as app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(ROOT / 'vault', self.root / 'vault', ignore=shutil.ignore_patterns('.obsidian', '.trash'))
        shutil.copytree(ROOT / 'obsidian', self.root / 'obsidian')
        shutil.copy(ROOT / 'workflow.json', self.root)
        self.vault = self.root / 'vault'
        # Exercise a clean sample even when this checkout contains real archives.
        shutil.rmtree(self.vault / '02 Projects/getting-started/Sessions', ignore_errors=True)
        for entry in (self.vault / '03 Daily').glob('20*.md'):
            entry.unlink()
        app.refresh(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            result = app.main(['--root', str(self.root), *args])
        self.last_error = err.getvalue()
        return result

    def session(self, **extra):
        data = {'id': 'first-observation', 'project': 'getting-started', 'date': '2026-01-02',
                'actor': 'agent', 'title': 'Actual work', 'summary': 'Verified one case.',
                'topics': ['A completely new subject'], 'tests': [
                    {'command': 'a non-code check', 'result': 'failed', 'evidence': 'Counterexample observed.'}]}
        data.update(extra)
        p = self.root / 'input.json'
        p.write_text(json.dumps(data))
        return p

    def test_windows_internal_paths_are_normalized_without_accepting_unsafe_strings(self):
        result = app.inside(self.vault, PureWindowsPath('02 Projects/getting-started/Progress.md'))
        self.assertEqual(result, self.vault / '02 Projects/getting-started/Progress.md')
        with self.assertRaises(app.LearningError):
            app.inside(self.vault, r'02 Projects\..\secret.md')
        with self.assertRaises(app.LearningError):
            app.inside(self.vault, PureWindowsPath('../secret.md'))

    def test_multi_subject_projects_and_stable_menu(self):
        self.assertEqual(self.call('project', 'linguistics', '--title', '语言研究'), 0, self.last_error)
        self.assertEqual(self.call('project', 'statistics', '--title', '统计学'), 0)
        self.assertEqual(self.call('refresh'), 0, self.last_error)
        config = json.loads((self.root / 'obsidian/quickadd.choices.json').read_text())
        self.assertEqual(len(config['choices'][0]['choices']), 3)
        progress = (self.vault / '02 Projects/linguistics/Progress.md').read_text()
        self.assertNotIn('Learning Template', progress)
        self.assertIn('暂无活动', progress)
        self.assertFalse(list((self.vault / '03 Daily').glob('20*.md')))
        self.assertEqual(self.call('validate'), 0)

    def test_record_idempotence_conflict_and_real_results(self):
        source = self.session()
        self.assertEqual(self.call('record', str(source)), 0, self.last_error)
        self.assertEqual(self.call('record', str(source)), 0, self.last_error)
        sessions = list((self.vault / '02 Projects/getting-started/Sessions').glob('*.md'))
        self.assertEqual(len(sessions), 1)
        text = sessions[0].read_text()
        self.assertIn('**failed**', text)
        self.assertNotIn('mastery:', text)
        self.assertEqual(self.call('record', str(self.session(summary='Different facts'))), 1)
        self.assertEqual(sessions[0].read_text(), text)
        daily = (self.vault / '03 Daily/2026-01-02.md').read_text()
        self.assertIn('Actual work', daily)
        self.assertEqual(self.call('validate'), 0)

    def test_unchanged_retry_on_later_day_keeps_original_date(self):
        source = self.session()
        data = json.loads(source.read_text())
        del data['date']
        source.write_text(json.dumps(data))
        with patch.object(app, 'day_for', return_value='2026-01-02'):
            self.assertEqual(self.call('record', str(source)), 0, self.last_error)
        with patch.object(app, 'day_for', return_value='2026-01-03'):
            self.assertEqual(self.call('record', str(source)), 0, self.last_error)
        self.assertEqual(len(list((self.vault / '02 Projects/getting-started/Sessions').glob('*.md'))), 1)

    def test_no_command_execution_from_record(self):
        marker = self.root / 'executed'
        source = self.session(tests=[{'command': f'touch {marker}', 'result': 'not_run', 'evidence': 'Not executed'}])
        self.assertEqual(self.call('record', str(source)), 0, self.last_error)
        self.assertFalse(marker.exists())

    def test_review_preserves_mastery_and_updates_full_links(self):
        draft = self.vault / '99 Inbox/candidate.md'
        draft.write_text('---\nid: candidate\ntype: knowledge\nstatus: draft\ntopic: Math\ntarget: "01 Knowledge/Math/idea.md"\nmastery: unassessed\n---\n\n# Idea\n\nOriginal personal text.\n')
        ref = self.vault / 'reference.md'
        ref.write_text('---\ntype: reference\n---\n[[99 Inbox/candidate|Idea]]\n')
        self.assertEqual(self.call('review', '99 Inbox/candidate.md'), 1)
        self.assertTrue(draft.exists())
        self.assertEqual(self.call('review', '99 Inbox/candidate.md', '--approve'), 0, self.last_error)
        dest = self.vault / '01 Knowledge/Math/idea.md'
        self.assertIn('status: reviewed', dest.read_text())
        self.assertIn('mastery: unassessed', dest.read_text())
        self.assertIn('Original personal text.', dest.read_text())
        self.assertIn('[[01 Knowledge/Math/idea|Idea]]', ref.read_text())

    def test_review_refuses_target_overwrite(self):
        target = self.vault / '01 Knowledge/existing.md'
        target.write_text('Keep this')
        draft = self.vault / '99 Inbox/candidate.md'
        draft.write_text('---\ntype: knowledge\nstatus: draft\ntarget: "01 Knowledge/existing.md"\n---\nNew')
        self.assertEqual(self.call('review', '99 Inbox/candidate.md', '--approve'), 1)
        self.assertEqual(target.read_text(), 'Keep this')
        self.assertTrue(draft.exists())

    def test_path_traversal_and_symlinks_refused(self):
        self.assertEqual(self.call('project', '../escape', '--title', 'Invalid'), 1)
        sessions = self.vault / '02 Projects/getting-started/Sessions'
        sessions.mkdir(exist_ok=True)
        sessions.rmdir()
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            sessions.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        self.assertEqual(self.call('record', str(self.session())), 1)
        self.assertEqual(list(outside.iterdir()), [])

    def test_managed_refresh_preserves_user_prose_and_is_idempotent(self):
        home = self.vault / '00 Dashboard/Home.md'
        home.write_text(home.read_text() + '\nA personal annotation.\n')
        self.assertEqual(self.call('refresh'), 0, self.last_error)
        before = home.read_bytes()
        self.assertEqual(self.call('refresh'), 0, self.last_error)
        self.assertEqual(home.read_bytes(), before)
        self.assertIn('A personal annotation.', home.read_text())

    def test_hidden_configuration_not_scanned(self):
        hidden = self.vault / '.obsidian'
        hidden.mkdir(exist_ok=True)
        (hidden / 'private.md').write_text('---\nmastery: invalid\n---\n[[Missing]]')
        self.assertEqual(self.call('validate'), 0)

    def test_missing_stage_fields_are_not_fabricated(self):
        path = self.vault / '02 Projects/getting-started/Practice.md'
        text = path.read_text()
        meta = app.frontmatter(text)
        self.assertEqual(meta['mastery'], 'unassessed')
        self.assertEqual(meta['stage_1'], 'planned')
        self.assertEqual(self.call('refresh'), 0, self.last_error)
        self.assertEqual(path.read_text(), text)
        self.assertNotIn('/5', (self.vault / '00 Dashboard/学习工作台.base').read_text())

    def test_invalid_results_and_dates_are_rejected(self):
        self.assertEqual(self.call('record', str(self.session(date='2026-02-30'))), 1)
        self.assertEqual(self.call('record', str(self.session(tests=[{'result': 'assumed'}]))), 1)


if __name__ == '__main__':
    unittest.main()
