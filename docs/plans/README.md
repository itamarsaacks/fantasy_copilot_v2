# Per-tab plan files

This directory holds one plan file per tab in the reformation roadmap.
Master plan: `~/.claude/plans/joyful-bubbling-dream.md`.

Each per-tab session opens via `/tab-session <tab>` which reads the plan
file for that tab (or drafts one if it doesn't exist yet) before any
work begins. See `.claude/skills/tab-session/SKILL.md`.

## Order tabs ship in

1. **chat-mentions** — wires the foundation primitives to existing chat.
   Smallest tab; proves the chips work end-to-end.
2. **players** — stresses the new game-log + drawer pipeline.
3. **games** — entirely net new. Highest visual payoff.
4. **my-team** — date toggle + simulator.
5. **league** — opponent drawer + standings on date.
6. **trades-waiver** — waiver planner calendar picker.

## Stub vs. full plan

Stub files exist for every tab so future sessions know where to start.
Each stub points to the master plan section for the tab and lists known
dependencies + acceptance gates. The session will flesh these into a
full plan during its own Phase 1 (Initial Understanding).
