# `app/evals/` — eval harness scaffolding

> Full design: [`docs/EVAL_HARNESS.md`](../../../docs/EVAL_HARNESS.md). Read that first.
> This README is just the file map.

## Layout

```
app/evals/
├── schema.py          Pydantic models — single source of truth for case shape
├── loader.py          load_case(path), discover_cases(root)
├── cases/
│   ├── manual/        Hand-written cases
│   ├── promoted/      Real chats turned into cases (via promoter, Phase E3)
│   └── generated/     Output of eval-author skill (Phase E4)
│       └── {topic}/   One subdir per topic (waivers, trades, etc.)
├── probes/            Topic contracts for the generator (Phase E4)
├── runner/            Discovers cases, invokes the agent, checks assertions
└── digests/           Auto-generated weekly markdown digests
```

## Status

- ✅ Phase E0: schema + loader + first manual case
- ✅ Phase E1: live runner + severity tiers + 6 cases passing 24/24
- ⬜ Phase E2: Postgres `eval_runs` + `eval_case_results` tables + LangSmith
- ⬜ Phase E3: promoter (real chat → case YAML)
- ⬜ Phase E4: `eval-author` skill + first topic contract
- ⬜ Phase E5: dashboard

## Running the harness

```bash
# All cases
python scripts/run_evals.py

# Filter by intent.domain
python scripts/run_evals.py --domain waivers

# One case
python scripts/run_evals.py --case waiver_days_offseason

# Validate cases without invoking the agent (no API cost)
python scripts/run_evals.py --dry-run
```

## Adding a case by hand

Drop a YAML in `cases/manual/{name}.yaml` matching `schema.EvalCase`, then
run `python scripts/run_evals.py --case {name}` to validate.
