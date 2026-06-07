"""
Kuzu graph database schema for design-graph.

All DDL statements are defined here as constants.
initialize_schema() is idempotent — calling it twice is safe.

Schema changes:
  v2 — added CONTAINS relationship (Component → Component with weight property)
       added detection_method field to Section node
"""

from __future__ import annotations

import logging
import sys

import kuzu

logger = logging.getLogger(__name__)

# ── Node table definitions ─────────────────────────────────────────────────────

_NODE_TABLES: list[str] = [
    (
        "CREATE NODE TABLE Screen("
        "  name STRING,"
        "  component_count INT64,"
        "  sections_count INT64,"
        "  PRIMARY KEY(name)"
        ")"
    ),
    (
        "CREATE NODE TABLE Section("
        "  id STRING,"
        "  screen STRING,"
        "  name STRING,"
        "  styles_json STRING,"
        "  components_json STRING,"
        "  texts_json STRING,"
        "  jsx_snippet STRING,"
        "  detection_method STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Component("
        "  name STRING,"
        "  comp_type STRING,"
        "  jsx_snippet STRING,"
        "  occurrence INT64,"
        "  classes STRING,"
        "  PRIMARY KEY(name)"
        ")"
    ),
    (
        "CREATE NODE TABLE Token("
        "  id STRING,"
        "  category STRING,"
        "  label STRING,"
        "  value STRING,"
        "  usage INT64,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE UIText("
        "  id STRING,"
        "  content STRING,"
        "  text_type STRING,"
        "  source STRING,"
        "  element STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Style("
        "  id STRING,"
        "  element STRING,"
        "  state STRING,"
        "  property STRING,"
        "  value STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Interaction("
        "  id STRING,"
        "  trigger STRING,"
        "  css_prop STRING,"
        "  from_val STRING,"
        "  to_val STRING,"
        "  transition STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE ComponentProp("
        "  id STRING,"
        "  component_name STRING,"
        "  prop_name STRING,"
        "  default_value STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
]

# ── Relationship table definitions ─────────────────────────────────────────────

_REL_TABLES: list[str] = [
    "CREATE REL TABLE USES_COMPONENT(FROM Screen TO Component)",
    "CREATE REL TABLE HAS_SECTION(FROM Screen TO Section)",
    "CREATE REL TABLE SECTION_USES(FROM Section TO Component)",
    "CREATE REL TABLE HAS_STYLE(FROM Component TO Style)",
    "CREATE REL TABLE USES_TOKEN(FROM Component TO Token)",
    "CREATE REL TABLE COMP_HAS_TEXT(FROM Component TO UIText)",
    "CREATE REL TABLE HAS_INTERACTION(FROM Component TO Interaction)",
    # v2: compositional hierarchy with occurrence weight
    "CREATE REL TABLE CONTAINS(FROM Component TO Component, weight INT64)",
    # v3: style-level token linkage — which CSS property resolves to which token
    "CREATE REL TABLE STYLE_USES_TOKEN(FROM Style TO Token)",
    # v4: section container styles as proper graph nodes (replaces styles_json blob)
    "CREATE REL TABLE SECTION_HAS_STYLE(FROM Section TO Style)",
    # v5: section texts as UIText nodes (replaces texts_json blob)
    "CREATE REL TABLE SECTION_HAS_TEXT(FROM Section TO UIText)",
    # v6: component prop declarations extracted from function signatures
    "CREATE REL TABLE HAS_PROP(FROM Component TO ComponentProp)",
]

SCHEMA: list[str] = _NODE_TABLES + _REL_TABLES

# ── Stats queries (count of each node/rel type) ───────────────────────────────

STATS_QUERIES: dict[str, str] = {
    "screens":          "MATCH (n:Screen) RETURN count(n)",
    "components":       "MATCH (n:Component) RETURN count(n)",
    "tokens":           "MATCH (n:Token) RETURN count(n)",
    "texts":            "MATCH (n:UIText) RETURN count(n)",
    "styles":           "MATCH (n:Style) RETURN count(n)",
    "sections":         "MATCH (n:Section) RETURN count(n)",
    "interactions":     "MATCH (n:Interaction) RETURN count(n)",
    "contains":         "MATCH ()-[r:CONTAINS]->() RETURN count(r)",
    "section_styles":   "MATCH ()-[r:SECTION_HAS_STYLE]->() RETURN count(r)",
    "component_props":  "MATCH (n:ComponentProp) RETURN count(n)",
}


def initialize_schema(conn: kuzu.Connection) -> None:
    """
    Create all node and relationship tables.
    Silences 'table already exists' errors so this is safe to call multiple times.
    Re-raises any other errors.
    """
    for stmt in SCHEMA:
        try:
            conn.execute(stmt)
        except Exception as exc:
            # Kuzu raises RuntimeError with "already exists" in the message
            if "already exists" in str(exc).lower():
                logger.debug("schema: table already exists, skipping: %s", exc)
            else:
                logger.error("schema: unexpected error executing: %s\n%s", stmt, exc)
                raise

    _verify_kuzu_version()
    logger.info("schema: initialised successfully")


def _verify_kuzu_version() -> None:
    """Emit a warning if the Kuzu version is below the tested minimum."""
    try:
        min_ver = (0, 6)
        ver_str: str = getattr(kuzu, "__version__", "0.0")
        parts = tuple(int(x) for x in ver_str.split(".")[:2] if x.isdigit())
        if parts < min_ver:
            sys.stderr.write(
                f"[design-graph] WARNING: Kuzu {ver_str} detected; "
                f">= 0.6 required for CONTAINS with properties.\n"
            )
    except Exception:  # noqa: BLE001
        pass
