"""
Kuzu graph database schema for design-graph.

All DDL statements are defined here as constants.
initialize_schema() is idempotent — calling it twice is safe.

Schema changes:
  v2 — added CONTAINS relationship (Component → Component with weight property)
       added detection_method field to Section node
  v7 — added truncated_fields to Component (comma-separated field names capped
       during extraction, e.g. "styles,texts" — empty string when nothing was cut)
  v8 — added order_index to CONTAINS (sibling render order — first-appearance
       order in the source JSX, not alphabetical)
  v9 — added referenced_data_json to Component (JSON-encoded {const_name:
       value} for every module-level constant this component's own body
       references by name, e.g. an icon-name -> SVG-path lookup table —
       empty string when none apply; see extraction/module_data_extractor.py)
  v10 — format-neutral model: source_code/source_lang/source_simplified on
       Screen, Section and Component; declares_inline_styles on Component;
       Token.mode; Screen viewport; NAVIGATES_TO and VARIANT_OF between
       screens; a Model node recording this version and the capture used
  v11 — lossless capture: sources stored as the prototype wrote them (source_simplified
       removed); no per-component caps, so truncated_fields is removed too;
       SCREEN_HAS_STYLE for a screen's own elements; Resource nodes and USES_RESOURCE;
       Screen.skeleton (the source with component occurrences as instance tags); Asset files;
       Action nodes (HAS_ACTION, SCREEN_HAS_ACTION)
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

import kuzu

from design_graph.model.entities import ComponentDefinitionStatus

logger = logging.getLogger(__name__)

# The version of the model a graph is written in. A graph from another version
# is rebuilt by the pipeline and refused by readers instead of half-working.
MODEL_VERSION = 11

# ── Node table definitions ─────────────────────────────────────────────────────

_NODE_TABLES: list[str] = [
    (
        "CREATE NODE TABLE Model("
        "  version INT64,"
        "  capture STRING,"
        "  PRIMARY KEY(version)"
        ")"
    ),
    (
        "CREATE NODE TABLE Screen("
        "  name STRING,"
        "  component_count INT64,"
        "  sections_count INT64,"
        "  source_code STRING,"
        "  source_lang STRING,"
        "  viewport_width INT64,"
        "  viewport_height INT64,"
        "  skeleton STRING,"
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
        "  source_code STRING,"
        "  source_lang STRING,"
        "  detection_method STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Component("
        "  name STRING,"
        "  comp_type STRING,"
        "  source_code STRING,"
        "  source_lang STRING,"
        "  declares_inline_styles BOOLEAN,"
        "  occurrence INT64,"
        "  classes STRING,"
        "  referenced_data_json STRING,"
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
        "  mode STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Icon("
        "  id STRING,"
        "  markup STRING,"
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
        "  media STRING,"  # raw @media condition (e.g. "(max-width:600px)"), "" when unconditional — C35
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
        "CREATE NODE TABLE Resource("
        "  id STRING,"
        "  kind STRING,"
        "  name STRING,"
        "  version STRING,"
        "  origin STRING,"
        "  certainty STRING,"
        "  detail STRING,"
        "  size INT64,"
        "  sha256 STRING,"
        "  import_line STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Action("
        "  id STRING,"
        "  owner STRING,"
        "  trigger STRING,"
        "  element STRING,"
        "  handler STRING,"
        "  effect STRING,"
        "  PRIMARY KEY(id)"
        ")"
    ),
    (
        "CREATE NODE TABLE Asset("
        "  id STRING,"          # sha256 of the content
        "  mime STRING,"
        "  size INT64,"
        "  data STRING,"        # base64 of the content
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
    "CREATE REL TABLE USES_SCREEN(FROM Screen TO Screen)",
    "CREATE REL TABLE NAVIGATES_TO(FROM Screen TO Screen, label STRING)",
    "CREATE REL TABLE VARIANT_OF(FROM Screen TO Screen, axis STRING)",
    "CREATE REL TABLE HAS_SECTION(FROM Screen TO Section)",
    "CREATE REL TABLE SECTION_USES(FROM Section TO Component)",
    "CREATE REL TABLE SECTION_USES_SCREEN(FROM Section TO Screen)",
    "CREATE REL TABLE HAS_STYLE(FROM Component TO Style)",
    # v11: a screen's own elements (the wrappers around its sections) keep their styles
    "CREATE REL TABLE SCREEN_HAS_STYLE(FROM Screen TO Style)",
    # v11: what a screen loads besides its own markup — libraries, runtime, modules, fonts, images
    "CREATE REL TABLE USES_RESOURCE(FROM Screen TO Resource)",
    # v11: the files a font or image resource is made of, each stored once by content
    "CREATE REL TABLE HAS_FILE(FROM Resource TO Asset)",
    # v11: what a component's or screen's elements do when used
    "CREATE REL TABLE HAS_ACTION(FROM Component TO Action)",
    "CREATE REL TABLE SCREEN_HAS_ACTION(FROM Screen TO Action)",
    "CREATE REL TABLE USES_TOKEN(FROM Component TO Token)",
    "CREATE REL TABLE COMP_HAS_TEXT(FROM Component TO UIText)",
    "CREATE REL TABLE HAS_INTERACTION(FROM Component TO Interaction)",
    # v2: compositional hierarchy with occurrence weight
    # v8: order_index — sibling render order among a parent's children
    "CREATE REL TABLE CONTAINS(FROM Component TO Component, weight INT64, order_index INT64)",
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
    "extracted_components": "MATCH (n:Component) WHERE n.occurrence > 0 RETURN count(n)",
    "unresolved_components": (
        "MATCH (n:Component) WHERE n.occurrence = "
        f"{ComponentDefinitionStatus.UNRESOLVED.value} RETURN count(n)"
    ),
    "tokens":           "MATCH (n:Token) RETURN count(n)",
    "icons":            "MATCH (n:Icon) RETURN count(n)",
    "texts":            "MATCH (n:UIText) RETURN count(n)",
    "styles":           "MATCH (n:Style) RETURN count(n)",
    "sections":         "MATCH (n:Section) RETURN count(n)",
    "interactions":     "MATCH (n:Interaction) RETURN count(n)",
    "contains":         "MATCH ()-[r:CONTAINS]->() RETURN count(r)",
    "section_styles":   "MATCH ()-[r:SECTION_HAS_STYLE]->() RETURN count(r)",
    "component_props":  "MATCH (n:ComponentProp) RETURN count(n)",
}


@dataclass(frozen=True)
class NodeTable:
    """A node table as its DDL declares it: primary key and column types."""

    key: str
    columns: dict[str, str]


@dataclass(frozen=True)
class RelTable:
    """A relationship table as its DDL declares it: endpoint tables and property types."""

    source: str
    target: str
    columns: dict[str, str]


_RE_NODE_DDL = re.compile(r"CREATE NODE TABLE (\w+)\((.*)PRIMARY KEY\((\w+)\)\)")
_RE_REL_DDL = re.compile(r"CREATE REL TABLE (\w+)\(FROM (\w+) TO (\w+)((?:, \w+ \w+)*)\)")
_RE_COLUMN = re.compile(r"(\w+) (\w+)")


@lru_cache(maxsize=1)
def node_tables() -> dict[str, NodeTable]:
    """Every node table by name, read from the DDL above — the one place the schema is declared."""
    tables = {}
    for ddl in _NODE_TABLES:
        name, body, key = _RE_NODE_DDL.fullmatch(ddl).groups()
        tables[name] = NodeTable(key=key, columns=dict(_RE_COLUMN.findall(body)))
    return tables


@lru_cache(maxsize=1)
def rel_tables() -> dict[str, RelTable]:
    """Every relationship table by name, read from the DDL above."""
    tables = {}
    for ddl in _REL_TABLES:
        name, source, target, props = _RE_REL_DDL.fullmatch(ddl).groups()
        tables[name] = RelTable(source=source, target=target, columns=dict(_RE_COLUMN.findall(props)))
    return tables


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
