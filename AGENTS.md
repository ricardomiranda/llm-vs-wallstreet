# Project instructions

## Python environment

Every Python script in this project must run inside the project virtual environment `.venv/`.

- Use `.venv/bin/python` explicitly (for example `.venv/bin/python scripts/bumpversion.py patch`).
- Activate `.venv` (`.venv/bin/activate`) when running several commands in a row.
- Never run project Python with the system interpreter: no bare `python`, `python3`, `pip`, or `mypy`.
- `.venv/` is git-ignored. It is disposable and must never be committed.

### Setup

`.venv` is provisioned by the project scripts themselves. To create or repair it:

```bash
python3 -c "import sys; sys.path.insert(0,'scripts'); from project_env import ensure_venv, repo_root; print(ensure_venv(repo_root()))"
```

That creates `.venv` and installs `requirements-dev.txt`. To install dependencies directly:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```

`.venv` creation requires the system package `python3.12-venv` (`sudo apt install python3.12-venv`).

## Dependencies

- `requirements-dev.txt` is the single source of truth for development dependencies. Keep it in sync with what the project actually needs.
- `scripts/project_env.py` holds `REQUIRED_MODULES`; every module listed there must be importable from `.venv`.

## Checks before committing

Run these from the project root:

```bash
.venv/bin/python -m mypy
.venv/bin/python scripts/pre_commit.py
```

Project Python must be fully type-annotated and pass `mypy --strict` (configured in `mypy.ini`).

## Versioning

This project uses **Semantic Versioning** (`MAJOR.MINOR.PATCH`) and releases from the default branch. Every change that lands must carry a version bump.

- **Every change that reaches `main` bumps the version.** No exceptions, including fixes and docs-only edits.
- Choose the level by intent, not by size:
  - `patch` — bug fixes, corrections, wording, refactors with no behaviour change.
  - `minor` — new features, new deliverables, new sections, architecture decisions that add capability.
  - `major` — breaking changes: removed or renamed public interfaces, changed output formats, changed config schema, anything that forces consumers to act.
- Bump only with `.venv/bin/python scripts/bumpversion.py patch|minor|major`. Never call the `bumpversion` console script, `python -m bumpversion`, or `bumpversion` directly, and never edit version strings by hand. The script re-executes itself inside `.venv` and updates `version.txt`, the version line in `README.md`, and `current_version` in `.bumpversion.cfg` together.
- `version.txt`, the version line in `README.md`, and `current_version` in `.bumpversion.cfg` are all updated together by that script. Do not edit any of them individually. If they ever disagree, the script is broken — fix the script, do not hand-patch the files.
- When several branches start from the same base, bump sequentially (`0.3.0` → `0.3.1`, then `0.3.2`) so the version files never collide.

## Git

This project is **trunk-based**: `main` is the single trunk, it is always releasable, and work lives in short-lived branches that are merged back and deleted.

- Branch from the latest default branch (`origin/HEAD`, normally `main`), never from another feature branch. No stacked branches.
- Keep branches short-lived: open, push, open a PR, merge, delete. Do not let feature branches linger.
- Delete a branch once it is fully merged. Suggest deletion; never delete an unmerged branch, and never use `git branch -D`.
- Merge through a pull request, never straight to `main` from a local branch.
- Never force-push, never rewrite history, never discard uncommitted work, never update git config.
- Every commit must reference one existing GitHub issue using `(#<issue-number>)` in its subject, for example `Fix price refresh handling (#42)`. Create an issue before starting work; split unrelated work across issues and commits.
- Name branches with the issue number, for example `feat/42-price-refresh` or `fix/43-cash-fx`.
- Every pull request must address one issue and include `Closes #<issue-number>` in its description. Keep the issue open until the PR is merged.
- Track issues through the repository's GitHub Project board when it is available.

Read `.opencode/commands/shared-git.md` before any branch, push, or cleanup work — it has the exact fast-forward, SSH-retry, and merged-branch cleanup procedure.
