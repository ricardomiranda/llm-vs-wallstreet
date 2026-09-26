# Project entry points. Every Python command runs inside .venv.
#
#   make help              list the available targets
#   make venv              provision .venv and install requirements-dev.txt
#   make check             type-check and run the pre-commit gate
#   make bump PART=minor   bump the project version

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY := .venv/bin/python
BUMP_SCRIPT := scripts/bumpversion.py
PART ?= patch
ARGS ?=

.PHONY: help venv deps mypy pre-commit check bump version clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
		| sed -E 's/^([a-zA-Z_-]+):.*## (.*)$$/\1\t\2/' \
		| sort \
		| awk -F'\t' '{printf "  %-12s %s\n", $$1, $$2}'

# Bootstrapping target. This is the one place a bare python3 is allowed: .venv
# does not exist yet, so it runs the provisioning helper the project ships.
venv: ## Provision .venv and install requirements-dev.txt
	python3 -c "import sys; sys.path.insert(0,'scripts'); from project_env import ensure_venv, repo_root; print(ensure_venv(repo_root()))"

deps: venv ## Ensure .venv exists and requirements-dev.txt is installed
	$(PY) -m pip install -r requirements-dev.txt

mypy: ## Type-check project Python (strict, per mypy.ini)
	$(PY) -m mypy

pre-commit: ## Run the pre-commit gate over staged project Python
	$(PY) scripts/pre_commit.py

check: mypy pre-commit ## Type-check and run the pre-commit gate

bump: ## Bump the version: make bump PART=patch|minor|major [ARGS=--dry-run]
	@case "$(PART)" in \
		patch|minor|major) ;; \
		*) echo "PART must be patch, minor or major (got '$(PART)')" >&2; exit 2 ;; \
	esac
	$(PY) $(BUMP_SCRIPT) $(PART) $(ARGS)

version: ## Print the current version
	@cat version.txt

clean: ## Remove caches and byte-code from project Python
	rm -rf .mypy_cache scripts/__pycache__
	find scripts -name '*.pyc' -delete
