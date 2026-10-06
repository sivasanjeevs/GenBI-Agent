"""
introspect.py – Oracle schema introspection (Phase 2 / Step 1).

Pulls *structural* information only – no LLM, no profiling.
All results are expressed as strict Pydantic v2 models so downstream
modules get typed, validated data.

Data gathered per table

• Columns   : name, data_type, nullable, lengths, precision, scale, default
• PK / FK   : via ALL_CONSTRAINTS + ALL_CONS_COLUMNS (+ recursive ref lookup)
• Unique     : U-type constraints
• Check      : C-type constraints (useful for decoding flag columns)
• Indexes    : via ALL_INDEXES + ALL_IND_COLUMNS
• Row count  : lightweight COUNT(*) per table

Public API

    introspect_schemas(schemas: list[str]) -> list[TableMeta]
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import BaseModel, Field
from tqdm import tqdm

from app.db import raw_execute

class ColumnMeta(BaseModel):
    """Metadata for a single column in ALL_TAB_COLUMNS."""
    name: str
    data_type: str
    nullable: bool
    data_length: int | None = None
    data_precision: int | None = None
    data_scale: int | None = None
    default_value: str | None = None

class ConstraintMeta(BaseModel):
    """A single constraint (P / R / U / C)."""
    name: str
    type: str          # P = primary key, R = foreign key, U = unique, C = check
    columns: list[str]
    ref_table: str | None = None        # fully qualified: SCHEMA.TABLE
    ref_columns: list[str] | None = None
    search_condition: str | None = None  # for CHECK constraints

class IndexMeta(BaseModel):
    name: str
    columns: list[str]
    uniqueness: str    # "UNIQUE" | "NONUNIQUE"

class TableMeta(BaseModel):
    """All structural metadata for one Oracle table."""
    schema_name: str = Field(..., alias="schema")
    table_name: str
    columns: list[ColumnMeta] = Field(default_factory=list)
    constraints: list[ConstraintMeta] = Field(default_factory=list)
    indexes: list[IndexMeta] = Field(default_factory=list)
    row_count: int | None = None

    model_config = {"populate_by_name": True}

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    @property
    def primary_key_columns(self) -> list[str]:
        return next(
            (c.columns for c in self.constraints if c.type == "P"), []
        )

    @property
    def foreign_keys(self) -> list[ConstraintMeta]:
        return [c for c in self.constraints if c.type == "R"]

    @property
    def check_constraints(self) -> list[ConstraintMeta]:
        return [c for c in self.constraints if c.type == "C"]

_ALL_TABLES_SQL = """
SELECT owner, table_name
FROM   all_tables
WHERE  owner IN ({placeholders})
ORDER  BY owner, table_name
"""

_COLUMNS_SQL = """
SELECT
    column_name,
    data_type,
    nullable,
    data_length,
    data_precision,
    data_scale,
    data_default
FROM   all_tab_columns
WHERE  owner      = :p_owner
  AND  table_name = :p_table
ORDER  BY column_id
"""

# Returns one row per (constraint, column); caller groups by constraint_name.
_CONSTRAINTS_SQL = """
SELECT
    ac.constraint_name,
    ac.constraint_type,
    acc.column_name,
    ac.r_owner,
    ac.r_constraint_name,
    ac.search_condition
FROM   all_constraints  ac
JOIN   all_cons_columns acc
    ON  ac.owner           = acc.owner
    AND ac.constraint_name = acc.constraint_name
WHERE  ac.owner       = :p_owner
  AND  ac.table_name  = :p_table
  AND  ac.constraint_type IN ('P', 'R', 'U', 'C')
ORDER  BY ac.constraint_name, acc.position
"""

# Resolve the referenced table + columns for an FK constraint.
_REF_COLS_SQL = """
SELECT acc.table_name, acc.column_name
FROM   all_constraints  ac
JOIN   all_cons_columns acc
    ON  ac.owner           = acc.owner
    AND ac.constraint_name = acc.constraint_name
WHERE  ac.owner           = :owner
  AND  ac.constraint_name = :ref_name
ORDER  BY acc.position
"""

_INDEXES_SQL = """
SELECT
    ai.index_name,
    aic.column_name,
    ai.uniqueness
FROM   all_indexes     ai
JOIN   all_ind_columns aic
    ON  ai.owner      = aic.index_owner
    AND ai.index_name = aic.index_name
WHERE  ai.table_owner = :p_owner
  AND  ai.table_name  = :p_table
ORDER  BY ai.index_name, aic.column_position
"""

_ROW_COUNT_SQL = "SELECT COUNT(*) AS cnt FROM {schema}.{table}"

def _build_constraints(schema: str, table: str) -> list[ConstraintMeta]:
    """Query ALL_CONSTRAINTS for a table and resolve FK references."""
    rows = raw_execute(_CONSTRAINTS_SQL, {"p_owner": schema, "p_table": table})

    # Group rows by constraint name (one DB row per column)
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        cname = row["constraint_name"]
        if cname not in by_name:
            by_name[cname] = {
                "type": row["constraint_type"],
                "columns": [],
                "r_owner": row["r_owner"],
                "r_constraint_name": row["r_constraint_name"],
                "search_condition": row["search_condition"],
            }
        col = row["column_name"]
        if col:
            by_name[cname]["columns"].append(col.lower())

    constraints: list[ConstraintMeta] = []
    for cname, info in by_name.items():
        ref_table: str | None = None
        ref_columns: list[str] | None = None

        if info["type"] == "R" and info["r_constraint_name"]:
            ref_owner = info["r_owner"] or schema
            ref_rows = raw_execute(
                _REF_COLS_SQL,
                {"owner": ref_owner, "ref_name": info["r_constraint_name"]},
            )
            if ref_rows:
                ref_table = f"{ref_owner}.{ref_rows[0]['table_name']}"
                ref_columns = [r["column_name"].lower() for r in ref_rows]

        constraints.append(
            ConstraintMeta(
                name=cname,
                type=info["type"],
                columns=info["columns"],
                ref_table=ref_table,
                ref_columns=ref_columns,
                search_condition=(
                    str(info["search_condition"]).strip()
                    if info["search_condition"]
                    else None
                ),
            )
        )
    return constraints

def _build_indexes(schema: str, table: str) -> list[IndexMeta]:
    """Query ALL_INDEXES + ALL_IND_COLUMNS for a table."""
    rows = raw_execute(_INDEXES_SQL, {"p_owner": schema, "p_table": table})
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        iname = row["index_name"]
        if iname not in by_name:
            by_name[iname] = {"columns": [], "uniqueness": row["uniqueness"]}
        by_name[iname]["columns"].append(row["column_name"].lower())
    return [
        IndexMeta(name=k, columns=v["columns"], uniqueness=v["uniqueness"])
        for k, v in by_name.items()
    ]

def _get_row_count(schema: str, table: str) -> int | None:
    """Return approximate row count; returns None on error."""
    try:
        rows = raw_execute(_ROW_COUNT_SQL.format(schema=schema, table=table))
        val = rows[0]["cnt"] if rows else None
        return int(val) if val is not None else None
    except Exception:  # noqa: BLE001
        return None

def introspect_schemas(schemas: list[str]) -> list[TableMeta]:
    """
    Introspect one or more Oracle schemas.

    Args:
        schemas: List of schema (owner) names – already upper-cased from
                 ``settings.schemas``.

    Returns:
        list[TableMeta] – one entry per table found across all schemas.
    """
    schemas = [s.upper() for s in schemas]
    logger.info("Introspecting schemas: {}", schemas)

    # Build IN-list for ALL_TABLES
    placeholders = ", ".join(f"'{s}'" for s in schemas)
    table_rows = raw_execute(_ALL_TABLES_SQL.format(placeholders=placeholders))
    logger.info("Found {} tables across {}", len(table_rows), schemas)

    result: list[TableMeta] = []

    for tr in tqdm(table_rows, desc="Introspecting tables"):
        schema = tr["owner"]
        table = tr["table_name"]

        col_rows = raw_execute(_COLUMNS_SQL, {"p_owner": schema, "p_table": table})
        columns = [
            ColumnMeta(
                name=r["column_name"].lower(),
                data_type=r["data_type"],
                nullable=(r["nullable"] == "Y"),
                data_length=r["data_length"],
                data_precision=r["data_precision"],
                data_scale=r["data_scale"],
                default_value=(
                    str(r["data_default"]).strip() if r["data_default"] else None
                ),
            )
            for r in col_rows
        ]

        constraints = _build_constraints(schema, table)
        indexes = _build_indexes(schema, table)
        row_count = _get_row_count(schema, table)

        result.append(
            TableMeta(
                schema=schema,
                table_name=table,
                columns=columns,
                constraints=constraints,
                indexes=indexes,
                row_count=row_count,
            )
        )
        logger.debug(
            "{}.{}: {} cols | {} constraints | {} rows",
            schema, table, len(columns), len(constraints), row_count,
        )

    logger.success("Introspection complete: {} tables", len(result))
    return result

if __name__ == "__main__":
    from app.config import settings

    tables = introspect_schemas(settings.schemas)
    for t in tables:
        print(
            f"{t.full_name}: {len(t.columns)} cols "
            f"pk={t.primary_key_columns} "
            f"fks={len(t.foreign_keys)} "
            f"rows={t.row_count}"
        )
