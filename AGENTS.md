# Learning workflow contract

Read `vault/00 Dashboard/Workflow.md` before substantive work. When workflow.json changes the vault, use that path instead.

## End meaningful work with an archive

- Archive at the end of actual development or learning work, including failed or blocked attempts. Do not schedule daily runs. No new work, observation or result means no record.
- Use `python3 scripts/learning.py project <id> --title "Title"` for a new subject. Reuse an existing project when appropriate.
- Finish relevant checks, then write a JSON in ignored `.learning/`, following `docs/session.example.json`. Use a stable ID. An unchanged retry must reuse it.
- `actor: agent` for Agent work; `pair` only if the user participated, `human` only for user work. Record concrete changes, actual checks with passed/failed/not_run, sources, unresolved questions and a next step. Technical findings never imply user mastery.
- Run `python3 scripts/learning.py record .learning/<id>.json`, then `refresh` and `validate`. Mention the archive path in the final response. Never copy secrets, private chat, credentials or unfiltered logs.
- Reusable knowledge may be proposed in `99 Inbox` only if it adds value beyond existing notes. Use the Knowledge template with a unique id, topic, safe target, status draft, mastery unassessed, sources, one small exercise and one learner question. Link the execution record and draft in both directions.
- Only upon the user's explicit approval of a specific draft, run `review '99 Inbox/<note>.md' --approve`. Review does not change mastery. Preserve the learner's own wording and observations.

## Keep understanding independent

Never infer user understanding from Agent execution, an explanation, a passing test, note count, stage state or a Git commit. Do not fill learner record areas, tick personal completion boxes or change mastery without evidence the user personally supplied. Accept rough explanations and selected output; if needed ask one focused question at a time.

Full learner-facing steps belong in the vault. A practice stage should have purpose, operations, expectations/reasoning, and lightweight personal evidence/explanation/question. Support non-code subjects; no fixed topic enum or mandatory terminal commands.

## Changes to this workflow

Maintainers of the public template: keep your own development archives in a separate,
ignored `.learning/` workspace. Do not add them or their generated activity indexes
to the shipped sample vault. This does not change the workflow for people using their
own vaults; their archives belong in their own projects.

Run `python3 -m unittest discover -s tests` and `python3 scripts/learning.py validate`. Plugin-kit changes also require the local setup check if plugins are installed; report checks not run accurately. Preserve themes, custom QuickAdd choices, plugin review data and local settings. Meta Bind writes stage_N only; it must not update status/mastery/learner checkboxes. Keep templates out of activity views.

Never stage `.obsidian`, `.learning`, trash, plugin data.json, logs or secrets. Do not auto-commit or push unless the current user request authorizes it. Inspect staged changes before committing.
