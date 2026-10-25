---
name: technical-doc
description: Create concise, high-level technical documents that explain existing systems or proposed changes in simple language for readers who may not have prior context. Use for architecture explanations, infrastructure changes, implementation plans, features, bug fixes, migrations, refactors, and other technical proposals. Always generate and validate a DOCX file under ~/documents/technical-doc/.
---

# Technical Doc

Create a clear, high-level technical document that allows someone without deep context to understand and review a technical subject.

The document may describe:

- an existing implementation;
- a proposed feature;
- a bug fix;
- an architectural change;
- an infrastructure change;
- a migration or refactor;
- an implementation plan.

The goal is understanding and review, not exhaustive documentation.

The generated document should feel like a compact engineering review brief: Calibri body text, blue section headings, generous white space, a dark blue/gray system-flow palette, and restrained green/amber/red status colors. Prefer the visual language of `examples/async-booking-retry-plan.docx` when the subject benefits from a flow or schematic.

# Writing Style

Write as a human explaining the subject to another engineer who does not have the same context.

Prefer:

- concepts over implementation details;
- responsibilities over classes or methods;
- flows over individual functions;
- intent and reasoning over code mechanics;
- simple language over specialized terminology.

Default to a high level of abstraction.

Only mention specific methods, parameters, classes, files, tables, queues, or internal identifiers when they are important to understanding the design.

A useful rule:

**If removing a technical identifier does not reduce understanding, remove it.**

# Content

The reader should understand:

- what the problem or subject is;
- why it matters;
- what the system or proposal is trying to accomplish;
- how the main pieces fit together;
- how the main flow works;
- what is changing, when applicable;
- the most important architectural decisions or tradeoffs.

Do not expose implementation complexity merely because it exists.

# Suggested Structure

Adapt the structure to the subject.

A typical document may contain:

## Overview

One or two short paragraphs explaining the subject and its purpose.

## Context

Explain only the context necessary to understand the problem or proposal.

## How It Works / Proposed Approach

Explain the main flow or architecture as a simple narrative.

Focus on the major stages and responsibilities.

## Example

Use one concrete example when it materially improves understanding.

## Important Considerations

Include only meaningful constraints, risks, tradeoffs, or architectural decisions.

Do not create sections that add no useful information.

# Existing Systems

When documenting existing code or infrastructure, inspect enough of the implementation to verify how the system actually works.

Understand the implementation in detail internally, then compress it into a simpler model for the reader.

Do not invent missing behavior.

The agent should understand the complexity so the reader does not have to.

# Future Implementations

When describing future work, focus on intended behavior and architecture rather than a detailed coding checklist.

Explain:

- what will change;
- which major components are affected;
- how they will interact;
- what the expected behavior will be;
- important architectural decisions;
- important tradeoffs or constraints.

Avoid predicting internal implementation details that have not yet been decided.

# Diagrams

Include a simple diagram only when it materially improves understanding.

Prefer diagrams showing:

- major components;
- system boundaries;
- data flow;
- execution flow;
- before/after architecture.

Keep diagrams high level.

Do not reproduce every service, method, table, queue, or dependency.

Use the built-in diagram renderer for architecture, execution-flow, and before/after schematics. Put a JSON spec inside a fenced `diagram` block in the Markdown draft; the DOCX generator renders it to an embedded SVG automatically:

```diagram
{
  "layout": "flow",
  "title": "How a request flows",
  "pipeline": [
    {"id": "client", "label": "Client"},
    {"id": "queue", "label": "Work queue", "w": 300},
    {"id": "worker", "label": "Worker"}
  ],
  "branches": [
    {"label": "Healthy → complete → report succeeded", "variant": "green"},
    {"label": "Permanent problem → report failed with a clear reason", "variant": "red"},
    {"label": "Temporary failure → hold → retry after recovery", "variant": "amber"}
  ]
}
```

The renderer is also available directly when an image asset is needed outside a DOCX:

```bash
node <skill-dir>/scripts/create_diagram.js diagram.json diagram.svg
```

Prefer `"layout": "flow"` for the reference-style schematic: provide a semantic `pipeline` array and a `branches` array, and the renderer automatically creates the top row, vertical spine, fan-out arrows, and stacked outcome boxes. Use explicit coordinates only for unusual custom layouts. In explicit mode, nodes support `id`, `label`, `x`, `y`, `w`, `h`, and `variant` (`blue`, `green`, `amber`, `red`, or `gray`). Edges support `from`, `to`, optional `label`, and optional `via` points for routed lines. Keep labels short enough to remain readable at document width.

# Output

The final output MUST be a validated DOCX file.

Save documents under:

`~/documents/technical-doc/`

Create the directory if necessary.

Always create a new file.

Never overwrite an existing document unless explicitly requested.

Use:

`<descriptive-topic>-YYYYMMDD-HHMMSS.docx`

Example:

`~/documents/technical-doc/async-booking-proposal-20261024-221500.docx`

# Generation Workflow

Always follow this sequence.

## 1. Draft

Create the complete document as temporary Markdown.

The Markdown is an intermediate representation, not the final deliverable.

Keep it simple and compatible with the supported DOCX generator:

- `#` title;
- `##` and `###` headings;
- paragraphs;
- bullet lists;
- numbered lists;
- `**bold**`;
- inline `code`.
- GitHub-style pipe tables with a separator row.

Avoid Markdown features that the generator does not support.

## 2. Generate DOCX

Use the skill's generator:

```bash
node scripts/create_docx.js <input.md> <output.docx>
```

The generator supports the Markdown subset above, image references such as `![flow](flow.svg)`, GitHub-style tables, and fenced `diagram` JSON blocks. SVG diagrams are embedded with a real 2× PNG raster fallback generated by `scripts/rasterize_svg.swift`, so viewers that do not render SVG do not show a blank or soft image. On macOS, Swift/AppKit support is required for SVG input; PNG input remains available everywhere.

When invoking the script, resolve the path relative to this skill's directory rather than assuming the current working directory contains `scripts/`.

The output path MUST follow the naming and directory rules above.

## 3. Validate

After generation, always run:

```bash
python scripts/validate_docx.py <output.docx> --render
```

Resolve the validator path relative to this skill's directory.

Validation is mandatory.

When diagrams are present, also inspect the rendered page images if the environment provides a DOCX/PDF renderer. Check that labels are not clipped, the diagram fits within the page width, arrows point in the intended direction, and color variants remain distinguishable in grayscale.

The document is not considered successfully generated until validation passes.

## 4. Handle Validation Failure

If validation fails:

1. inspect the reported error;
2. fix the Markdown or generation issue;
3. regenerate the DOCX;
4. run validation again.

Do not deliver a document known to have failed validation.

Do not silently ignore warnings that indicate a meaningful content or rendering problem.

## 5. Clean Up

After successful generation and validation, remove temporary Markdown files unless they are useful for debugging or explicitly requested by the user.

# Failure Behavior

If the DOCX cannot be generated or validated, report the failure and its cause.

Do not silently fall back to another output format.

Do not claim success unless the final DOCX exists and validation has passed.

# Chat Response

Do not duplicate the document contents in chat.

After successful generation, respond with:

- the generated DOCX path;
- at most one short sentence describing the document.

# Guiding Principle

Prefer:

**a simple document that communicates the essential technical idea**

over:

**a complete document that exposes every implementation detail**

The document should be understandable in one reading by someone who did not participate in the implementation.
