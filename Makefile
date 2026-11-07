PYTHON ?= python3
.DEFAULT_GOAL := help
.PHONY: help check learn-check learn-record learn-refresh learn-review obsidian-check obsidian-install obsidian-apply
help:
	@echo 'make check | learn-refresh | learn-record SESSION=.learning/session.json'
	@echo 'python3 scripts/learning.py project my-topic --title "我的主题"'
	@echo 'make obsidian-install | obsidian-apply | obsidian-check'
check learn-check:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
	$(PYTHON) scripts/learning.py validate
learn-record:
	@test -n "$(SESSION)" || { echo 'Set SESSION=.learning/session.json'; exit 2; }
	$(PYTHON) scripts/learning.py record "$(SESSION)"
learn-refresh:
	$(PYTHON) scripts/learning.py refresh
learn-review:
	@test -n "$(NOTE)" || { echo 'Set NOTE="99 Inbox/note.md"'; exit 2; }
	$(PYTHON) scripts/learning.py review "$(NOTE)" --approve
obsidian-install:
	$(PYTHON) scripts/obsidian_setup.py install
obsidian-apply:
	$(PYTHON) scripts/obsidian_setup.py apply
obsidian-check:
	$(PYTHON) scripts/obsidian_setup.py --skip-app-check check --require-content
