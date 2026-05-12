# `app/evals/` — eval harness scaffolding

> Full design: [`docs/EVAL_HARNESS.md`](../../../docs/EVAL_HARNESS.md). Read that first.
> This README is just the file map.

## Layout

```
app/evals/
├── schema.py          Pydantic models — single source of truth for case shape
├── loader.py          load_case(path), discover_cases(root)
├── cases/
│   ├── manual/        Hand-written cases (Itamar or Claude during a session)
│   ├── promoted/      Real chats turned into cases (via promoter, Phase E3)
│   └── generated/     Output of eval-author skill (Phase E3.5)
│       └── {topic}/   One subdir per topic (waivers, trades, etc.)
├── snapshots/         Frozen league states for replay (one subdir per snapshot)
├── probes/            Ground-truth probes per topic (Phase E3.5)
├── runner/            Runs cases against snapshots, checks assertions
└── digests/           Auto-generated weekly markdown digests
```

## Status

- ✅ Phase E0: schema + loader + first manual case validate end-to-end
- ⬜ Phase E1: snapshot capture + runner skeleton
- ⬜ Phase E2: Postgres tables + LangSmith integration
- ⬜ Phase E3: promoter (real chat → case)
- ⬜ Phase E3.5: eval-author skill + first probe
- ⬜ Phase E4: multi-snapshot
- ⬜ Phase E5: dashboard

## Adding a case by hand right now

1. Drop a YAML in `cases/manual/{name}.yaml` matching `schema.EvalCase`
2. Validate: `python -c "from pathlib import Path; from app.evals.loader import discover_cases; print(discover_cases(Path('app/evals/cases')))"`
3. Once Phase E1 lands: `./scripts/eval.sh --case {name}`
