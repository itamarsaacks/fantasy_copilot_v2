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
| **Case** | One automated test: a user message + expected agent behavior + the snapshot it runs against. Lives in our repo as YAML. |
| **Snapshot** | A frozen point-in-time copy of league state (DB rows + recorded Yahoo API responses + a fixed date). Lets us replay "what if we asked this on Nov 15?" |
| **Replay** | Running the real agent against a snapshot. The agent's prompts and tools are real; only the data is frozen. |
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

## 4. Snapshot strategy (the date-pinning problem)

**The point:** the agent's correct answer to "should I start Embiid this week?" depends on whether "this week" is Week 5 of November or the off-season. We can't have one "right answer" — we need to test the same question against different snapshots.

### What a snapshot contains

```
snapshots/
  2025-11-15_midseason_normal/
    metadata.yaml            # date, league context summary, why this snapshot
    db.sql                   # dump of relevant DB tables at that date
    yahoo_responses/         # recorded Yahoo API JSON for every endpoint we hit
    news_cache.json          # snapshot of Tavily / news results
  2026-01-20_midseason_trade_deadline/
    ...
  2026-03-05_late_season_playoff_race/
    ...
  2026-04-18_offseason/
    ...
```

### How a snapshot is used

When a case runs:

1. The harness loads the snapshot's DB dump into a temporary Postgres schema
2. Sets `AS_OF_DATE` env var to the snapshot's date
3. Stubs Yahoo HTTP calls to read from `yahoo_responses/` instead of hitting the network
4. Stubs Tavily search to read from `news_cache.json`
5. Runs the agent against the user message
6. Captures every tool call + the final response
7. Tears down

The agent code itself doesn't know it's in a test. Tools, prompts, and the LLM are real. **Only the data is frozen.**

### How we build snapshots

Two ways:

**A. Live capture** (best when possible) — at any moment during the real season, run a script that:
- Dumps the relevant DB tables
- Records all Yahoo responses for that league for the next ~30 minutes of usage
- Tags the result with the date

**B. Backfill from LangSmith** — for past dates, scrape the tool inputs/outputs from existing traces to reconstruct what Yahoo returned at that time. Less complete but works for cases where we don't have a live capture.

### Snapshot library plan

| Snapshot | Purpose | When captured |
|----------|---------|---------------|
| `offseason_2026_05` | Current state. Off-season behavior. | Now |
| `preseason_2026_10` | Right before the season. Draft just done. | Oct 2026 |
| `early_season_2026_11` | Week 5-ish. Sample size building. | Nov 2026 |
| `midseason_2027_01` | Mid-season. Trade deadline approaching. | Jan 2027 |
| `late_season_2027_03` | Playoff push. Some teams tanking. | Mar 2027 |
| `playoffs_2027_04` | Fantasy playoffs active. | Apr 2027 |

We add snapshots as the season progresses. Cases declare which snapshot(s) they apply to.

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
│  ├── snapshots/              Frozen league states          │
│  │   ├── offseason_2026_05/                                │
│  │   └── ...                                               │
│  ├── runner/                 Python: load snapshot, run    │
│  │                           agent, check assertions       │
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
│  - Per-snapshot health                                     │
└────────────────────────────────────────────────────────────┘
```

---

## 6. Case format (the YAML spec)

Each case is one file. Plain YAML so Itamar can read and edit them.

```yaml
# evals/cases/waiver_days_offseason.yaml

id: waiver_days_offseason
description: |
  User asks what their waiver days are during off-season.
  Agent should call get_league_rules and answer with the league's
  waiver type, not search the web or hallucinate.

# Which snapshot this runs against. Can be a list to run on multiple.
snapshots:
  - offseason_2026_05

# What the user types
user_message: "what are my waiver days"

# Optional: prior turns to seed conversation memory
conversation_prefix: []

# Structured intent classification (used for dashboard slicing).
# Borrowed from the multi-dimensional intent taxonomy — lets us see
# "we pass 95% of definitional cases but only 70% of comparative ones."
intent:
  question_type: definitional         # definitional | procedural | comparative | conditional | recommendation | clarification_needed
  complexity: simple                  # simple | moderate | complex
  domain: league_rules                # roster | waivers | trades | standings | news | rules | projections | matchups | meta
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

# Provenance: which real trace did this come from
source_trace_id: ls_trace_abc123     # LangSmith trace ID
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

| Assertion | Meaning |
|-----------|---------|
| `must_call_tools` | Every tool listed must appear at least once in the trace |
| `must_not_call_tools` | None of these tools may appear |
| `must_call_tools_in_order` | These tools must appear in this exact sequence |
| `tool_call_args_contain` | Specific arguments must appear in a specific tool call |
| `response_contains_any` | At least one of these strings appears in the final response |
| `response_contains_all` | All of these strings appear |
| `response_contains_none` | None of these strings appear |
| `response_matches_regex` | Final response matches a regex |
| `must_ask_clarification` | Agent's response must be a clarifying question, not an answer attempt |
| `clarification_must_mention_any` | If asking for clarification, at least one of these phrases must appear (e.g. "which player") |
| `max_tool_calls` | Total tool calls ≤ N |
| `max_latency_ms` | End-to-end time ≤ N ms |
| `max_cost_usd` | Total cost ≤ $X |
| `min_response_chars` | Response is at least N chars (catches "ok" responses) |
| `max_response_chars` | Response is at most N chars (catches over-explaining) |

We start with these. Add more only when we need them.

### What we deliberately don't assert (yet)

- **Exact response text.** Too brittle.
- **"Is this a good answer?" via LLM judge.** Adds cost + flakiness. Only added when string matching genuinely isn't enough.
- **Numbers from projections.** Those are deterministic from the snapshot — if they drift, the projection engine changed, which is its own test concern.

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
| `snapshot_id` | text | Which snapshot was used |
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
- Per-snapshot health — does the agent do worse on midseason than offseason?
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
   - "Which snapshot does this represent?" (defaults to most recent)
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

# Run against a specific snapshot only
./scripts/eval.sh --snapshot midseason_2027_01
```

Output (console):

```
Running 32 cases across 2 snapshots...

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

### Phase E1 — Minimal harness (1 session)

- `evals/cases/` directory + YAML format
- One snapshot: `offseason_2026_05` (live capture from current DB)
- Runner that loads snapshot → runs agent → checks assertions → prints to console
- 5-10 starter cases hand-written from current real chats
- Pass/fail to console only (no DB yet)

**Goal:** prove the loop works end-to-end with one snapshot.

### Phase E2 — Postgres results + LangSmith integration (½ session)

- `eval_runs` + `eval_case_results` tables + Alembic migration
- Runner writes results to Postgres
- Runner attaches LangSmith trace URL to each result
- LangSmith Dataset mirror (push cases as a LangSmith dataset)

**Goal:** every run is queryable. Dashboard becomes possible.

### Phase E3 — Promoter (½ session)

- `python -m evals.promoter <trace_id>` script
- Pulls trace from LangSmith
- Interactive CLI to fill in assertion fields
- Writes YAML + commits draft

**Goal:** capturing new cases takes 2 minutes per chat instead of 20.

### Phase E3.5 — `eval-author` skill (1-2 sessions) — **the "no-manual-authoring" unlock**

- `evals/probes/` framework + first probe: `league_rules.py`
- `eval-author` skill that enumerates, grounds, phrases, dry-runs, saves
- Generation uses Opus; agent under test stays Sonnet
- Weekly digest writer (`evals/digests/{date}.md`)
- 30 generated cases for `league_rules` topic seeded into the suite

**Goal:** `/author-evals --topic X` produces a usable case batch end-to-end. After this, you stop authoring cases by hand for any factual topic. See §13 for full design.

### Phase E4 — Multi-snapshot support (1 session, when we have a 2nd snapshot)

- Snapshot loader generalizes
- Cases can declare multiple snapshots; runner expands one case → N runs
- Snapshot capture script

**Goal:** ready for the season — capture one snapshot per phase of the year, run cases across all of them.

### Phase E5 — Dashboard (later, separate effort)

- Frontend page that reads `eval_runs` + `eval_case_results`
- Charts: pass rate over time, cost, latency, failure clusters
- Filters: tag, snapshot, case

---

## 10. What this catches vs doesn't (calibrate expectations)

### Catches well

- **Hallucinated facts** ("Adebayo plays for the Dolphins") — via `response_contains_none`
- **Wrong tool routing** — via `must_call_tools` / `must_not_call_tools`
- **Strategy framing regressions** ("category coverage" suggested in points league) — via content assertions
- **Cost / latency regressions** — via budget assertions
- **Multi-turn memory failure** — via conversation prefix + content assertion
- **Tool-not-called-when-needed** — agent answering "what are my waiver days" from training data instead of calling the tool

### Catches partially

- **Quality of writing** — only via length bounds and presence of key phrases. Doesn't judge prose.
- **Numerical accuracy** — only catches specific numbers we choose to assert on. Drift in unasserted numbers won't be flagged.

### Doesn't catch

- **Novel failures** — only catches regressions of behaviors we've encoded.
- **Tone / personality** — needs LLM-as-judge, deferred until needed.
- **End-to-end UI bugs** — this tests the agent, not the chat UI rendering.

---

## 11. Open decisions (things we'll figure out as we build)

- **Should snapshots include real player names or anonymized?** Real for now. We're not publishing snapshots — they're internal test fixtures.
- **How often do we recapture snapshots?** Probably one per major season phase (preseason, early, mid, late, playoffs). Plus one ad-hoc snapshot any time we ship a feature that should be regression-tested at a specific moment.
- **LangSmith Datasets vs our YAML — which is source of truth?** YAML in repo. LangSmith Dataset is a mirror, regenerated from YAML on each run.
- **Run frequency?** Manual at first (after big changes). CI integration once it's stable and fast.
- **LLM-as-judge scoring?** Deferred. Add only when a class of failure can't be checked with string matching.

### Resolved (2026-05-10)

- ~~Manual case authoring vs automated generation~~ → **Hybrid.** Generated covers facts (deterministic GT only), promoted covers opinions. See §13.
- ~~Should the same model author and run cases?~~ → **No.** Author = Opus, agent under test = Sonnet, to break self-reference bias.
- ~~Zero-monitoring vs full-monitoring~~ → **Weekly digest** is the floor. ~5 min/week of human attention. See §13.
- ~~Where does ground truth come from for generated cases?~~ → **Snapshot DB queries**, never the LLM's opinion. Probes per topic.

---

## 12. Glossary cross-reference

If you forget what a word means, search this file:

- "Trace" → §2
- "Case" → §2, §6
- "Snapshot" → §2, §4
- "Replay" → §2, §4
- "Assertion" → §2, §6
- "Intent eval" → §2, §6
- "Run" → §2, §7
- "LangSmith Dataset" → §2, §3

---

## 13. Automated case generation (the `eval-author` skill)

§8 (Lifecycle) describes how a *human* promotes a real chat into a case. That's the **deep / high-stakes** path: a few cases per week, opinionated ground truth.

This section describes the **wide / low-stakes** path: an automated generator that enumerates the topic space, queries the snapshot DB for ground truth, and writes hundreds of cases without human authoring.

### The hybrid model

| Source | Volume | Ground truth quality | What it tests |
|--------|--------|----------------------|---------------|
| **Generated** (this section) | high (100s) | Deterministic only — restricted to facts computable from the snapshot | Tool routing, factual accuracy, hallucination, format, cost |
| **Promoted** (§8) | low (~1/week) | Opinionated — captured from real human-validated chats | Recommendations, multi-turn flow, judgment calls |

Generated covers ~70% of the agent's surface area. Promoted covers the rest.

### The deterministic-GT principle (non-negotiable)

The generator is allowed to produce cases ONLY when the answer can be computed directly from the snapshot. Concretely:

| Question class | Generator allowed? | How GT is obtained |
|----------------|-------------------|---------------------|
| "What's my rank?" | ✅ | `SELECT rank FROM teams WHERE user_id=...` against snapshot DB |
| "When is the trade deadline?" | ✅ | Read `settings_json.trade_end_date` |
| "Top 5 in rebounds last 30 days" | ✅ | Direct stats query against snapshot |
| "Project Embiid this week" | ✅ | Call projection engine directly with snapshot inputs |
| "Who's on team Foo?" | ✅ | Direct roster query |
| "Should I trade Embiid for Sabonis?" | ❌ | Opinion — no ground truth. **Promoted only.** |
| "Who should I pick up?" | ❌ | Strategy-dependent. **Promoted only.** |
| "Is he having a good season?" | ❌ | Subjective. **Promoted only.** |

If a topic has no deterministic answer, the generator either skips it or generates a **process-only case** (assertions on tool routing + hallucination guards, no answer-content assertion).

### Self-reference mitigation

To reduce blind-spot alignment between author and agent:

- **Different model.** Generation uses a stronger model (Claude Opus). The agent under test runs Sonnet. This breaks symmetric biases.
- **DB-grounded, not LLM-grounded GT.** Ground truth is computed by **querying the snapshot DB**, not by asking the generator LLM "what's the right answer." The generator only chooses *what to ask* and *what shape the assertion takes* — never *what's true*.
- **Independent spot-checks.** Every Nth generated case is flagged for human review before it enters the regression suite.

### What the `eval-author` skill does

Invocation:

```
/author-evals --topic waivers --snapshot offseason_2026_05 --count 30
```

Pipeline per invocation:

1. **Enumerate** — for the requested topic, walk the (question_type × complexity × answer_shape) taxonomy. Skip combinations that don't make sense for the topic.
2. **Ground** — for each cell, run a **ground-truth probe** against the snapshot DB. The probe is a small Python function per topic (e.g. `evals/probes/waivers.py`) that returns the deterministic facts needed: waiver type, waiver day, FAAB usage, max adds. Skip cells with no probe match.
3. **Phrase** — generate 3-5 paraphrasings of the user message. Variations cover: terse vs verbose, jargon vs plain English, full sentences vs fragments. All phrasings share the same ground truth and assertions.
4. **Assemble** — write the case YAML: structured `intent` block, `phrasings` list, `must_call_tools` (inferred from the topic-tool map), `response_contains_any` (built from ground truth), `response_contains_none` (built from a hallucination blacklist for that topic).
5. **Dry-run** — execute every phrasing against the snapshot. Capture results.
6. **Verdict:**
   - All phrasings pass → save the case to `evals/cases/generated/{topic}/{case_id}.yaml`.
   - All phrasings fail → flag for human review. Likely a generator bug or a real agent regression — don't auto-commit.
   - Mixed → save the case but mark `flaky_at_generation: true` for follow-up.
7. **Log** — write a generation summary to `evals/generation_runs/` (which topic, how many cases produced, which were flagged).

The skill never overwrites cases under `evals/cases/promoted/` or `evals/cases/manual/`. Only `evals/cases/generated/{topic}/` is generator-owned.

### Topic registry

The generator works per topic. Each topic has a small Python module:

```
evals/probes/
├── waivers.py          # ground-truth probes for waiver questions
├── trades.py           # trade rules + deadline
├── roster.py           # roster composition
├── standings.py        # rank, points_for, FAAB
├── projections.py      # per-player projections
├── league_rules.py     # playoffs, draft, scoring
├── stat_leaders.py     # top-N by stat
└── news_status.py      # process-only (no ground truth, only routing)
```

Each probe exposes:

- `enumerate_questions(snapshot)` — yields (intent_classification, ground_truth_facts) tuples
- `phrasings(question_template, facts)` — produces N paraphrasings
- `expected_tools(intent)` — which tool(s) the agent should call
- `hallucination_blacklist(facts)` — phrases that signal the agent made something up

Adding a new topic = adding one probe file. The skill picks it up automatically.

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

The original phased plan stays. Generator slots in at E3.5:

- **E1** — minimal harness, hand-written cases (still the foundation)
- **E2** — Postgres + LangSmith integration
- **E3** — promoter (real chat → case)
- **E3.5** — `eval-author` skill + first probe (`league_rules`) + first 30 generated cases. **This is the "I don't author cases" unlock.**
- **E4** — multi-snapshot
- **E5** — dashboard

E3.5 cannot ship before E1+E2: the generator depends on the runner and the result schema.

---

## How to keep this doc useful

- Update §4 (snapshot library) every time we capture a new snapshot.
- Update §6 (assertion vocabulary) every time we add an assertion type.
- Don't delete the "deferred" or "open decisions" sections — they're reminders of things we chose NOT to do, which matters as much as what we did.
