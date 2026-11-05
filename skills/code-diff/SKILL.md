---
name: code-diff
description: Generate a standalone HTML dashboard that shows a pull request or branch diff with each hunk placed side-by-side with a plain-language annotation explaining it (what a new function does, what changed, what was removed), plus an optional call-flow diagram. Use when someone wants to review or understand a diff quickly, correlate code changes to explanations, or share an annotated review artifact. Always write the result under ~/documents/code-diff/.
---

# Code Diff Dashboard

Turn a git diff into a single self-contained HTML page that a reviewer can skim: the real
color-coded diff on the left, and a short explanation of each change aligned on the right.

The goal is **correlation** — the reader should see a hunk and, right next to it, what that
hunk does and why. Not a line-by-line restatement of the code; a concept-level note per change.

# When To Use

- Reviewing or explaining a PR / branch before merge.
- Producing a shareable, annotated review artifact.
- Helping someone understand an unfamiliar change quickly.

# What It Produces

A standalone HTML file (no external assets) with:

1. **Header + summary** — title, branch/PR link, `+adds / -dels` stat, and one short paragraph
   stating the problem and the fix.
2. **Optional call-flow diagram** — one or two columns of boxes showing the sequence of calls the
   change introduces (e.g. a "save" path and a "restore" path), with new-in-this-change boxes
   highlighted and guard/branch boxes marked. Include it only when a flow materially helps. Give
   each node a `w` subtitle that names the **file or location** the call lives in and any key
   detail (the exact method, the condition, the data shape), and include the **surrounding steps**
   that frame the change — not only the new calls — so the path reads end to end and the reader
   can place each step in the codebase.
3. **Annotated diffs** — per file: a tag (core/test), path, counts, a one-line purpose, then each
   hunk rendered as a two-column row: the syntax-highlighted diff on the left, its annotation
   card(s) on the right. Hunks with no annotation (imports, context) show a muted marker.

# Writing The Annotations

Write them like a reviewer explaining the change to someone seeing it for the first time:

- One card per meaningful change (a new function, a changed block, a removal) — not per line.
- Say **what it does and why**, and note important edge cases or constraints, in plain language.
- Keep each card to a sentence or three. Prefer intent over mechanics.
- Mark each card `added`, `changed`, or `removed`.
- Do not annotate pure context or import hunks; let them render with the muted marker.

A useful rule: if a note just restates the code, cut it.

# Generation Workflow

Always follow this sequence.

## 1. Capture the diff

Write the raw unified diff to a temp file:

```bash
git -C <repo> --no-pager diff <base>...<head> > /tmp/<name>.diff
```

Use `<base>...<head>` (three dots) for a PR/branch review so the diff is against the merge base.

## 2. Build the spec

Write a JSON spec describing the titles, optional flow, and per-file annotations. Each annotation
carries an **anchor**: a substring that appears in the hunk it describes (usually the function
signature or a distinctive line). Anchors are how notes attach to hunks, and notes are ordered by
where their anchor appears in the hunk, so they line up with the code.

The example below is fictional — a "widget cache" PR — purely to show the spec shape:

```json
{
  "title": "PR #42 — cache widget lookups",
  "title_html": "optional HTML title (overrides title for display)",
  "subtitle_html": "repo · branch <code>...</code> · <a href=\"...\">#42</a>",
  "summary_html": "One short paragraph: the problem and the fix.",
  "lang": "go",
  "flow": {
    "title": "Call flow of the change",
    "columns": [
      {"title": "Read path", "nodes": [
        {"m": "GetWidget(id)", "w": "widget/service.go"},
        {"m": "if cache.Enabled", "w": "cold path falls through to the DB", "variant": "gate"},
        {"m": "cache.Lookup(id)", "w": "NEW · widget/cache.go · returns on hit", "variant": "new"}
      ]}
    ],
    "legend_html": "<b>Green</b> = new in this change."
  },
  "files": {
    "widget/cache.go": {
      "tag": "core",
      "purpose": "New in-memory lookup cache fronting the widget store.",
      "notes": [
        {"kind": "added", "name": "Lookup(id)",
         "desc": "Returns a cached widget on hit; reports a miss so the caller falls back to the store.",
         "anchor": "func (c *Cache) Lookup"}
      ]
    }
  }
}
```

Notes:
- `tag` is a free short label; use `"test"` to get the amber test styling, anything else gets the
  blue core styling.
- `variant` on a flow node is `"new"` (highlighted), `"gate"` (branch/guard), or omitted (plain).
- `lang` selects syntax highlighting. `"go"` is implemented; other values fall back to generic
  string/number/comment coloring only (no keyword/function coloring). To add a language, extend
  `LANGS` in the script with its keywords, types, and line-comment token.

## 3. Render

```bash
python3 <skill-dir>/scripts/generate_diff_dashboard.py \
  --diff /tmp/<name>.diff --spec /tmp/<name>.spec.json \
  --out ~/documents/code-diff/<descriptive-topic>-YYYYMMDD-HHMMSS.html
```

Resolve the script path relative to this skill's directory. Create `~/documents/code-diff/` if
needed. Always create a new file; never overwrite an existing one unless asked. Name it
`<descriptive-topic>-YYYYMMDD-HHMMSS.html`.

## 4. Verify

Open the file (or screenshot it with headless Chrome) and check: diff lines are tightly spaced
(no blank gaps), annotations sit beside the hunks they describe and in code order, syntax colors
are legible over the green/red backgrounds, and the flow arrows point the intended way.

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --screenshot=/tmp/preview.png \
  --window-size=1240,3000 --hide-scrollbars "file://<abs-path>.html"
```

## 5. Clean up

Remove the temp `.diff` and `.spec.json` after a successful render.

# Chat Response

After generation, respond with the generated HTML path and at most one short sentence. Do not
paste the dashboard contents into chat.

# Guiding Principle

Prefer **a page where each change sits next to a clear reason for it** over a page that merely
recolors the diff. The reader should be able to answer, for every hunk: what does this do, and why.
