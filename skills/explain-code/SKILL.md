---
name: explain-code
description: Analyze existing code and generate a concise, high-level standalone HTML explanation focused on the essential architecture, concepts, and data flow. Use when the user wants to quickly understand how a piece of code, feature, service, or system works without being overwhelmed by implementation details. Always write the result to ~/documents/explain-code/.
---

# Explain Code

Help the user build a simple and accurate mental model of existing code.

Explain the system as a human would explain it to another engineer seeing it for the first time.

Focus on:

- what the system is trying to accomplish;
- the main concepts involved;
- how information moves through the system;
- the major decisions or transitions;
- what happens when things succeed or fail.

Avoid implementation details unless they are necessary to understand the core idea.

# Output

Always create a new standalone HTML file under:

`~/documents/explain-code/`

Use:

`<descriptive-topic>-YYYYMMDD-HHMMSS.html`

Never overwrite an existing file unless explicitly requested.

Do not provide the full explanation in chat.

After generation, respond only with the generated file path and, if useful, one short sentence describing the subject.

# Required Structure

The output should contain four main parts.

## 1. Overview

Write one short paragraph that explains the system as a story.

Start from the user's or system's intent:

- What is trying to happen?
- Why does this flow exist?
- What are the main stages?

Prefer conceptual language.

For example, prefer:

> A booking request is placed on a queue so it can be processed reliably in the background. A consumer picks it up, determines which external system should handle it, attempts the booking, and records the final outcome so downstream systems know whether it succeeded.

Over:

> `scheduling_consumer` decodes `agent_id`, calls `Resolver.AscendClient`, invokes `Dispatch`, and claims `idempotency_key`.

Mention concrete function, method, parameter, class, or file names only when they are central to understanding the design.

## 2. Main Flow Diagram

Create one simple visual representation of the main flow.

The diagram should show concepts and responsibilities rather than implementation details.

Prefer nodes such as:

```text
Booking Request
      ↓
Queue
      ↓
Booking Worker
      ↓
Scheduling Logic
      ↓
External Booking System
      ↓
Outcome
```

Avoid exposing internal methods, helper functions, parameters, or every decision branch.

Keep the diagram small enough to understand at a glance.

Use Mermaid when appropriate.

## 3. Happy Path

Explain one successful end-to-end example in simple language.

Follow the journey of the request or data through the system.

Prefer:

```text
A booking request enters the queue.

→ A worker picks it up.
→ The correct booking system is selected.
→ The requested slot is checked.
→ The appointment is created.
→ The result is recorded.
→ A success event is published.
```

Avoid unnecessary parameter values, method names, IDs, and internal data structures.

Include a concrete implementation detail only when it explains an important concept.

## 4. Error Path

Explain one representative failure scenario.

Choose the error that best helps the user understand the architecture or behavior of the system.

Example:

```text
A booking request reaches the worker.

→ The requested slot is checked.
→ The slot is no longer available.
→ The booking is not created.
→ The failure is recorded.
→ A failure event is published.
```

Focus on what happens and why.

Do not enumerate all error types unless the user asks for them.

# Level of Abstraction

Default to a high-level explanation.

Prefer:

- concepts over identifiers;
- responsibilities over classes;
- flows over individual functions;
- transformations over parameter names;
- architectural boundaries over file structure.

Only move into implementation details when they are essential to answering:

- why the system behaves this way;
- where an important decision happens;
- which component owns a critical responsibility.

Do not introduce names such as function names, method names, parameters, tables, queues, or files simply because they exist.

A useful rule:

**If removing a technical identifier does not reduce understanding, remove it.**

# Analysis Rules

Inspect enough code to verify the real behavior before explaining it.

Understand the implementation deeply, but explain it simply.

Internally determine:

- entry point;
- main components;
- data flow;
- important decisions;
- external dependencies;
- side effects;
- final result.

Then compress that understanding into the smallest accurate mental model.

Do not invent missing behavior.

Clearly distinguish confirmed behavior from inference when necessary.

# Visual Style

Optimize for quick reading.

Use:

- light background;
- high contrast;
- generous spacing;
- one main diagram;
- short text blocks.

Avoid:

- dashboard-style layouts;
- large tables;
- many cards;
- dense diagrams;
- excessive labels;
- decorative elements;
- implementation-heavy annotations.

The page should feel like a visual explanation, not technical documentation.

# Guiding Principle

The agent should understand the code in detail so the user does not have to.

Prefer:

**simple explanation backed by deep analysis**

over:

**detailed explanation that exposes the complexity of the implementation**

The user should be able to open the file and quickly answer:

- What is this system doing?
- Why does this flow exist?
- What are the main stages?
- What happens when it works?
- What happens when it fails?
