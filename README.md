# Oracle → Snowflake Migration Agent

Auto-migrates Oracle DWH ETL pipelines (built in Informatica PowerCenter) to native
Snowflake SQL stored procedures. See **CLAUDE.md** for the full operating spec.

## Quick start

```bash
uv sync
cp config/env.yaml.example config/env.yaml   # fill in credentials
uv run pytest -x -q
uv run python pipeline.py --all --dry-run
```

## Pipeline stages

1. **step1_lineage** — parse Informatica XML → field-level lineage JSON
2. **step2_mapping** — Oracle ↔ Snowflake column equivalence sheet
3. **step3_procgen** — generate Snowflake `LANGUAGE SQL` stored procedures
4. **step4_testing** — row count / hash / null-rate reconciliation

## Autoresearch loops

```bash
uv run python autoresearch/run_loop.py --step lineage  --max-experiments 50
uv run python autoresearch/run_loop.py --step mapping  --max-experiments 50
uv run python autoresearch/run_loop.py --step procgen  --max-experiments 50
```

Each loop proposes one change, runs `step<N>/eval.py`, keeps the commit on improvement,
reverts otherwise. The eval files and golden fixtures are immutable.
