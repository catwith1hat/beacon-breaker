# URGENT — Subagent fan-out prompts

This file collects self-contained work prompts for parallelizing audits
across multiple subagents (or sessions). Each prompt should be a complete
brief: what to research, which clients to touch, what to write.

When fan-out helps:
- A surface naturally splits per-client (e.g. "audit each client's BLS
  library bindings independently") and per-client work is large.
- A class-of-bug sweep across many similar predicates (e.g. "find every
  `assert` in `process_epoch` for each client").

When fan-out does **not** help:
- A single linear hypothesis where each step depends on the previous.
- Cross-cut composition audits — the synthesis is the hard part.

## Open prompts

_None._

## Completed / archived prompts

_None._
