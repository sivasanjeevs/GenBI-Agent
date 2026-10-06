"""
store.py – Semantic layer persistence (Phase 2 / Step 6).

Compiles the output of introspect → profile → patterns → enrich → verify
into a single ``semantic_layer.json`` file (plus a per-table index) and
provides helpers for loading, overriding, and patching.

File layout

  semantic_layer/
    semantic_layer.json   – full nested dict; all tables
    index.json            – summary index for fast lookup
    overrides.yaml        – human-editable corrections (never auto-overwritten)
    changelog.json        – append-only audit log

Version hash

Each ``semantic_layer.json`` includes a ``version`` field: the SHA-256 of
the full JSON body (computed before writing).  Any change to the content
will produce a new hash, making it easy to detect staleness.

Override merge

``overrides.yaml`` uses the structure documented in the file itself.
At load time, ``_apply_overrides`` deep-merges the YAML onto the JSON in
memory so the response always reflects operator corrections.

Public API

    save_semantic_layer(enrichments: list[TableEnrichment]) -> Path
    load_semantic_layer() -> dict | None
    load_table_semantics(full_name: str) -> dict | None
    apply_overrides(new_overrides: dict) -> None
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from app.config import settings
from app.learning.enrich import TableEnrichment

def _serialize(obj: Any) -> Any:
    """Make objects JSON-serialisable (datetime, Pydantic models, etc.)."""
    if hasattr(obj, "isoformat"):      # datetime / date / time
        return obj.isoformat()
    if hasattr(obj, "model_dump"):     # Pydantic BaseModel
        return obj.model_dump()
    return str(obj)

def _to_dict(te: TableEnrichment) -> dict[str, Any]:
    """Convert a TableEnrichment to a plain JSON-serialisable dict."""
    d = te.model_dump()
    # Nested Pydantic objects (semantics, etc.) are already dicts after model_dump.
    return d

def _semantic_layer_path() -> Path:
    settings.semantic_layer_dir.mkdir(parents=True, exist_ok=True)
    return settings.semantic_layer_dir / "semantic_layer.json"

def _index_path() -> Path:
    return settings.semantic_layer_dir / "index.json"

def _version_hash(payload: str) -> str:
    """SHA-256 of the JSON body, truncated to 16 hex chars for readability."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

def save_semantic_layer(enrichments: list[TableEnrichment]) -> Path:
    """
    Persist the full semantic layer to disk.

    Writes:
    • ``semantic_layer.json``  – full nested object (all tables + version hash)
    • ``index.json``           – lightweight summary for fast lookup

    Args:
        enrichments: Output of ``verify_all()``.

    Returns:
        Path to the ``semantic_layer/`` directory.
    """
    settings.semantic_layer_dir.mkdir(parents=True, exist_ok=True)

    tables_data: list[dict[str, Any]] = [_to_dict(te) for te in enrichments]

    # Build the wrapper object *without* version first, so we can hash it.
    wrapper: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "schemas": list({te.schema_name for te in enrichments}),
        "table_count": len(enrichments),
        "tables": tables_data,
    }

    body_json = json.dumps(wrapper, indent=2, default=_serialize, ensure_ascii=False)
    wrapper["version"] = _version_hash(body_json)

    final_json = json.dumps(wrapper, indent=2, default=_serialize, ensure_ascii=False)

    sl_path = _semantic_layer_path()
    sl_path.write_text(final_json, encoding="utf-8")
    logger.success(
        "Semantic layer saved → {} ({} tables, version={})",
        sl_path, len(enrichments), wrapper["version"],
    )

    index: list[dict[str, Any]] = []
    for te in enrichments:
        high_concepts = [
            v["term"] for v in te.verified_concepts if v.get("confidence") == "high"
        ]
        index.append(
            {
                "schema": te.schema_name,
                "table_name": te.table_name,
                "full_name": te.full_name,
                "table_type": te.table_type,
                "business_entity": te.semantics.business_entity,
                "row_count": te.row_count,
                "is_scd": te.is_scd,
                "verified_high_concepts": high_concepts,
                "version": wrapper["version"],
            }
        )
    _index_path().write_text(
        json.dumps(
            {
                "generated_at": wrapper["generated_at"],
                "version": wrapper["version"],
                "tables": index,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return settings.semantic_layer_dir

def load_semantic_layer() -> dict[str, Any] | None:
    """
    Load the full semantic layer from disk and apply overrides.

    Returns:
        The merged dict, or None if no layer has been generated yet.
    """
    sl_path = _semantic_layer_path()
    if not sl_path.exists():
        return None

    data: dict[str, Any] = json.loads(sl_path.read_text(encoding="utf-8"))

    # Apply human overrides on top
    overrides = _load_overrides()
    if overrides:
        data = _apply_overrides(data, overrides)

    return data

def load_table_semantics(full_name: str) -> dict[str, Any] | None:
    """
    Load semantics for a single table by its full name (SCHEMA.TABLE).

    Scans the in-memory loaded layer rather than a separate per-table file,
    which keeps the storage flat (one file = one source of truth).
    """
    layer = load_semantic_layer()
    if layer is None:
        return None
    target = full_name.upper()
    return next(
        (t for t in layer.get("tables", []) if t.get("full_name", "").upper() == target),
        None,
    )

def _load_overrides() -> dict[str, Any]:
    if not settings.overrides_file.exists():
        return {}
    try:
        with open(settings.overrides_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load overrides.yaml: {}", exc)
        return {}

def _apply_overrides(
    layer: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """
    Deep-merge ``overrides.yaml`` onto the in-memory semantic layer dict.

    Override file structure (YAML):

        tables:
          VID.SUBSCRIBERS:
            semantics:
              table_description: "Overridden description"
            concepts:
              - term: "Active Subscribers"
                filter_sql: "status = 'A'"
                rationale: "Manually verified"
            columns:
              status:
                value_map:
                  A: Active
                  P: Passive
    """
    table_overrides: dict[str, Any] = overrides.get("tables", {})
    tables: list[dict[str, Any]] = layer.get("tables", [])

    for table in tables:
        full_name: str = table.get("full_name", "")
        ov: dict[str, Any] = table_overrides.get(full_name, {})
        if not ov:
            continue

        # Top-level semantics override
        if "semantics" in ov:
            _deep_merge(table.setdefault("semantics", {}), ov["semantics"])

        # Concept-level overrides (replace matching concept by term)
        if "concepts" in ov:
            existing_concepts: list[dict] = table.get("verified_concepts", [])
            for ov_concept in ov["concepts"]:
                term = ov_concept.get("term")
                matched = next((c for c in existing_concepts if c.get("term") == term), None)
                if matched:
                    matched.update(ov_concept)
                else:
                    existing_concepts.append({**ov_concept, "confidence": "manual"})
            table["verified_concepts"] = existing_concepts

        # Column-level overrides (nested under semantics.columns)
        if "columns" in ov:
            sem_cols: dict = table.setdefault("semantics", {}).setdefault("columns", {})
            for col_name, col_ov in ov["columns"].items():
                if col_name in sem_cols:
                    _deep_merge(sem_cols[col_name], col_ov)
                else:
                    sem_cols[col_name] = col_ov

    return layer

def apply_overrides(new_overrides: dict[str, Any]) -> None:
    """
    Merge ``new_overrides`` into ``overrides.yaml`` and log the change.

    The changelog is append-only; the overrides.yaml is updated in place.

    Args:
        new_overrides: Dict following the overrides.yaml structure.
    """
    settings.overrides_file.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_overrides()
    _changelog_append({"action": "override", "before": existing, "patch": new_overrides})

    _deep_merge(existing, new_overrides)

    with open(settings.overrides_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)

    logger.info("Overrides saved to {}", settings.overrides_file)

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge ``override`` into ``base`` in place."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v

def _changelog_append(entry: dict[str, Any]) -> None:
    settings.changelog_file.parent.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    if settings.changelog_file.exists():
        try:
            log = json.loads(settings.changelog_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log = []
    entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log.append(entry)
    settings.changelog_file.write_text(
        json.dumps(log, indent=2, default=_serialize, ensure_ascii=False),
        encoding="utf-8",
    )
