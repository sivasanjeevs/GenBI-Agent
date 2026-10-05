"""
introspect.py – Schema introspection for Oracle DB.

Pulls:
  - All tables in target schemas
  - Column names, data types, nullable, defaults
  - Primary keys
  - Foreign keys / referential constraints
  - Unique constraints
  - Check constraints (useful for decoding status flags)
  - Indexes

Output: list[TableMeta] – one per table across all schemas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from tqdm import tqdm

from app.db import raw_execute


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class ColumnMeta:
    name: str
    data_type: str
    nullable: bool
    data_length: int | None
    data_precision: int | None
    data_scale: int | None
    default_value: str | None


@dataclass
class ConstraintMeta:
    name: str
    type: str          # P=primary, R=foreign, U=unique, C=check
    columns: list[str]
    ref_table: str | None = None
    ref_columns: list[str] | None = None
    search_condition: str | None = None  # for CHECK constraints


@dataclass
class IndexMeta:
    name: str
    columns: list[str]
    uniqueness: str    # UNIQUE | NONUNIQUE


@dataclass
class TableMeta:
    schema: str
    table_name: str
    columns: list[ColumnMeta] = field(default_factory=list)
    constraints: list[ConstraintMeta] = field(default_factory=list)
    indexes: list[IndexMeta] = field(default_factory=list)
    row_count: int | None = None

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.table_name}"

    @property
    def primary_key_columns(self) -> list[str]:
        return next(
            (c.columns for c in self.constraints if c.type == "P"), []
        )

    @property
    def foreign_keys(self) -> list[ConstraintMeta]:
        return [c for c in self.constraints if c.type == "R"]


# ─── Introspection Queries ────────────────────────────────────────────────────

_ALL_TABLES_SQL = """
SELECT owner, table_name
FROM all_tables
WHERE owner IN ({placeholders})
ORDER BY owner, table_name
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
FROM all_tab_columns
WHERE owner = :schema AND table_name = :table
ORDER BY column_id
"""

_CONSTRAINTS_SQL = """
SELECT
    ac.constraint_name,
    ac.constraint_type,
    acc.column_name,
    ac.r_owner,
    ac.r_constraint_name,
    ac.search_condition
FROM all_constraints ac
JOIN all_cons_columns acc
  ON ac.owner = acc.owner
 AND ac.constraint_name = acc.constraint_name
WHERE ac.owner = :schema
  AND ac.table_name = :table
  AND ac.constraint_type IN ('P', 'R', 'U', 'C')
ORDER BY ac.constraint_name, acc.position
"""

_REF_COLS_SQL = """
SELECT acc.table_name, acc.column_name
FROM all_constraints ac
JOIN all_cons_columns acc
  ON ac.owner = acc.owner
 AND ac.constraint_name = acc.constraint_name
WHERE ac.owner = :owner
  AND ac.constraint_name = :ref_name
ORDER BY acc.position
"""

_INDEXES_SQL = """
SELECT
    ai.index_name,
    aic.column_name,
    ai.uniqueness
FROM all_indexes ai
JOIN all_ind_columns aic
  ON ai.owner = aic.index_owner
 AND ai.index_name = aic.index_name
WHERE ai.table_owner = :schema
  AND ai.table_name = :table
ORDER BY ai.index_name, aic.column_position
"""

_ROW_COUNT_SQL = "SELECT COUNT(*) AS cnt FROM {schema}.{table}"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_constraints(schema: str, table: str) -> list[ConstraintMeta]:
    rows = raw_execute(_CONSTRAINTS_SQL, {"schema": schema, "table": table})

    # Group rows by constraint name
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
        by_name[cname]["columns"].append(row["column_name"].lower())

    constraints = []
    for cname, info in by_name.items():
        ref_table = None
        ref_columns = None
        if info["type"] == "R" and info["r_constraint_name"]:
            ref_rows = raw_execute(
                _REF_COLS_SQL,
                {
                    "owner": info["r_owner"] or schema,
                    "ref_name": info["r_constraint_name"],
                },
            )
            if ref_rows:
                ref_table = f"{info['r_owner'] or schema}.{ref_rows[0]['table_name']}"
                ref_columns = [r["column_name"].lower() for r in ref_rows]

        constraints.append(
            ConstraintMeta(
                name=cname,
                type=info["type"],
                columns=info["columns"],
                ref_table=ref_table,
                ref_columns=ref_columns,
                search_condition=info["search_condition"],
            )
        )
    return constraints


def _build_indexes(schema: str, table: str) -> list[IndexMeta]:
    rows = raw_execute(_INDEXES_SQL, {"schema": schema, "table": table})
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
    try:
        rows = raw_execute(_ROW_COUNT_SQL.format(schema=schema, table=table))
        return rows[0]["cnt"] if rows else None
    except Exception:
        return None


# ─── Public Interface ─────────────────────────────────────────────────────────

def introspect_schemas(schemas: list[str]) -> list[TableMeta]:
    """
    Introspect the given Oracle schemas.
    Returns a list of TableMeta objects (one per table).
    """
    logger.info(f"Introspecting schemas: {schemas}")

    # Fetch all tables
    placeholders = ", ".join(f"'{s}'" for s in schemas)
    table_rows = raw_execute(
        _ALL_TABLES_SQL.format(placeholders=placeholders)
    )
    logger.info(f"Found {len(table_rows)} tables across {schemas}")

    result: list[TableMeta] = []
    for tr in tqdm(table_rows, desc="Introspecting tables"):
        schema = tr["owner"]
        table = tr["table_name"]

        # Columns
        col_rows = raw_execute(_COLUMNS_SQL, {"schema": schema, "table": table})
        columns = [
            ColumnMeta(
                name=r["column_name"].lower(),
                data_type=r["data_type"],
                nullable=r["nullable"] == "Y",
                data_length=r["data_length"],
                data_precision=r["data_precision"],
                data_scale=r["data_scale"],
                default_value=r["data_default"],
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
            f"  {schema}.{table}: {len(columns)} cols, "
            f"{row_count} rows, {len(constraints)} constraints"
        )

    logger.success(f"Introspection complete: {len(result)} tables")
    return result


if __name__ == "__main__":
    # Quick smoke test
    from app.config import settings

    tables = introspect_schemas(settings.schemas)
    for t in tables:
        print(f"{t.full_name}: {len(t.columns)} cols, pk={t.primary_key_columns}")
