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

## 4. Run modes — live vs snapshot

This is the most important design decision in the harness. Get it wrong and
either tests are flaky (live state shifting under them) or the system is
bloated (snapshots forced on cases that don't need them).

### Two modes

| Mode | What the agent runs against | Allowed assertions | When to use |
|------|----------------------------|---------------------|-------------|
| **`live`** (default) | The actual local Postgres in whatever state it's in | Process only: tool routing, no-hallucination phrases, format, cost, length | Most cases. The case is testing **agent behavior**, not a specific factual answer. |
| **`snapshot`** | A restored point-in-time DB dump, `AS_OF_DATE` pinned | Process **plus** content-equality (specific numbers, names, rank) | Minority of cases. The case is testing a **specific factual outcome** that requires frozen state. |

### Why this matters

Most fantasy-copilot questions test behavior, not facts. Examples:

- "What are my waiver days?" — agent should call `get_league_rules`, not search the web. Whether the answer is "continuous" or "Tue/Fri" depends on the league. We assert on the **call**, not the answer.
- "Who should I pick up?" — agent should call `get_free_agents` + `get_player_projection`, shouldn't recommend a player not in the FA pool. The specific player it picks is judgment.
- "Compare A and B" — agent should call `compare_players`. The verdict text changes; the tool call is constant.

For all of those, the live DB is fine. We assert on what the agent **does**, not on what it **says**.

Snapshots only matter when the assertion needs frozen ground truth:

- **Regression tests** — "with this exact DB state, the agent should say X". Locks in a previously-fixed bug.
- **Numerical accuracy** — "if the snapshot has Embiid at 38.2 fps, the projection tool must return 38.2."
- **Date-sensitive logic** — "tonight's slate" depends on a frozen date.

These are ~10-20% of cases at maturity. Not the default.

### Snapshot mechanics (when we do use them)

```
snapshots/
  offseason_2026_05/
    metadata.yaml      snapshot_id, captured_at, as_of_date, test_user_email,
                       test_league_id, row counts, free-form note
    schema.sql         pg_dump --schema-only (creates tables)
    db.sql             pg_dump --data-only (populates tables)
```

When a `mode: snapshot` case runs:

1. Runner drops + recreates a separate Postgres database (`fantasy_copilot_eval`)
2. Restores `schema.sql`, then `db.sql`, into the eval DB
3. Sets `DATABASE_URL` to the eval DB + `APP_MODE=replay` + `AS_OF_DATE` from metadata
4. Imports + invokes the real agent (tools, prompts, LLM are all unchanged)
5. Captures tool calls + final response
6. Evaluates assertions
7. Tears down the eval DB

The agent doesn't know it's in a test. **Only the data is frozen.**

### How we build snapshots

A capture script (`scripts/eval_capture_snapshot.py`) dumps the live local DB:
schema + all application tables, minus the LangGraph checkpointer tables
(conversation memory shouldn't leak into eval runs). Output goes to
`backend/app/evals/snapshots/{snapshot_id}/`.

### Snapshot library plan

We capture snapshots **only when we need to lock in regression state**, not as
a rolling backup. So far:

| Snapshot | Purpose | Captured |
|----------|---------|----------|
| `offseason_2026_05` | Baseline off-season behavior. Seed for future regression cases. | ✅ 2026-05-12 |
| (future) `preseason_2026_10` | Right after draft. Captured when first numerical-accuracy case lands. | When needed |
| (future) `midseason_2027_01` | Trade deadline. Captured when first season-time bug needs locking in. | When needed |

We don't capture quarterly snapshots speculatively. Each snapshot exists
because at least one case requires it.

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
# evals/cases/manual/waiver_days_offseason.yaml

id: waiver_days_offseason
description: |
  User asks what their waiver days are. Agent should call get_league_rules,
  not search the web, and reference the league's waiver mechanism in plain
  English. Process-only assertions — the specific answer text varies by league.

# Run mode. Default is `live` (runs against the actual local DB).
# Use `snapshot` only when assertions need frozen ground truth.
mode: live

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

### Snapshot-mode variant

When a case needs frozen state (regression test, numerical accuracy, date-sensitive logic), declare the snapshot and unlock content-equality assertions:

```yaml
id: rank_after_week_5_freeze
description: |
  Regression: user reported the agent misreporting standings rank
  on 2026-11-15. Locks in the correct answer against that snapshot.

mode: snapshot
snapshot_id: midseason_2026_11_15

user_message: "what's my rank in the league"
intent:
  question_type: definitional
  complexity: simple
  domain: standings
  answer_shape: number

expected:
  must_call_tools: [get_league_summary]
  # Content-equality assertions — only legal in snapshot mode
  response_contains_all:
    - "rank"
    - "2"     # frozen ground truth: user is #2 in this snapshot
  response_contains_none: ["#3", "#4", "#5"]
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

Assertions split into two classes based on what they check:

- **Process assertions** — legal in both `live` and `snapshot` modes. They check what the agent *did*, not specific content.
- **Content-equality assertions** — legal in `snapshot` mode only. Asserting specific text against a live (changing) DB produces flaky cases. The runner rejects content-equality assertions on `live` cases at load time.

| Assertion | Mode | Meaning |
|-----------|------|---------|
| `must_call_tools` | both | Every tool listed must appear at least once in the trace |
| `must_not_call_tools` | both | None of these tools may appear |
| `must_call_tools_in_order` | both | These tools must appear in this exact sequence |
| `tool_call_args_contain` | both | Specific arguments must appear in a specific tool call |
| `response_contains_any` | both | At least one of these strings appears (use loose-OR'd lists like `["continuous", "daily"]` — works fine on live data) |
| `response_contains_none` | both | None of these strings appear (hallucination guards, e.g. `["Dolphins", "I don't have"]`) |
| `response_contains_all` | **snapshot only** | All of these strings appear — content-equality, requires frozen ground truth |
| `response_matches_regex` | **snapshot only** | Final response matches a regex — content-equality |
| `must_ask_clarification` | both | Agent's response must be a clarifying question, not an answer attempt |
| `clarification_must_mention_any` | both | If asking for clarification, at least one of these phrases must appear |
| `max_tool_calls` | both | Total tool calls ≤ N |
| `max_latency_ms` | both | End-to-end time ≤ N ms |
| `max_cost_usd` | both | Total cost ≤ $X |
| `min_response_chars` | both | Response is at least N chars (catches "ok" responses) |
| `max_response_chars` | both | Response is at most N chars (catches over-explaining) |

We start with these. Add more only when we need them.

### What we deliberately don't assert (yet)

- **Exact response text.** Too brittle even in snapshot mode.
- **"Is this a good answer?" via LLM judge.** Adds cost + flakiness. Only added when string matching genuinely isn't enough.
- **Specific projection numbers in live mode.** Numbers drift as the projection cache updates. Pin them via snapshot mode if you need to.

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
| `mode` | text | `live` or `snapshot` — copied from case YAML |
| `snapshot_id` | text | Which snapshot was used (NULL for `live` cases) |
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

### Phase E0 — Foundation ✅ (committed 2026-05-12, c45acbe)

- Design doc (this file)
- Pydantic schema (`app/evals/schema.py`)
- YAML loader (`app/evals/loader.py`)
- Directory tree + first manual case
- Snapshot capture script + first snapshot `offseason_2026_05`

### Phase E1 — Live-mode runner (1 session)

- Runner that loads `mode: live` cases, invokes the real agent against the live local DB, captures tool calls + final response, evaluates assertions, prints pass/fail to console
- Snapshot-mode path can be stubbed for now (raise NotImplementedError)
- Run the starter case `waiver_days_offseason` end-to-end (4 phrasings)
- Pass/fail to console only (no DB persistence yet)

**Goal:** prove the loop works end-to-end against live data. This is the load-bearing phase — everything after E1 builds on a working runner.

### Phase E2 — Postgres results + LangSmith integration (½ session)

- `eval_runs` + `eval_case_results` tables + Alembic migration
- Runner writes results to Postgres (including mode, snapshot_id where applicable)
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

### Phase E3.5 — `eval-author` skill (1-2 sessions) — **the "no-manual-authoring" unlock**

- `app/evals/probes/` framework + first contract: `league_rules.py`
- `eval-author` skill that enumerates → applies contract → phrases → dry-runs → saves
- Generation uses Opus; agent under test stays Sonnet
- Weekly digest writer (`app/evals/digests/{date}.md`)
- 30 generated cases for `league_rules` topic seeded into the suite

**Goal:** `/author-evals --topic X` produces a usable case batch end-to-end. After this, you stop authoring cases by hand for any topic. See §13 for full design.

### Phase E4 — Snapshot-mode runner + multi-snapshot support (1 session, when first snapshot-mode case lands)

- Runner implements snapshot restore (`fantasy_copilot_eval` DB, schema + data load)
- `EVAL_DATABASE_URL` + `APP_MODE=replay` + `AS_OF_DATE` plumbing
- Cases can declare multiple snapshots; runner expands one case → N runs

**Goal:** the regression-test subset becomes runnable. Ready for season-time content-equality cases.

### Phase E5 — Dashboard (later, separate effort)

- Frontend page that reads `eval_runs` + `eval_case_results`
- Charts: pass rate over time, cost, latency, failure clusters
- Filters: intent dimensions, tag, snapshot, case

---

## 10. What this catches vs doesn't (calibrate expectations)

### Catches well (live mode — most of the suite)

- **Wrong tool routing** — via `must_call_tools` / `must_not_call_tools`
- **Hallucinated phrases** ("Adebayo plays for the Dolphins") — via `response_contains_none`
- **Strategy framing regressions** ("category coverage" in a points league) — via `response_contains_none`
- **Cost / latency regressions** — via budget assertions
- **Tool-not-called-when-needed** — agent answering "what are my waiver days" from training data instead of calling the tool
- **Ambiguous-query handling** — via `must_ask_clarification` (agent shouldn't guess)

### Catches well (snapshot mode — the regression-test subset)

- **Numerical accuracy** — projection numbers, standings rank, FAAB balance frozen against snapshot
- **Date-sensitive logic** — "tonight's slate", "this week's matchup" pinned to a date
- **Locked-in regressions** — bug reported on a specific day, snapshot captures that DB state forever

### Catches partially

- **Quality of writing** — only via length bounds and key-phrase presence. Doesn't judge prose.
- **Recommendation correctness** — we can check the agent called the right tools and didn't hallucinate, but "is this the right trade?" is judgment, not a test.

### Doesn't catch

- **Novel failures** — only catches regressions of behaviors we've encoded.
- **Tone / personality** — needs LLM-as-judge, deferred until needed.
- **End-to-end UI bugs** — this tests the agent, not the chat UI rendering.
- **Drift in unasserted numbers** in live mode — if you care about a specific number staying constant, pin it via snapshot mode.

---

## 11. Open decisions (things we'll figure out as we build)

- **Should snapshots include real player names or anonymized?** Real for now. We're not publishing snapshots — they're internal test fixtures.
- **How often do we recapture snapshots?** Probably one per major season phase (preseason, early, mid, late, playoffs). Plus one ad-hoc snapshot any time we ship a feature that should be regression-tested at a specific moment.
- **LangSmith Datasets vs our YAML — which is source of truth?** YAML in repo. LangSmith Dataset is a mirror, regenerated from YAML on each run.
- **Run frequency?** Manual at first (after big changes). CI integration once it's stable and fast.
- **LLM-as-judge scoring?** Deferred. Add only when a class of failure can't be checked with string matching.

### Resolved (2026-05-10)

- ~~Manual case authoring vs automated generation~~ → **Hybrid.** Generated covers behavior at scale, promoted covers high-value real-chat cases. See §13.
- ~~Should the same model author and run cases?~~ → **No.** Author = Opus, agent under test = Sonnet, to break self-reference bias.
- ~~Zero-monitoring vs full-monitoring~~ → **Weekly digest** is the floor. ~5 min/week of human attention. See §13.

### Resolved (2026-05-12)

- ~~Are snapshots required for every case?~~ → **No.** Default is `live` mode — runs against the actual local DB, asserts on process only (tool routing, no-hallucination, format, cost). `snapshot` mode is opt-in for cases that need frozen ground truth (regression tests, numerical accuracy, date-sensitive logic). Most cases — ~80% at maturity — are `live`. See §4.
- ~~Are content-equality assertions (`response_contains_all`, `response_matches_regex`) always legal?~~ → **No.** Restricted to `snapshot` mode. Loader rejects them on `live` cases. Prevents flaky tests caused by asserting specific text against a live DB. See §6.
- ~~Where does ground truth come from for generated cases?~~ → **For live-mode generated cases (the default), ground truth = expected behavior, not expected content.** Snapshot DB queries only apply to the small minority of cases that need content-equality.

---

## 12. Glossary cross-reference

If you forget what a word means, search this file:

- "Trace" → §2
- "Case" → §2, §6
- "Mode (live vs snapshot)" → §4, §6
- "Process assertion vs content-equality" → §6
- "Snapshot" → §2, §4
- "Replay" → §2, §4
- "Assertion" → §2, §6
- "Intent eval" → §2, §6
- "Run" → §2, §7
- "LangSmith Dataset" → §2, §3
- "Topic contract" → §13

---

## 13. Automated case generation (the `eval-author` skill)

§8 (Lifecycle) describes how a *human* promotes a real chat into a case — the **deep / high-touch** path: a few cases per week, hand-validated.

This section describes the **wide / hands-off** path: an automated generator that enumerates the topic space and writes hundreds of cases without human authoring.

### The hybrid model

| Source | Volume | Default mode | What it tests | Authored by |
|--------|--------|--------------|---------------|-------------|
| **Generated** (this section) | high (100s) | `live` | Tool routing, hallucination guards, format, cost, behavior under paraphrase | Opus, via the skill |
| **Promoted** (§8) | low (~1/week) | `live` or `snapshot` as the original chat warrants | Multi-turn flows, judgment-call behavior, recommendation framing | Human, from real LangSmith trace |
| **Manual regression** | rare (as needed) | `snapshot` | Specific factual outcomes locked in against a frozen snapshot | Human, from a bug report or numerical regression |

Generated covers most of the agent's behavior surface — every well-formed question gets covered. Promoted and manual regression fill the gaps where real-world judgment or frozen state matters.

### The process-first principle

The generator defaults to `live` mode with **behavior assertions**, not content assertions. It never asserts the agent's answer text against a specific value — that would require frozen state, which is what `snapshot` mode is for.

What the generator can assert in live mode:

- `must_call_tools` — derived from a topic-to-tool mapping (e.g. waivers → `get_league_rules`)
- `must_not_call_tools` — sanity guards (e.g. don't call `search_recent_news` for a rules question)
- `response_contains_any` — loose-OR'd lists of expected vocabulary (e.g. for waivers: `["continuous", "daily", "FAAB", "claim", "process"]` — at least one must appear)
- `response_contains_none` — hallucination blacklist for the topic (e.g. for NBA team abbreviations: `["Dolphins", "Cowboys", "Yankees"]`)
- `must_ask_clarification` — for queries the generator marks as ambiguous on purpose
- Cost / latency / length budgets

What the generator **cannot** assert (would require snapshot mode + human curation):

- Specific numerical values
- Specific player names
- Exact text matches via `response_contains_all` or regex

This keeps generated cases stable across DB updates while still catching the failures that matter most (wrong tool, hallucinated team, missing topic vocabulary).

### What kinds of questions the generator covers

| Question class | Generator coverage | Why |
|----------------|---------------------|-----|
| "What are my waiver days?" | ✅ live | Tool routing + topic vocabulary |
| "When is the trade deadline?" | ✅ live | Tool routing + topic vocabulary |
| "Who's on team Foo?" | ✅ live | Tool routing + must-not-hallucinate names |
| "Top 5 in rebounds" | ✅ live | Tool routing + format (list/table) |
| "Should I trade Embiid for Sabonis?" | ✅ live (behavior only) | Tool routing (`compare_players`) + must-not-hallucinate. **No verdict assertion.** |
| "Who should I pick up?" | ✅ live (behavior only) | Tool routing (`get_free_agents` + `get_player_projection`) + must-not-recommend-rostered-player |
| "Is X having a good season?" | ✅ live (behavior only) | Tool routing + must-cite-a-tool |
| "What's my rank?" with a specific expected number | ❌ — escalates to **manual regression** with snapshot | Content-equality requires frozen state |

So the generator covers **all** common question types — it just asserts on the right things for each.

### Self-reference mitigation

To reduce blind-spot alignment between author and agent:

- **Different model.** Generation uses Claude Opus. The agent under test runs Sonnet. Symmetric biases get broken.
- **Contract-grounded, not LLM-grounded.** Assertions come from a **topic contract** — a small Python module per topic that hard-codes "for this topic the agent must call tool X, must reference vocabulary Y, must never say Z." The generator LLM only writes paraphrasings and picks which contract to apply. It never invents what's correct.
- **Independent spot-checks.** Every Nth generated case is flagged for human review before it enters the regression suite.

### What the `eval-author` skill does

Invocation:

```
/author-evals --topic waivers --snapshot offseason_2026_05 --count 30
```

Invocation:

```
/author-evals --topic waivers --count 30
```

(No `--snapshot` flag by default. Generated cases are `live` mode.)

Pipeline per invocation:

1. **Enumerate** — load the topic's contract module. Walk the (question_type × complexity × answer_shape) taxonomy filtered to what the contract declares supported. Each cell becomes one case slot.
2. **Apply contract** — for each slot, copy the topic's hard-coded behavior assertions: `must_call_tools`, `must_not_call_tools`, vocabulary for `response_contains_any`, hallucination blacklist for `response_contains_none`, cost/latency budgets.
3. **Phrase** — call Opus to generate 3-5 paraphrasings of the user message. Variations cover: terse vs verbose, jargon vs plain English, full sentences vs fragments. All phrasings share the same assertions.
4. **Assemble** — write the case YAML with `mode: live`, structured `intent` block, `phrasings` list, the contract's assertions, `provenance.source: generated`.
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

The original phased plan stays. Generator slots in at E3.5:

- **E1** — minimal harness, hand-written cases (still the foundation)
- **E2** — Postgres + LangSmith integration
- **E3** — promoter (real chat → case)
- **E3.5** — `eval-author` skill + first probe (`league_rules`) + first 30 generated cases. **This is the "I don't author cases" unlock.**
- **E4** — multi-snapshot
- **E5** — dashboard

E3.5 cannot ship before E1+E2: the generator depends on the runner and the result schema.

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
| Tavily (`search_recent_news`) | Real Tavily calls cost cents per query. **E1 avoids; E2+ stubs from snapshot fixtures.** |
| Postgres + local compute | Free |

**Prompt caching is the key lever.** The system prompt + tool definitions
(~3-4k tokens) are identical across every case. Deepagents caches by default —
after the first run in a batch, subsequent runs pay ~10% on the cached portion.
**Run cases in batches**, not one-at-a-time, to keep the cache warm.

### Projected cost per full-suite run

Assumes prompt caching on, no Tavily calls, Sonnet pricing.

| Stage | Cases | Avg phrasings × repeats | Runs | Cost / full suite |
|-------|-------|------------------------|------|-------------------|
| E1 launch | 1 | 4 × 1 | 4 | ~$0.02 |
| After E3.5 (first generated batch) | ~30 | 3 × 1 | 90 | ~$0.50–$1 |
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
- **Pause snapshots that aren't currently relevant.** If only off-season behavior is shipping, don't burn tokens on midseason snapshots until you change something season-dependent.
- **Stop running cases with `repeat>1`** when investigation completes — flakiness sweeps are scoped, not standing.

### What NOT to do (anti-patterns)

- **Don't substitute Haiku for the agent under test.** The eval must hit the real production model. Cheaper-model evals lie.
- **Don't disable evals because they cost.** A missed regression in production costs more than running the suite. The threshold for "too expensive" is when token spend crosses ~5% of total LLM spend; well below that, keep running.
- **Don't run on every commit assuming it's "free."** Caching helps but doesn't eliminate cost. Multiply commits/day × full-suite cost before flipping that switch.

### When to revisit this section

- When `eval_runs` token spend in a month exceeds 5% of total Anthropic spend
- When mature-suite cost projection exceeds $50/day
- When the smoke tier grows past ~15 cases (it shouldn't; trim it)
- When we add expensive-per-call tools (e.g. real-time NBA APIs) that bypass snapshot fixtures

---

## How to keep this doc useful

- Update §4 (snapshot library) every time we capture a new snapshot.
- Update §6 (assertion vocabulary) every time we add an assertion type.
- Don't delete the "deferred" or "open decisions" sections — they're reminders of things we chose NOT to do, which matters as much as what we did.
