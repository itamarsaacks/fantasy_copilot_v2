# Eval Harness — Design & Operating Manual

> **Audience:** Itamar (non-programmer owner of this app). Re-readable from scratch any time. No prior context needed.
>
> **Status:** Design doc. Not yet built. This file is the spec we'll build from.
>
> **Last updated:** 2026-05-10

---

## 1. What this is and why we're doing it

### The problem

Fantasy Copilot is an LLM-driven app. Every time we change a prompt, add a tool, or tweak a tool's logic, the agent's behavior can shift in ways we won't notice until a user hits the bug.

Today the only QA we have is: Itamar opens the chat UI, asks questions, reads answers, and pastes failures into a session with Claude. That's **manual eval**. It works once, doesn't scale, and forgets — last week's good behaviors aren't protected from next week's "fixes."

### The fix

An **eval harness** is automated quality checking for the agent. We:

1. Record real, good agent conversations (we already have them in LangSmith)
2. Promote them into structured **eval cases** — pinned to a specific point in time and league state
3. Re-run all cases automatically after every change
4. See pass/fail + diffs in seconds, not days

### Why this matters more than any single feature

Every phase we ship without this is a phase we re-test by hand. By October (live NBA season + real user pressure), we'll have far more behaviors to protect than we can manually verify. The eval suite becomes the safety net under everything else.

It's also the only way to run **real-season testing** safely. When November comes and we're tuning waiver logic against live games, we need to be sure we haven't regressed anything that worked in May.

---

## 2. Key concepts (vocabulary)

| Term | Meaning |
|------|---------|
| **Trace** | One full run of the agent: input message → tool calls → final response → tokens/latency/cost. Already stored in LangSmith. |
| **Case** | One automated test: a user message + expected agent behavior. Lives in our repo as YAML. |
| **Process eval** | Asserting on what the agent *did* (tools called, arguments, phrases avoided), not what it *said* (specific answer text). The harness is process-only. |
| **Assertion** | A check we make on the agent's output — e.g. "must call tool X", "response must mention 'continuous waivers'", "must not exceed 5 tool calls." |
| **Intent eval** | A specific assertion type: did the agent correctly understand what the user was asking? Usually checked by which tool it routed to. |
| **Run** | One full execution of all (or a subset of) cases at a moment in time. Produces a result row per case. |
| **Dataset** (LangSmith) | A LangSmith-managed collection of inputs + expected outputs. We mirror our YAML cases here so LangSmith's UI is also usable. |

---

## 3. Why LangSmith changes the design

We already have LangSmith capturing every real chat. That's a free, ongoing source of:

- The exact user message
- Every tool call and its arguments
- Every tool result
- The final agent response
- Tokens, latency, and cost per run

So we don't build a "recorder." We build a **promoter**: a tool that takes a LangSmith trace ID and converts it into a YAML eval case in our repo.

Workflow becomes:

> "I just had a good chat. Promote trace `abc123` into an eval case named 'asks_waiver_days_offseason'."

The harness fetches the trace, asks us a few questions about which assertions matter, writes the YAML, and now that conversation is a permanent regression test.

LangSmith also has its own evaluation primitives (Datasets + Experiments + scorers). We'll use them as the visualization layer alongside our own Postgres table — LangSmith's UI is great for browsing individual runs; our table is what powers the future custom dashboard.

---

## 4. How cases run — process eval, not content eval

The harness has one execution mode: **run the real agent against the live
local DB, capture what the agent did, assert on the process.**

There are no snapshots, no frozen state, no separate eval database. The
agent runs the same way it does in production. The eval validates **agent
behavior** — which tools it called, with what arguments, whether it
hallucinated forbidden phrases, whether it stayed within cost/latency budgets.
It does **not** validate the specific text of the agent's answer.

### Why process, not content

Every fantasy-copilot bug we've found or imagined reduces to one of four
shapes — and all four are testable without freezing state:

| Bug shape | How live mode catches it |
|-----------|--------------------------|
| Wrong tool called | `must_call_tools` / `must_not_call_tools` |
| Right tool, wrong arguments | `tool_call_args_contain` |
| Right calls, hallucinated synthesis | `response_contains_none` with specific never-OK phrases (e.g. "Dolphins" for the Bam Adebayo/Heat case) |
| Cost/latency drift | budget assertions (`max_tool_calls`, `max_latency_ms`, `max_cost_usd`) |

Asserting "the answer should be 41.7 fps" or "the user's rank is #2" is **not
the agent's job** — those values come from tools and the projection engine,
whose correctness is tested at the tool layer. The agent test verifies that
the agent **followed the right process** to produce the answer.

### When the agent runs

1. Runner discovers cases from `app/evals/cases/`
2. For each phrasing × repeat:
   - Generate a fresh thread_id so conversation memory doesn't leak
   - Build a config with the test user + league
   - Invoke `agent.ainvoke(...)` against the real DB
   - Capture every tool call (name + args + output preview) and the final response
3. Evaluate assertions on the captured trace
4. Report verdict per phrasing

The agent doesn't know it's in a test. Tools, prompts, LLM, projection cache —
everything is real.

### The load-bearing trick: `response_contains_none`

Because we don't assert specific content, all synthesis-level bugs ("agent said
the wrong thing") get caught via hallucination guards: phrases that should
**never** appear in a correct response. Examples:

- "Dolphins", "Cowboys", "Yankees" — NFL/MLB team names appearing in NBA context
- "I don't have", "I cannot access" — refusal patterns when the tool returned data
- "category coverage" — strategic framing wrong for points leagues

When we discover a new failure mode, the fix in eval terms is almost always
"add the offending phrase to the case's `response_contains_none` list." This
keeps the harness honest without reaching for frozen state.

### Why we don't use snapshots

We considered a `mode: snapshot` system (restore a frozen DB dump, pin
`AS_OF_DATE`, allow content-equality assertions) and decided against it. The
argument that retired the idea: every bug class we could imagine either
catches in live mode via the four shapes above, or it's a tool/engine bug
rather than an agent bug. Snapshots would have added significant machinery
(separate eval DB, capture script, restore plumbing, `EVAL_DATABASE_URL`
routing) to serve cases that don't actually exist.

If we ever discover a genuine need for frozen state later, the design is
captured in the git history at commit `ba9c7a6`. For now, all cases run live.

---

## 5. Architecture

```
┌────────────────────────────────────────────────────────────┐
│  LangSmith (already running)                               │
│  - Captures every real agent run                           │
│  - We pull traces from here to seed eval cases             │
└────────────────────────────────────────────────────────────┘
                       │
                       ▼ (promote good trace → YAML case)
┌────────────────────────────────────────────────────────────┐
│  backend/evals/                                            │
│  ├── cases/                  YAML eval cases (source of    │
│  │   ├── waiver_days.yaml    truth, version-controlled)    │
│  │   └── ...                                               │
│  ├── probes/                 Topic contracts (E4)          │
│  ├── runner/                 Python: invoke agent, check   │
│  │                           assertions, print verdicts    │
│  ├── promoter/               Python: trace → case YAML     │
│  └── reporters/              Console, JSON, Postgres       │
└────────────────────────────────────────────────────────────┘
                       │
                       ▼ (write results)
┌────────────────────────────────────────────────────────────┐
│  Postgres: eval_runs + eval_case_results tables            │
│  Source of truth for the future dashboard                  │
└────────────────────────────────────────────────────────────┘
                       │
                       ▼ (future)
┌────────────────────────────────────────────────────────────┐
│  Eval dashboard (UI)                                       │
│  - Pass rate over time                                     │
│  - Cost / latency per case                                 │
│  - Failure clustering                                      │
│  - Pass rate by intent dimension                           │
└────────────────────────────────────────────────────────────┘
```

---

## 6. Case format (the YAML spec)

Each case is one file. Plain YAML so Itamar can read and edit them.

```yaml
# evals/cases/manual/waiver_days_offseason.yaml

id: waiver_days_offseason
description: |
  User asks what their waiver days are. Agent should call get_league_rules,
  not search the web, and reference the league's waiver mechanism in plain
  English. Process-only assertions — the specific answer text varies by league.

# What the user types — either `user_message` (single) or `phrasings` (many)
phrasings:
  - "what are my waiver days"
  - "when do waivers process in my league"
  - "tell me my waiver schedule"
  - "how do waivers work here"

# Optional: prior turns to seed conversation memory
conversation_prefix: []

# Structured intent classification (used for dashboard slicing).
# Borrowed from the multi-dimensional intent taxonomy — lets us see
# "we pass 95% of definitional cases but only 70% of comparative ones."
intent:
  question_type: definitional         # definitional | procedural | comparative | conditional | recommendation | clarification_needed
  complexity: simple                  # simple | moderate | complex
  domain: rules                       # roster | waivers | trades | standings | news | rules | projections | matchups | meta
  answer_shape: explanation           # number | list | table | explanation | recommendation | clarification

# What success looks like
expected:
  # Tool routing (intent eval)
  must_call_tools:
    - get_league_rules
  must_not_call_tools:
    - search_recent_news    # this isn't a news question
    - get_free_agents

  # Response content (loose match — "any" passes if at least one hits)
  response_contains_any:
    - "continuous"
    - "daily"
    - "FAAB"

  # Response content (strict — must contain none)
  response_contains_none:
    - "I don't have"
    - "I'm not sure"
    - "I cannot"

  # Cost/efficiency
  max_tool_calls: 3
  max_latency_ms: 15000
  max_cost_usd: 0.05

# Free-form tags for additional dashboard filtering (orthogonal to `intent`).
# Use for cross-cutting concerns: "regression_8_7", "user_reported", "flaky", etc.
tags:
  - offseason
  - regression_8_7

# Where the case came from. `source: manual | promoted | generated`.
provenance:
  source: manual
  source_chat_date: 2026-05-08
```

### Intent taxonomy reference

The structured `intent` block is required on every case. Values:

| Field | Allowed values | Meaning |
|-------|---------------|---------|
| `question_type` | `definitional` | "what is X" — wants a fact or definition |
| | `procedural` | "how do I X" — wants steps |
| | `comparative` | "X vs Y" / "who's better" — wants a side-by-side judgment |
| | `conditional` | "if X then what" / "should I start him if Y" — wants reasoning under a hypothesis |
| | `recommendation` | "who should I pick up" / "what should I do" — wants an opinionated answer |
| | `clarification_needed` | The query is genuinely ambiguous; the right behavior is to ask back |
| `complexity` | `simple` | One tool, one fact, no reasoning |
| | `moderate` | 2-3 tools, light reasoning |
| | `complex` | Multi-step reasoning, multiple tools, synthesis |
| `domain` | `roster`, `waivers`, `trades`, `standings`, `news`, `rules`, `projections`, `matchups`, `meta` | Subject area |
| `answer_shape` | `number`, `list`, `table`, `explanation`, `recommendation`, `clarification` | Expected output form |

**Why this matters:** the dashboard slices on these. "Comparative + complex" cases are where the agent typically struggles. Without the taxonomy, we'd see one global pass rate and miss the structural weakness.

### Special case: clarification cases

When a query is genuinely ambiguous, the *correct* behavior is to ask back, not guess. These cases use `question_type: clarification_needed` + the `must_ask_clarification` assertion:

```yaml
id: ambiguous_pronoun_no_context
intent:
  question_type: clarification_needed
  complexity: simple
  domain: meta
  answer_shape: clarification

user_message: "is he good?"
conversation_prefix: []     # no prior turns — pronoun has no referent

expected:
  must_ask_clarification: true
  clarification_must_mention_any: ["who", "which player", "do you mean"]
  must_not_call_tools: [get_player_projection, find_player, compare_players]
  max_tool_calls: 0
```

Without these tests, the agent is free to silently guess at ambiguous queries and we'd never notice the regression.

### Assertion vocabulary (v1)

All assertions check **process**, not content. Two principles:

- Assertions on what the agent **did** (tool routing + arguments + cost) — direct checks.
- Assertions on what the agent **didn't say** (hallucination guards) — `response_contains_none` with specific never-OK phrases.
- Loose-OR'd vocabulary checks (`response_contains_any` with multiple terms) are fine because they tolerate state shifts: as long as ONE of the expected terms appears, the case passes.

| Assertion | Meaning |
|-----------|---------|
| `must_call_tools` | Every tool listed must appear at least once in the trace |
| `must_not_call_tools` | None of these tools may appear |
| `must_call_tools_in_order` | These tools must appear in this exact sequence |
| `tool_call_args_contain` | Specific arguments must appear in a specific tool call |
| `response_contains_any` | At least one of these strings appears (use loose-OR'd lists like `["continuous", "daily"]` — survives data shifts) |
| `response_contains_none` | None of these strings appear (the load-bearing hallucination guard: `["Dolphins", "I don't have", "category coverage"]`) |
| `must_ask_clarification` | Agent's response must be a clarifying question, not an answer attempt |
| `clarification_must_mention_any` | If asking for clarification, at least one of these phrases must appear |
| `max_tool_calls` | Total tool calls ≤ N |
| `max_latency_ms` | End-to-end time ≤ N ms |
| `max_cost_usd` | Total cost ≤ $X |
| `min_response_chars` | Response is at least N chars (catches "ok" responses) |
| `max_response_chars` | Response is at most N chars (catches over-explaining) |

We start with these. Add more only when we need them.

### What we deliberately don't assert

- **Specific response text** (e.g. `response_contains_all: ["#2"]`, regex). Brittle against shifting data. If you find yourself wanting this, the right move is almost always to convert it into a `response_contains_none` guard ("agent must NOT say X").
- **"Is this a good answer?" via LLM judge.** Adds cost + flakiness. Only added when string matching genuinely isn't enough.
- **Specific projection numbers, ranks, FAAB balances, or counts.** These belong in tool-layer tests, not agent-layer tests.

---

## 7. Result schema (Postgres tables)

This is the data the future dashboard reads. Designed once, written from day one.

### `eval_runs` — one row per harness invocation

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `started_at` | timestamp | When the run kicked off |
| `finished_at` | timestamp | When it completed |
| `git_sha` | text | Code version under test |
| `git_branch` | text | Branch name |
| `triggered_by` | text | "manual", "ci", "pre-commit" |
| `model` | text | LLM model used (e.g. claude-sonnet-4-6) |
| `total_cases` | int | Cases run |
| `passed` | int | Cases passed |
| `failed` | int | Cases failed |
| `errored` | int | Cases that crashed (not pass/fail) |
| `total_latency_ms` | bigint | Sum of case latencies |
| `total_cost_usd` | numeric | Sum of case costs |
| `notes` | text | Free-form note from operator |

### `eval_case_results` — one row per case per run

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `run_id` | UUID | FK to `eval_runs` |
| `case_id` | text | The case's YAML id (e.g. "waiver_days_offseason") |
| `passed` | bool | Pass/fail |
| `errored` | bool | True if the case crashed |
| `error_message` | text | Crash reason if errored |
| `failure_reasons` | jsonb | List of failed assertions, e.g. `[{"assertion": "must_call_tools", "expected": ["get_league_rules"], "actual": []}]` |
| `tool_calls` | jsonb | Full list of tool calls + args + outputs |
| `final_response` | text | What the agent said |
| `latency_ms` | int | End-to-end |
| `tokens_in` | int | Prompt tokens |
| `tokens_out` | int | Completion tokens |
| `cost_usd` | numeric | This case's cost |
| `langsmith_trace_id` | text | LangSmith trace ID for this run (raw ID for API queries) |
| `langsmith_trace_url` | text | Link to the LangSmith trace for this run (clickable URL) |
| `langsmith_thread_id` | text | LangSmith thread ID — groups multi-turn cases into one conversation thread |
| `agent_thread_id` | text | LangGraph thread ID used in the agent's checkpointer (links to `conversations` table) |
| `intent_question_type` | text | Copied from case `intent.question_type` (definitional / procedural / comparative / conditional / recommendation / clarification_needed) |
| `intent_complexity` | text | Copied from case `intent.complexity` (simple / moderate / complex) |
| `intent_domain` | text | Copied from case `intent.domain` (roster / waivers / trades / etc.) |
| `intent_answer_shape` | text | Copied from case `intent.answer_shape` (number / list / table / etc.) |
| `tags` | text[] | Free-form tags copied from case YAML for cross-cutting filtering |

**Why intent fields are dedicated columns (not just tags):** the dashboard's most useful slices are intent-driven ("pass rate by question_type", "cost by complexity"). Dedicated indexed columns make those queries fast and the schema self-documenting. Free-form `tags` covers everything else.

### What the dashboard can show with this

- Pass rate over time (line chart, x = `started_at`, y = `passed/total`)
- Pass rate by `intent_question_type` (definitional 95% / comparative 70% — reveals where the agent struggles)
- Pass rate by `intent_complexity` (simple vs complex — shows if the agent breaks down on multi-step reasoning)
- Pass rate by `intent_domain` (waivers 90% / trades 65% — surfaces weak subject areas)
- Clarification rate — % of `clarification_needed` cases where the agent correctly asked back instead of guessing
- Cost / latency per `intent_complexity` — confirms expensive cases are actually the complex ones, not simple ones bloating
- Cost trend per run, cost per case
- Latency p50/p95 per case
- "New regressions" — cases that passed last run but failed this run
- "Flaky cases" — cases that pass and fail intermittently
- Failure clustering — which assertion fails most often across cases?

---

## 8. Lifecycle (how this is used week to week)

### Capturing new cases

1. You have a real chat with the agent.
2. It does something well (or revealingly poorly).
3. You note the LangSmith trace URL.
4. You run `python -m evals.promoter <trace_id>`.
5. The promoter pulls the trace, asks 3-5 questions in CLI:
   - "Name this case?"
   - "Which tools were essential? (suggested: ...)"
   - "Any phrases the response must contain? (auto-extract suggestions)"
   - "Any phrases it must NOT contain?"
6. Writes a draft YAML to `evals/cases/`.
7. You review and tweak the YAML by hand.
8. Commit.

The harness grows organically from real usage.

### Running the harness

```bash
# Run all cases
./scripts/eval.sh

# Run a subset by tag
./scripts/eval.sh --tag intent

# Run one case
./scripts/eval.sh --case waiver_days_offseason

# Filter by intent.domain
./scripts/eval.sh --domain waivers
```

Output (console):

```
Running 32 cases...

✅ waiver_days_offseason          (1.2s, $0.008)
✅ trade_deadline_midseason       (2.1s, $0.014)
❌ ranks_team_strength_pointslg   (3.4s, $0.021)
   - response_contains_none failed: response contained "category coverage"
   - LangSmith: https://smith.langchain.com/...
✅ ...

30 / 32 passed (94%)
Total: 47s, $0.42
Run id: 8f3a... (logged to eval_runs table)
```

A failed assertion always includes a LangSmith link so you can inspect the full trace.

### CI integration (later)

Once stable, run on every commit. Block merges that drop pass rate below threshold.

---

## 9. Phased build plan

### Phase E0 — Foundation ✅ (committed 2026-05-12, c45acbe)

- Design doc (this file)
- Pydantic schema (`app/evals/schema.py`)
- YAML loader (`app/evals/loader.py`)
- Directory tree + first manual case
- Directory tree: cases/{manual,promoted,generated}/, probes/, runner/, digests/

### Phase E1 — Live runner ✅ (committed 2026-05-12, ba9c7a6 + 23a8ef0)

- Runner loads cases, invokes the real agent against the live local DB, captures tool calls + final response, evaluates assertions, prints pass/fail to console
- Severity tiers (critical / warning) and Verdicts (🟢/🟡/🔴/💥)
- Starter case + 5 more (roster, standings, trades, waivers, free agents, stat leaders)
- **24 / 24 phrasings passing**

### Phase E2 — Postgres results + LangSmith integration (½ session)

- `eval_runs` + `eval_case_results` tables + Alembic migration
- Runner writes results to Postgres
- Runner attaches LangSmith trace ID / URL / thread ID per result
- LangSmith Dataset mirror (push cases as a LangSmith dataset)
- Separate LangSmith project (`fantasy-copilot-evals`) so eval traces don't pollute prod

**Goal:** every run is queryable. Dashboard becomes possible.

### Phase E3 — Promoter (½ session)

- `python -m app.evals.promoter <trace_id>` script
- Pulls trace from LangSmith
- Interactive CLI to fill in assertion fields, suggests defaults
- Writes YAML draft to `cases/promoted/`

**Goal:** capturing new cases takes 2 minutes per chat instead of 20.

### Phase E4 — `eval-author` skill (1-2 sessions) — **the "no-manual-authoring" unlock**

- `app/evals/probes/` framework + first contract: `league_rules.py`
- `eval-author` skill that enumerates → applies contract → phrases → dry-runs → saves
- Generation uses Opus; agent under test stays Sonnet
- Weekly digest writer (`app/evals/digests/{date}.md`)
- 30 generated cases for `league_rules` topic seeded into the suite

**Goal:** `/author-evals --topic X` produces a usable case batch end-to-end. After this, you stop authoring cases by hand for any topic. See §13 for full design.

### Phase E5 — Dashboard (later, separate effort)

- Frontend page that reads `eval_runs` + `eval_case_results`
- Charts: pass rate over time, cost, latency, failure clusters
- Filters: intent dimensions, tag, case

---

## 10. What this catches vs doesn't (calibrate expectations)

### Catches well

- **Wrong tool routing** — via `must_call_tools` / `must_not_call_tools`
- **Wrong tool arguments** — via `tool_call_args_contain`
- **Hallucinated phrases** ("Adebayo plays for the Dolphins") — via `response_contains_none`
- **Strategy framing regressions** ("category coverage" in a points league) — via `response_contains_none`
- **Cost / latency / over-tool-use regressions** — via budget assertions
- **Tool-not-called-when-needed** — agent answering "what are my waiver days" from training data instead of calling the tool
- **Ambiguous-query handling** — via `must_ask_clarification` (agent shouldn't guess)

### Catches partially

- **Quality of writing** — only via length bounds and key-phrase presence. Doesn't judge prose.
- **Recommendation correctness** — we can check the agent called the right tools and didn't hallucinate, but "is this the right trade?" is judgment, not a test.

### Doesn't catch

- **Novel failures** — only catches regressions of behaviors we've encoded.
- **Tone / personality** — needs LLM-as-judge, deferred until needed.
- **End-to-end UI bugs** — this tests the agent, not the chat UI rendering.
- **Specific factual values** (rank, FPS, FAAB balance, schedule counts) — these belong in tool-layer tests. The agent layer only verifies the agent followed the right process to expose those values.

---

## 11. Open decisions (things we'll figure out as we build)

- **LangSmith Datasets vs our YAML — which is source of truth?** YAML in repo. LangSmith Dataset is a mirror, regenerated from YAML on each run.
- **Run frequency?** Manual at first (after big changes). CI integration once it's stable and fast.
- **LLM-as-judge scoring?** Deferred. Add only when a class of failure can't be checked with string matching.

### Resolved (2026-05-10)

- ~~Manual case authoring vs automated generation~~ → **Hybrid.** Generated covers behavior at scale, promoted covers high-value real-chat cases. See §13.
- ~~Should the same model author and run cases?~~ → **No.** Author = Opus, agent under test = Sonnet, to break self-reference bias.
- ~~Zero-monitoring vs full-monitoring~~ → **Weekly digest** is the floor. ~5 min/week of human attention. See §13.

### Resolved (2026-05-12)

- ~~Do we need snapshots / frozen DB state?~~ → **No.** Every bug class we could imagine reduces to wrong-tool, wrong-args, or hallucinated synthesis — all catchable in live mode against shifting data. Snapshots would have added significant machinery (separate eval DB, capture script, `EVAL_DATABASE_URL` plumbing) for use cases that don't exist. The harness is **live-only**. See §4.
- ~~Are content-equality assertions (`response_contains_all`, `response_matches_regex`) ever useful?~~ → **No.** Removed from the vocabulary entirely. The agent test verifies process, not specific content. Hallucination guards via `response_contains_none` handle synthesis-level bugs without needing frozen state.
- ~~Where does ground truth come from for generated cases?~~ → **From the topic contract**, not from DB queries. Each topic hard-codes: which tool(s) the agent must call, what vocabulary the response should reference, what phrases must NEVER appear. See §13.

---

## 12. Glossary cross-reference

If you forget what a word means, search this file:

- "Trace" → §2
- "Case" → §2, §6
- "Process eval" → §4
- "Hallucination guard" (`response_contains_none`) → §4, §6
- "Assertion" → §2, §6
- "Verdict (PASS / SOFT_PASS / FAIL)" → §6
- "Severity (critical / warning)" → §6
- "Intent eval" → §2, §6
- "Run" → §2, §7
- "LangSmith Dataset" → §2, §3
- "Topic contract" → §13

---

## 13. Automated case generation (the `eval-author` skill)

§8 (Lifecycle) describes how a *human* promotes a real chat into a case — the **deep / high-touch** path: a few cases per week, hand-validated.

This section describes the **wide / hands-off** path: an automated generator that enumerates the topic space and writes hundreds of cases without human authoring.

### The hybrid model

| Source | Volume | What it tests | Authored by |
|--------|--------|---------------|-------------|
| **Generated** (this section) | high (100s) | Tool routing, hallucination guards, format, cost, behavior under paraphrase | Opus, via the skill |
| **Promoted** (§8) | low (~1/week) | Multi-turn flows, judgment-call behavior, recommendation framing — from real LangSmith traces worth locking in | Human, from a real chat |

Generated covers most of the agent's behavior surface — every well-formed question gets covered. Promoted fills the gap where real-world judgment or multi-turn flow matters.

### The process-first principle

The generator only writes **behavior assertions**, never content assertions. It never asserts the agent's answer text against a specific value — that's the wrong layer.

What the generator can assert:

- `must_call_tools` — derived from a topic-to-tool mapping (e.g. waivers → `get_league_rules`)
- `must_not_call_tools` — sanity guards (e.g. don't call `search_recent_news` for a rules question)
- `response_contains_any` — loose-OR'd lists of expected vocabulary (e.g. for waivers: `["continuous", "daily", "FAAB", "claim", "process"]` — at least one must appear)
- `response_contains_none` — hallucination blacklist for the topic (e.g. for NBA team abbreviations: `["Dolphins", "Cowboys", "Yankees"]`)
- `must_ask_clarification` — for queries the generator marks as ambiguous on purpose
- Cost / latency / length budgets

What the generator **cannot** assert (since the whole harness is process-only):

- Specific numerical values (ranks, FPS, FAAB balance, schedule counts)
- Specific player names as a required answer
- Exact text matches

If a case calls for one of these, the right move is either:
- Rephrase it as a hallucination guard (e.g. "agent must NOT recommend a rostered player" instead of "agent must recommend Player X")
- Move the assertion down to the tool/engine layer, where it belongs

### What kinds of questions the generator covers

| Question class | Coverage | Why |
|----------------|----------|-----|
| "What are my waiver days?" | ✅ | Tool routing + topic vocabulary |
| "When is the trade deadline?" | ✅ | Tool routing + topic vocabulary |
| "Who's on team Foo?" | ✅ | Tool routing + must-not-hallucinate names |
| "Top 5 in rebounds" | ✅ | Tool routing + format (list/table) |
| "Should I trade Embiid for Sabonis?" | ✅ (behavior only) | Tool routing (`compare_players`) + must-not-hallucinate. **No verdict assertion.** |
| "Who should I pick up?" | ✅ (behavior only) | Tool routing (`get_free_agents` + `get_player_projection`) + must-not-recommend-rostered-player |
| "Is X having a good season?" | ✅ (behavior only) | Tool routing + must-cite-a-tool |

The generator covers every common question type — it just asserts on the **right things** (process), not on outputs we can't reliably predict.

### Self-reference mitigation

To reduce blind-spot alignment between author and agent:

- **Different model.** Generation uses Claude Opus. The agent under test runs Sonnet. Symmetric biases get broken.
- **Contract-grounded, not LLM-grounded.** Assertions come from a **topic contract** — a small Python module per topic that hard-codes "for this topic the agent must call tool X, must reference vocabulary Y, must never say Z." The generator LLM only writes paraphrasings and picks which contract to apply. It never invents what's correct.
- **Independent spot-checks.** Every Nth generated case is flagged for human review before it enters the regression suite.

### What the `eval-author` skill does

Invocation:

```
/author-evals --topic waivers --count 30
```

Pipeline per invocation:

1. **Enumerate** — load the topic's contract module. Walk the (question_type × complexity × answer_shape) taxonomy filtered to what the contract declares supported. Each cell becomes one case slot.
2. **Apply contract** — for each slot, copy the topic's hard-coded behavior assertions: `must_call_tools`, `must_not_call_tools`, vocabulary for `response_contains_any`, hallucination blacklist for `response_contains_none`, cost/latency budgets.
3. **Phrase** — call Opus to generate 3-5 paraphrasings of the user message. Variations cover: terse vs verbose, jargon vs plain English, full sentences vs fragments. All phrasings share the same assertions.
4. **Assemble** — write the case YAML with the structured `intent` block, `phrasings` list, the contract's assertions, `provenance.source: generated`.
5. **Dry-run** — execute every phrasing against the live local DB. Capture pass/fail.
6. **Verdict:**
   - All phrasings pass → save to `app/evals/cases/generated/{topic}/{case_id}.yaml`.
   - All phrasings fail → flag for human review. Likely a contract bug or a real agent regression — don't auto-commit.
   - Mixed → save the case but mark `provenance.flaky_at_generation: true` for follow-up.
7. **Log** — append a generation summary to `app/evals/digests/generation_{date}.md`.

The skill never overwrites cases under `cases/promoted/` or `cases/manual/`. Only `cases/generated/{topic}/` is generator-owned.

### Topic contracts

Each topic has one Python module that hard-codes its behavior contract:

```
app/evals/probes/
├── waivers.py          # waiver-related behavior contract
├── trades.py           # trade rules + deadline contract
├── roster.py           # roster composition contract
├── standings.py        # rank / points_for / FAAB contract
├── projections.py      # projection-tool behavior contract
├── league_rules.py     # playoffs / draft / scoring contract
├── stat_leaders.py     # top-N-by-stat contract
└── news_status.py      # injury / status / news contract
```

A contract exposes:

- `supported_intents() -> list[Intent]` — which question_type × complexity × answer_shape cells this topic covers
- `required_tools(intent) -> list[str]` — which tool(s) the agent must call for that intent
- `forbidden_tools(intent) -> list[str]` — tools that signal misrouting
- `expected_vocabulary(intent) -> list[str]` — loose-OR'd phrases for `response_contains_any`
- `hallucination_blacklist() -> list[str]` — never-OK phrases (e.g. NFL team names, "I don't have")
- `seed_prompts(intent) -> list[str]` — starting points for Opus to paraphrase from

Adding a new topic = writing one contract module (~50 lines). The skill picks it up automatically.

### Repeat / phrasings / multi-turn in the case YAML

The schema supports the three reliability dimensions discussed:

```yaml
# Paraphrase robustness
phrasings:
  - "what are my waiver days"
  - "when do waivers process"
  - "tell me my waiver schedule"
  - "claim window?"

# Flakiness detection — run each phrasing M times, expect 100% pass
repeat: 3

# Multi-turn / memory — prior turns seeded before the test message
conversation_prefix:
  - role: user
    content: "show me my roster"
  - role: assistant   # captured from a real run, used verbatim
    content: "Here's your roster: ..."
```

Each phrasing × repeat = one row in `eval_case_results`. So a case with 4 phrasings and repeat=3 produces 12 result rows. The dashboard rolls them up to per-case pass rate.

### Monitoring (the realistic floor)

You don't author cases. You don't run the harness manually. But "zero monitoring" produces noise. The realistic floor:

- **Daily cron** (or per-commit on main) runs the full suite
- **Weekly digest** auto-generated and saved to `evals/digests/{date}.md`:
  - Pass rate trend (last 7 runs)
  - New regressions (cases that flipped from pass → fail)
  - Newly-flaky cases (pass rate < 95%)
  - Cost / latency drift
  - Top 5 failing assertions across the whole suite
  - Direct LangSmith links to the worst failures
- **Hard alert** (email or Slack later) only on:
  - Pass-rate drop > 5% vs prior run
  - New errored case (crash, not assertion fail)
  - Cost spike > 25%

Reading the weekly digest is ~5 minutes. That's the floor of human involvement.

### Phasing (slots into §9)

The generator is Phase E4 — depends on the runner (E1 ✅) and result schema (E2).

---

## 14. Cost policy

Running evals costs LLM tokens. Without a policy this grows quietly until the
bill is uncomfortable. This section locks in the discipline.

### Cost components

| Component | Cost behavior |
|-----------|---------------|
| LLM (Anthropic Sonnet for agent under test) | Dominant. ~$0.005–$0.025 per agent run, prompt-cache dependent |
| LLM (Anthropic Opus for `eval-author` generation) | Paid only when generating cases, not when running |
| LangSmith ingestion | Free at our volume |
| Tavily (`search_recent_news`) | Real Tavily calls cost cents per query. Cases generally avoid it via `must_not_call_tools: [search_recent_news]`; when a news-status case genuinely needs it, accept the small per-call cost. |
| Postgres + local compute | Free |

**Prompt caching is the key lever.** The system prompt + tool definitions
(~3-4k tokens) are identical across every case. Deepagents caches by default —
after the first run in a batch, subsequent runs pay ~10% on the cached portion.
**Run cases in batches**, not one-at-a-time, to keep the cache warm.

### Projected cost per full-suite run

Assumes prompt caching on, no Tavily calls, Sonnet pricing.

| Stage | Cases | Avg phrasings × repeats | Runs | Cost / full suite |
|-------|-------|------------------------|------|-------------------|
| E1 launch ✅ | 6 | 4 × 1 | 24 | ~$0.30 (measured) |
| After E4 (first generated batch) | ~30 | 3 × 1 | 90 | ~$0.50–$1 |
| 3 months out | ~100 | 3 × 1 | 300 | ~$2–$3 |
| Mature suite (6+ months) | ~300 | 3 × 1.5 | ~1,400 | ~$10–$15 |

A single full-suite run is between pennies and ~$15 at maturity.

### Tiered run policy

The cost question is really "how often do we run it." The answer is:
not on every commit. Tier by risk and frequency.

| Tier | When | What runs | Mature cost / day | Why |
|------|------|-----------|-------------------|-----|
| **Smoke** | On every commit (CI, later) | Hand-picked subset (~5–10 cases) covering highest-risk paths | Pennies | Catches the worst regressions in 30s. Most commits don't touch agent behavior; full suite is wasted. |
| **Domain-filtered** | During active development | `eval.sh --domain waivers` if you're working on waivers | ~$0.50 / run | Tight feedback loop, no need to run unrelated cases |
| **Full suite** | Nightly cron + on-demand before any agent/prompt change merges to main | All cases × all phrasings × repeat | ~$10–$15 / day | Safety net. Produces the data feeding the weekly digest. |
| **Flakiness sweep** | Manual, ad-hoc when a case is suspected flaky | One case × phrasings × repeat=10 | ~$1 / sweep | Targeted diagnosis, not part of standard cadence |

### Levers if costs grow uncomfortable

- **Repeat=1 by default.** Increase only on cases under flakiness investigation.
- **Skip `generated/` cases on smoke tier**, run them only nightly. `promoted/` and `manual/` (curated, high-value) stay on smoke.
- **Per-domain smoke selection**: keep 1–2 representative cases per intent.domain on the smoke tier; the rest only nightly.
- **Skip generated cases that aren't currently exercised.** If a topic's feature isn't shipping yet, mark those cases inactive instead of running them on every cron.
- **Stop running cases with `repeat>1`** when investigation completes — flakiness sweeps are scoped, not standing.

### What NOT to do (anti-patterns)

- **Don't substitute Haiku for the agent under test.** The eval must hit the real production model. Cheaper-model evals lie.
- **Don't disable evals because they cost.** A missed regression in production costs more than running the suite. The threshold for "too expensive" is when token spend crosses ~5% of total LLM spend; well below that, keep running.
- **Don't run on every commit assuming it's "free."** Caching helps but doesn't eliminate cost. Multiply commits/day × full-suite cost before flipping that switch.

### When to revisit this section

- When `eval_runs` token spend in a month exceeds 5% of total Anthropic spend
- When mature-suite cost projection exceeds $50/day
- When the smoke tier grows past ~15 cases (it shouldn't; trim it)
- When we add expensive-per-call tools (e.g. real-time NBA APIs) that bypass the standard tool cost profile

---

## How to keep this doc useful

- Update §11 (Resolved) every time a major open decision lands.
- Update §6 (assertion vocabulary) every time we add an assertion type.
- Don't delete the "deferred" or "open decisions" sections — they're reminders of things we chose NOT to do, which matters as much as what we did.
