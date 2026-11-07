# Initial public release

2026-11-07 · LearnVault

- Extracted a subject-independent learning workflow with configurable vault path and timezone, arbitrary topics, and multiple projects.
- Created a clean starter vault; no imported personal notes, execution history or conversations.
- Added deterministic per-project QuickAdd menus, lightweight practices, separate execution/learning views, knowledge review and activity-day indexes.
- Retained configuration merging, local backups, release-asset hashing and preservation of existing plugin data.
- Added an original README banner, contributor guide, source/license notice and GPL-3.0-only license text.

Validation performed locally:

- `make check`: 26 unit tests passed and 16 Markdown notes validated.
- `python3 scripts/obsidian_setup.py install`: passed after verifying pinned asset digests against official GitHub Release metadata.
- `python3 scripts/obsidian_setup.py apply`: passed in the independent starter vault.
- `python3 scripts/obsidian_setup.py --skip-app-check check --require-content`: passed.
- Obsidian 1.15.0 reading view: four Home actions rendered; project/heading selection and actual QuickAdd capture succeeded. Multiline observation and fenced evidence landed in the selected stage; stage properties and mastery were unchanged. Temporary QA content was removed.
- Native Bases query: the learner-session view was empty, excluding templates as intended. No runtime errors captured.

CI adds macOS, Linux and Windows coverage on Python 3.10 and 3.13. Those platform runs are separate from the local checks above. Firmware and embedded tools are outside this project.

Generated execution archive: [release-session.md](release-session.md). This records Agent work, not a learner assessment.
