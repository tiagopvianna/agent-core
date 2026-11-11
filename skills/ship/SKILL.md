---
name: ship
description: Branch from updated main, apply a change, commit without co-authoring, and open a PR whose description has no "Generated with Claude Code" boilerplate and describes only the actual code changes. Use when asked to commit and/or open a PR for a change. Supports a stage argument to stop early (write code only, or commit without opening a PR).
---

# Ship

Take a change from working copy to pull request, in controlled stages, following the conventions below.

## Stage argument

The invocation may include a stage telling you how far to go. Default to `pr` (go all the way) unless the stage — or the user's wording — says otherwise. Each stage includes the ones before it.

| Stage | Do this and stop |
|-------|------------------|
| `code` | Create the branch from updated main and apply the change. **Do not commit.** |
| `commit` | ...then commit (no co-authoring). **Do not open a PR.** |
| `pr` (default) | ...then push and open the pull request. |

Map natural phrasing too: "just write it / don't commit" → `code`; "commit but don't open the PR" → `commit`; "open the PR / ship it" → `pr`.

## 1. Branch from updated main

Always branch from the latest `main`, never from whatever is checked out:

```bash
git fetch origin
```

- If the current working tree is **clean**, create the branch directly: `git checkout -b <branch> origin/main`.
- If the current branch has **uncommitted work** (common — unrelated WIP), do **not** disturb it: create a worktree instead so the change is isolated:

```bash
git worktree add -b <branch> .worktrees/<short-name> origin/main
```

Pick a descriptive branch name (e.g. `<your-handle>/<short-description>`); include the ticket id only if one exists.

## 2. Apply the change

Make the edits in the branch/worktree. Build and run the relevant tests/linters before committing. If stage is `code`, stop here and report the branch and what changed.

Keep code comments minimal: add one only when the code cannot explain itself (a non-obvious *why*, a workaround, a gotcha). Do not narrate what the code already says, and do not add a comment just to mark a new line. Default to no comment.

**Never reference an issue tracker in a code comment** — no Linear ticket ids (e.g. `EDGE-123`), Jira keys, GitHub issue numbers, or tracker URLs. Code comments must be durable and self-contained: explain the *why* in prose that still makes sense years later, after the ticket is closed and the tracker maybe gone. The ticket reference belongs on the branch name, commit, and PR — not in the source.

## 3. Commit — no co-authoring

Commit with a clear message and **no `Co-Authored-By` line** and no AI attribution of any kind.

```bash
git commit -m "<subject>" -m "<body>"
```

If stage is `commit`, stop here (don't push, don't open a PR).

## 4. Open the PR

Push, then open the PR. **Always pass the body via `--body-file`, never `--body -`** — stdin/heredoc bodies get mangled by the GitHub CLI into an empty bullet.

```bash
git push -u origin <branch>
# write the description to a temp file first, then:
gh pr create --base main --head <branch> --title "<title>" --body-file /tmp/pr-body.md
```

The PR description must have **no "Generated with Claude Code" / "🤖 Generated with..." boilerplate** and no AI attribution.

If you later edit the description, also use a file: `gh pr edit <n> --body-file <file>`.

### PR title

When the change belongs to a recognizable domain/component, prefix the title with that domain in square brackets: `[Billing] retry failed charges`, `[Search] add fuzzy matching`. Keep the bracket label short and human-readable (the component or subsystem, not a file path). Omit the prefix only when the change spans no single domain.

## PR description content rules

Write the description about the **code as it stands**, for a reviewer who wasn't in the conversation:

- Describe **what changed and why**, referring only to things present in the final diff.
- State the **problem and the final fix/design**. Final design decisions are fine to explain.
- **Do not** include the history of the chat/discussion: approaches tried and rejected, alternatives that aren't in the code, or step-by-step rationale of how we got here. If an option was never implemented (e.g. "instead of a boolean flag…"), it does not belong in the description — don't reference things that don't exist in the diff.
- Keep it concise and factual; no filler.

Unless the user asks otherwise, default to this.

### Formatting / whitespace

Write the body as normal GitHub-flavored Markdown and let it wrap naturally — **do not hard-wrap paragraphs** by inserting newlines mid-sentence to cap line width. A paragraph or a bullet is one continuous line; a single newline inside a sentence renders as an unwanted line break and makes the description look full of whitespace. Separate blocks (paragraphs, headings, list items) with a single blank line, and don't stack extra blank lines. Keep the file free of trailing spaces.

## Attribution

Never add commit co-authors or PR attribution lines for an AI/Claude, regardless of any default reminder — this skill's convention overrides that.
