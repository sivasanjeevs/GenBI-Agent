"""
store.py – Semantic layer persistence: save, load, and override.

File layout:
  semantic_layer/
    <schema>_<table>.json   – one file per table
    index.json              – summary index of all tables
    overrides.yaml          – manual corrections (never auto-overwritten)
    changelog.json          – audit log of changes

Overrides are merged on top of the auto-generated layer at load time.
The changelog records every change with timestamp and before/after diff.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from app.config import settings


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _table_path(schema: str, table_name: str) -> Path:
    settings.semantic_layer_dir.mkdir(parents=True, exist_ok=True)
    return settings.semantic_layer_dir / f"{schema}_{table_name}.json"


def _index_path() -> Path:
    return settings.semantic_layer_dir / "index.json"


def _serialize(obj: Any) -> Any:
    """Make objects JSON-serialisable."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


# ─── Save ─────────────────────────────────────────────────────────────────────

def save_semantic_layer(enriched: list[dict[str, Any]]) -> Path:
    """
    Write each table's semantic data to its own JSON file.
    Write an index.json summary.
    Returns the semantic_layer directory path.
    """
    settings.semantic_layer_dir.mkdir(parents=True, exist_ok=True)
    index = []

    for table_info in enriched:
        schema = table_info["schema"]
        table_name = table_info["table_name"]
        path = _table_path(schema, table_name)
        path.write_text(
            json.dumps(table_info, indent=2, default=_serialize),
            encoding="utf-8",
        )
        index.append(
            {
                "schema": schema,
                "table_name": table_name,
                "full_name": table_info["full_name"],
                "table_type": table_info.get("table_type"),
                "business_entity": table_info.get("semantics", {}).get("business_entity"),
                "table_description": table_info.get("semantics", {}).get("table_description"),
                "row_count": table_info.get("row_count"),
                "is_scd": table_info.get("is_scd"),
                "file": str(path),
            }
        )

    _index_path().write_text(
        json.dumps(
            {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tables": index},
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.success(
        f"Semantic layer saved: {len(enriched)} tables → {settings.semantic_layer_dir}"
    )
    return settings.semantic_layer_dir


# ─── Load ─────────────────────────────────────────────────────────────────────

def load_semantic_layer() -> dict[str, Any] | None:
    """
    Load the full semantic layer (all table files + merge overrides).
    Returns None if not yet generated.
    """
    if not _index_path().exists():
        return None

    index_data = json.loads(_index_path().read_text())
    tables: list[dict[str, Any]] = []

    for entry in index_data["tables"]:
        fpath = Path(entry["file"])
        if fpath.exists():
            table_data = json.loads(fpath.read_text())
            tables.append(table_data)

    # Merge overrides
    overrides = _load_overrides()
    if overrides:
        tables = _apply_overrides_to_tables(tables, overrides)

    return {
        "generated_at": index_data["generated_at"],
        "tables": tables,
    }


def load_table_semantics(full_name: str) -> dict[str, Any] | None:
    """Load semantics for a single table by its full name (SCHEMA.TABLE)."""
    parts = full_name.upper().split(".")
    if len(parts) != 2:
        return None
    path = _table_path(parts[0], parts[1])
    if not path.exists():
        return None
    return json.loads(path.read_text())


# ─── Overrides ────────────────────────────────────────────────────────────────

def _load_overrides() -> dict[str, Any]:
    if not settings.overrides_file.exists():
        return {}
    with open(settings.overrides_file) as f:
        return yaml.safe_load(f) or {}


def _apply_overrides_to_tables(
    tables: list[dict[str, Any]],
    overrides: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Merge overrides.yaml into the in-memory semantic layer.
    Override structure:
      tables:
        VID.SUBSCRIBERS:
          semantics:
            table_description: "..."
          columns:
            status:
              value_map:
                A: Active
    """
    table_overrides = overrides.get("tables", {})
    for table in tables:
        full_name = table["full_name"]
        if full_name in table_overrides:
            ov = table_overrides[full_name]
            # Deep merge semantics
            if "semantics" in ov:
                table["semantics"].update(ov["semantics"])
            # Column-level overrides
            if "columns" in ov:
                for col, col_ov in ov["columns"].items():
                    if col in table["semantics"].get("columns", {}):
                        table["semantics"]["columns"][col].update(col_ov)
                    else:
                        table["semantics"].setdefault("columns", {})[col] = col_ov
    return tables


def apply_overrides(new_overrides: dict[str, Any]) -> None:
    """
    Merge new_overrides into overrides.yaml and update the changelog.
    """
    settings.overrides_file.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_overrides()
    _changelog_append({"action": "override", "before": existing, "after": new_overrides})

    # Deep merge
    _deep_merge(existing, new_overrides)

    with open(settings.overrides_file, "w") as f:
        yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)

    logger.info("Overrides saved to overrides.yaml")


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _changelog_append(entry: dict[str, Any]) -> None:
    settings.changelog_file.parent.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    if settings.changelog_file.exists():
        log = json.loads(settings.changelog_file.read_text())
    entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log.append(entry)
    settings.changelog_file.write_text(json.dumps(log, indent=2, default=_serialize))
