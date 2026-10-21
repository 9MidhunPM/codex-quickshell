PYTHON ?= python3
.PHONY: check test lint privacy preview dry-run

check: test lint privacy

test:
	$(PYTHON) -m unittest discover -s tests -v
	node qml/test-format.cjs
	$(PYTHON) scripts/check_qml.py test

lint:
	$(PYTHON) -m compileall -q codex_status scripts
	$(PYTHON) scripts/check_qml.py lint
	git diff --check

privacy:
	$(PYTHON) scripts/check_privacy.py --history

preview:
	qs -p qml/preview.qml

dry-run:
	$(PYTHON) scripts/install.py --dry-run
