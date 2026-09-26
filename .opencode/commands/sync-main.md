---
description: Fast-forward the local default branch to origin, then ask before checking out main or deleting merged branches (runs on a free opencode model)
model: opencode/mimo-v2.6-flash-free
---

# Sync main

Fast-forward the local default branch to match `origin`. This does not push feature branches and does not rewrite history.

Shared rules, SSH retry, fast-forward, and merged-branch cleanup: [shared-git.md](shared-git.md).

## Extra hard rules

- Run this command on a **free** opencode model. The `model` field in the frontmatter pins one; keep it on a model whose id ends in `-free` (see `opencode models`). Do not switch to a paid model.
- Do not stash, commit, or switch away from a dirty branch to make the sync work.
- Stay on the current branch unless it is already the default branch and the working tree is clean.
- **Never delete a branch or check out another branch without asking the user first.** Step 4 is a hard gate: ask, then wait.

## 1. Inspect

Run these in parallel:

- `git status -sb`
- `git branch --show-current`
- `git rev-parse --abbrev-ref origin/HEAD`
- `git rev-parse <default-branch> origin/<default-branch>` (after fetch if needed)

## 2. Fast-forward

Follow **Fast-forward local default branch** in [shared-git.md](shared-git.md).

## 3. Find merged-branch candidates

Run the candidate scan in [shared-git.md](shared-git.md) to get the list of fully merged local and remote branches. Exclude `<default-branch>`, `origin/HEAD`, and anything unmerged.

If the list is empty, skip to step 5.

## 4. Ask before touching anything

Do not delete a branch or switch branches on your own initiative. When step 3 found candidates, **ask the user** and wait for an answer.

Ask two things in one go:

1. **Check out `<default-branch>`?** Needed when a candidate is the current branch. Only offer it when the working tree is clean; if it is dirty, say why and do not offer.
2. **Delete the merged branches?** List each candidate and whether it exists locally, on `origin`, or both.

Offer these options:

- Check out `<default-branch>` and delete every candidate locally and on `origin`
- Delete every candidate locally and on `origin`, stay on the current branch
- Check out `<default-branch>` only, keep the branches
- Keep everything (no changes)

If the user has uncommitted work, say explicitly that checking out `<default-branch>` is safe only if nothing in the working tree would be lost, and let them decide. Never stash or commit to make a checkout possible.

After the user agrees, run exactly what they approved:

```bash
git checkout <default-branch>
git branch -d <branch> ...
git push origin --delete <branch> ...
```

Use `git branch -d`, never `-D`. Report each deletion. If a `git branch -d` refuses because the branch is not fully merged, leave it and report that instead of forcing it.

## 5. Report

State:

- current branch (unchanged unless it was a clean default branch, or the user approved a checkout)
- `<default-branch>` before → after (`git rev-parse --short`)
- whether it was already up to date, fast-forwarded, or blocked
- leftover dirty or untracked files, if any
- every branch deleted, and any candidate the user chose to keep
