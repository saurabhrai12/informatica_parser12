---
name: informatica_xml
description: Domain knowledge for parsing Informatica PowerCenter mapping XML exports. Load before modifying step1_lineage/extractor.py.
owner: step1_lineage
agent_modifiable: true
improved_by: autoresearch (program_lineage.md)
---

# Informatica PowerCenter XML — field extraction reference

This skill is loaded by the agent **before** it edits `step1_lineage/extractor.py`.
It encodes what we know about the Informatica XML schema so the extractor can be
improved without re-deriving structural knowledge every run. The autoresearch loop
may **append** new findings to the "Learned patterns" section at the bottom, but
must NOT rewrite canonical sections above it.

## Top-level structure

```
POWERMART
└── REPOSITORY
    └── FOLDER
        └── MAPPING  (name = mapping_name)
            ├── SOURCE       (one per Oracle table read)
            │   └── SOURCEFIELD (NAME, DATATYPE, LENGTH, NULLABLE, KEYTYPE)
            ├── TARGET       (one per Snowflake target)
            │   └── TARGETFIELD (NAME, DATATYPE, KEYTYPE)
            ├── TRANSFORMATION  (TYPE = Source Qualifier | Expression |
            │   │                 Filter | Lookup Procedure | Aggregator |
            │   │                 Joiner | Router | Sorter | Normalizer |
            │   │                 Update Strategy | Sequence)
            │   ├── TRANSFORMFIELD  (NAME, PORTTYPE, EXPRESSION, DATATYPE)
            │   └── TABLEATTRIBUTE  (NAME="Sql Query" | "Lookup condition"
            │                        | "Group Filter Condition" | ...)
            ├── INSTANCE  (references a transformation by name)
            ├── TARGETINSTANCE  (UPDATESTRATEGY, TRUNCATETARGET)
            └── CONNECTOR  (FROMTRANSFORMATION, FROMFIELD,
                            TOTRANSFORMATION,   TOFIELD)
```

## Field-extraction cheat-sheet

| Lineage field | Where to read it from |
|---|---|
| `mapping_name` | `MAPPING/@NAME` |
| `source_table` | Resolve via SQ: for each `TRANSFORMATION TYPE="Source Qualifier"`, take its TRANSFORMFIELD names and pick the SOURCE with the highest field-name overlap |
| `source_column`, `source_datatype`, `source_length`, `source_nullable`, `source_pk_flag` | `SOURCEFIELD` attributes — `NULLABLE != "NOT NULL"`, `KEYTYPE` contains `PRIMARY KEY` |
| `source_filter` | `TRANSFORMATION TYPE="Filter"` → `TABLEATTRIBUTE NAME="Filter Condition"` |
| `sq_override_sql` | `TRANSFORMATION TYPE="Source Qualifier"` → `TABLEATTRIBUTE NAME="Sql Query"` (unescape `&#10;`, `&#13;`) |
| `transformation_sequence` | Walk CONNECTOR backwards from TARGET field → collect TRANSFORMATION types in order |
| `final_expression` | Last Expression/Aggregator TRANSFORMFIELD in the chain, attribute `EXPRESSION` — **verbatim**, never paraphrase |
| `pass_through` | true if the CONNECTOR chain has no Expression/Aggregator/Lookup between SQ and TARGET |
| `default_value` | `TRANSFORMFIELD/@DEFAULTVALUE` |
| `lookup_table` | `TRANSFORMATION TYPE="Lookup Procedure"` → `TABLEATTRIBUTE NAME="Lookup table name"` |
| `lookup_condition` | same transform → `TABLEATTRIBUTE NAME="Lookup condition"` |
| `aggregation_logic` | TRANSFORMFIELD in an Aggregator where PORTTYPE contains `VARIABLE` or expression has `SUM/AVG/COUNT/MIN/MAX` |
| `join_condition` | `TRANSFORMATION TYPE="Joiner"` → `TABLEATTRIBUTE NAME="Join Condition"` |
| `router_condition` | `TRANSFORMATION TYPE="Router"` → per-group `TABLEATTRIBUTE NAME="Group Filter Condition"` (one lineage row PER group, including `DEFAULT`) |
| `sorter_logic` | Sorter TRANSFORMFIELDs whose PORTTYPE includes `KEY` |
| `target_table`, `target_column`, `target_datatype` | `TARGET/@NAME`, `TARGETFIELD` |
| `load_type` | `TARGETINSTANCE/@UPDATESTRATEGY`: both `DD_INSERT`+`DD_UPDATE` → `UPSERT`; `DD_DELETE` → `DELETE`; else `INSERT` |
| `truncate_before_load` | `TARGETINSTANCE/@TRUNCATETARGET == "YES"` |

## CONNECTOR graph traversal

Building both a forward and backward map is the single most important step:

```python
conn_fwd: dict[(from_t, from_f), list[(to_t, to_f)]]
conn_bwd: dict[(to_t, to_f), (from_t, from_f)]
```

To fill a target row's lineage, start at `(target_instance, target_field)` and
walk `conn_bwd` until you hit a SOURCEFIELD reference (or a SQ TRANSFORMFIELD
that is itself wired to a SOURCEFIELD). Collect every transformation type you
pass through — that is the `transformation_sequence`.

## Migration complexity rules

- **COMPLEX** — chain contains `Lookup Procedure`, `Router`, `Joiner`, `Aggregator`, `Normalizer`, or a stored-procedure call
- **MODERATE** — has a single `IIF`, `DECODE`, `NVL2`, `ADD_TO_DATE`, `DATE_DIFF`, or a standard scalar (`NVL`, `UPPER`, `LOWER`, `SUBSTR`, `TO_DATE`, `TO_CHAR`, `TRUNC`)
- **SIMPLE** — pass-through or trivial type cast

## Expression gotchas (do NOT paraphrase)

Informatica expressions are stored with XML entity escapes. Always unescape
`&quot;`, `&apos;`, `&amp;`, `&#10;`, `&#13;` before emitting the verbatim
expression into the lineage row.

Nested `IIF` chains commonly reach 5+ levels deep. Do not attempt to simplify
them in the extractor — Step 3 (procgen) does the translation.

## Router gotcha

Routers produce N+1 lineage rows per target field: one per named group plus the
`DEFAULT` group. Each row MUST have the verbatim group filter condition in
`router_condition`, and the transformation_sequence must terminate with the
Router group name.

## Learned patterns (append-only, autoresearch may extend)

<!-- Each entry: date | pattern | fixture where observed -->
<!-- Example: 2026-04-09 | SQ override with multi-line CTE wrapped in &#10; | complex_chain.xml -->
