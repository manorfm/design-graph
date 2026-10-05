"""
Writes extracted entities to the Kuzu graph database.

Design rules:
- GraphWriter is always constructed with an open write connection.
- Entities are collected as rows and written once, in batches, by commit()
  (Kuzu does not support concurrent writes; see batch.py).
- Idempotency: every node is collected once per id; a repeated one is skipped.
- CONTAINS relationships are only created when both parent and child nodes exist.
"""

from __future__ import annotations

import fcntl
import json
import logging
import shutil
from pathlib import Path
from typing import TextIO

import kuzu


from design_graph.model.entities import (
    ComponentDefinitionStatus,
    ComponentProp,
    ComponentType,
    DesignToken,
    ExtractedComponent,
    ExtractedScreen,
    ExtractedSection,
    IconAsset,
    RE_CUSTOM_PROPERTY_REFERENCE,
    StyleEntry,
    TextEntry,
    TokenCategory,
)
from design_graph.model.graph.batch import GraphRows, write_rows
from design_graph.model.graph.schema import MODEL_VERSION, STATS_QUERIES, initialize_schema

logger = logging.getLogger(__name__)

class BuildLockError(RuntimeError):
    """Raised when a build is already in progress for the target database."""


class GraphWriteSession:
    """
    Atomic write context for the design graph.

    Writes all nodes to a hidden temporary database, then atomically renames
    it to the final path on success.  On any failure the temp is discarded and
    the pre-existing final database is left intact — the caller never sees a
    partially-written graph.

    Usage::

        with GraphWriteSession(db_path) as writer:
            writer.write_tokens(tokens)
            for comp in components:
                writer.write_component(comp)
        # final path now holds the complete fresh graph
    """

    def __init__(self, final_path: Path) -> None:
        self._final = final_path
        self._temp  = final_path.parent / f".{final_path.name}.building"
        self._lock_path = final_path.parent / f".{final_path.name}.lock"
        self._lock_file: TextIO | None = None
        self._db:   kuzu.Database   | None = None
        self._conn: kuzu.Connection | None = None
        self._writer: GraphWriter | None = None

    def __enter__(self) -> "GraphWriter":
        self._final.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        try:
            self._cleanup_temp()
            self._db   = kuzu.Database(str(self._temp))
            self._conn = kuzu.Connection(self._db)
            initialize_schema(self._conn)
        except Exception:
            self._release_lock()
            raise
        self._writer = GraphWriter(self._conn)
        return self._writer

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None and self._writer is not None:
            self._writer.commit()
        self._release_db()
        if exc_type is None:
            self._swap_temp_to_final()
        else:
            self._cleanup_temp()
        self._release_lock()
        return False  # never suppress exceptions

    # ── Private helpers ───────────────────────────────────────────────────────

    def _acquire_lock(self) -> None:
        """
        Take an exclusive, non-blocking lock on a sentinel file next to the
        database so a second concurrent build (e.g. a manual build racing
        watch_prototype.sh) fails fast and clearly instead of corrupting the
        shared .building temp directory or the final database.
        """
        lock_file = open(self._lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock_file.close()
            raise BuildLockError(
                f"Another build is already in progress for {self._final.name} "
                f"(lock held at {self._lock_path}). Wait for it to finish, or "
                "remove the lock file manually if you're sure no build is running."
            ) from exc
        self._lock_file = lock_file

    def _release_lock(self) -> None:
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._lock_file.close()
            except OSError:
                pass
            self._lock_file = None
        self._lock_path.unlink(missing_ok=True)

    def _release_db(self) -> None:
        """Close Kuzu handles so the OS releases any file locks before rename."""
        for handle_attr in ("_conn", "_db"):
            handle = getattr(self, handle_attr, None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                setattr(self, handle_attr, None)

    def _cleanup_temp(self) -> None:
        if self._temp.exists():
            if self._temp.is_dir():
                shutil.rmtree(str(self._temp), ignore_errors=True)
            else:
                self._temp.unlink(missing_ok=True)

    def _swap_temp_to_final(self) -> None:
        """Replace final path with temp (delete old first, then rename)."""
        if self._final.exists():
            if self._final.is_dir():
                shutil.rmtree(str(self._final), ignore_errors=True)
            else:
                self._final.unlink(missing_ok=True)
        self._temp.rename(self._final)
        logger.debug("write_session: committed %s", self._final)


class GraphWriter:
    """
    Collects one build's graph as rows (domain → rows) and writes them all
    in commit(), one batch per table (rows → Kuzu, see batch.py).

    Nothing reaches the database before commit(); a writer commits once —
    writing after that would silently lose any update to a node already
    written, so it raises instead.
    """

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn
        self._pending: GraphRows | None = GraphRows()
        self._known_comp_names:    set[str] = set()
        self._resolved_comp_names: set[str] = set()
        self._declared_screen_names: set[str] = set()
        self._inserted_token_ids:  set[str] = set()
        # Lowercased value → tokens written so far: how a literal style value finds its token.
        self._tokens_by_value:     dict[str, list[DesignToken]] = {}
        # Custom property name (`--accent`) → its tokens, one per mode.
        self._tokens_by_custom_property: dict[str, list[DesignToken]] = {}
        self._inserted_icon_ids:   set[str] = set()
        self._inserted_style_ids:  set[str] = set()
        self._inserted_inter_ids:  set[str] = set()
        self._inserted_text_ids:   set[str] = set()
        self._token_rel_keys:      set[str] = set()
        self._contains_keys:       set[str] = set()
        self._inserted_prop_ids:   set[str] = set()
        # (parent, child, order_index) deferred because child wasn't inserted yet
        self._pending_contains:    set[tuple[str, str, int]] = set()
        # Rows the database refused at commit, capped so a catastrophic run can't grow this unbounded
        self._write_errors:        list[str] = []

    @property
    def inserted_names(self) -> frozenset[str]:
        """Names of components already written — read-only snapshot."""
        return frozenset(self._resolved_comp_names)

    @property
    def _rows(self) -> GraphRows:
        if self._pending is None:
            raise RuntimeError("this graph was already committed — a writer commits once")
        return self._pending

    # ── Public write API ──────────────────────────────────────────────────────

    def commit(self) -> None:
        """Write every collected row to the database. Calling it again does nothing."""
        if self._pending is None:
            return
        rows, self._pending = self._pending, None
        errors = write_rows(self._conn, rows)
        self._write_errors.extend(errors[: self._MAX_TRACKED_WRITE_ERRORS - len(self._write_errors)])
        logger.debug("writer: committed (%d rows refused)", len(errors))

    def record_model(self, capture: str) -> None:
        """Record the model version this graph is written in and the capture that produced it."""
        self._rows.put_node("Model", str(MODEL_VERSION), {"version": MODEL_VERSION, "capture": capture})

    def write_tokens(self, tokens: list[DesignToken]) -> int:
        """Collect Token nodes. Returns the number of new tokens."""
        inserted = 0
        for token in tokens:
            if token.id in self._inserted_token_ids:
                continue
            self._rows.put_node("Token", token.id, {
                "id": token.id, "category": token.category, "label": token.label,
                "value": token.value, "usage": token.usage, "mode": token.mode,
            })
            self._inserted_token_ids.add(token.id)
            inserted += 1
            self._tokens_by_value.setdefault(token.value.lower(), []).append(token)
            if token.category == TokenCategory.CSS_VAR:
                self._tokens_by_custom_property.setdefault(token.label, []).append(token)
        logger.debug("writer: collected %d tokens", inserted)
        return inserted

    def write_icons(self, icons: list[IconAsset]) -> int:
        """
        Collect deduplicated Icon nodes. Returns the number of new icons — a
        caller passing repeated ids (same icon reused across many components)
        gets each one written exactly once.
        """
        inserted = 0
        for icon in icons:
            if icon.id in self._inserted_icon_ids:
                continue
            self._rows.put_node("Icon", icon.id, {"id": icon.id, "markup": icon.markup})
            self._inserted_icon_ids.add(icon.id)
            inserted += 1
        logger.debug("writer: collected %d icons", inserted)
        return inserted

    def write_module_texts(self, texts: list[TextEntry]) -> int:
        """
        Collect UIText nodes with no owning Component or Section — text
        from a module-level constant array (const DETAIL_TABS = [...])
        isn't rendered by any one component, so there's no node to relate
        it to via COMP_HAS_TEXT/SECTION_HAS_TEXT. Still directly queryable
        through list_texts()/search() exactly like any other UIText, which
        query the node type directly rather than through either edge.
        """
        inserted = sum(self._put_text_once(text) for text in texts)
        logger.debug("writer: collected %d module-level texts", inserted)
        return inserted

    def declare_screens(self, screens: list[ExtractedScreen]) -> None:
        """Materialize screen identities before resolving typed screen references."""
        for screen in screens:
            if screen.name in self._declared_screen_names:
                continue
            self._rows.put_node("Screen", screen.name, self._screen_row(screen, 0, screen.sections_count))
            self._declared_screen_names.add(screen.name)

    @staticmethod
    def _screen_row(screen: ExtractedScreen, component_count: int, sections_count: int) -> dict:
        return {
            "name": screen.name, "component_count": component_count, "sections_count": sections_count,
            "source_code": screen.source_code,
            "source_lang": screen.source_lang,
            "viewport_width": screen.viewport_width, "viewport_height": screen.viewport_height,
        }

    def _write_screen_relations(self, screen: ExtractedScreen) -> None:
        """Navigation and variant edges — only toward screens this build declared."""
        for link in dict.fromkeys(screen.links):
            if link.target not in self._declared_screen_names:
                logger.debug("writer: %s links to unknown screen %s — dropped", screen.name, link.target)
                continue
            self._rows.add_rel("NAVIGATES_TO", screen.name, link.target, label=link.label)
        if screen.variant_of in self._declared_screen_names:
            self._rows.add_rel("VARIANT_OF", screen.name, screen.variant_of, axis=screen.variant_axis)
        elif screen.variant_of:
            logger.debug("writer: %s varies unknown screen %s — dropped", screen.name, screen.variant_of)

    def write_component(self, comp: ExtractedComponent) -> None:
        """
        Collect the Component node with its Style, Interaction, UIText and
        ComponentProp sub-nodes and the CONTAINS relationships to child
        components. A definition replaces a shell collected earlier under
        the same name.
        """
        if comp.name in self._resolved_comp_names:
            logger.debug("writer: skipping duplicate component %s", comp.name)
            return

        self._rows.replace_node("Component", comp.name, {
            "name": comp.name, "comp_type": comp.comp_type,
            "source_code": comp.source_code,
            "source_lang": comp.source_lang,
            "declares_inline_styles": comp.declares_inline_styles, "occurrence": comp.occurrence,
            "classes": comp.classes, "truncated_fields": ",".join(sorted(comp.truncated_fields)),
            "referenced_data_json": json.dumps(comp.referenced_data) if comp.referenced_data else "",
        })
        self._known_comp_names.add(comp.name)
        self._resolved_comp_names.add(comp.name)

        self._write_component_styles(comp)
        self._write_component_interactions(comp)
        for text in comp.texts:
            if self._put_text_once(text):
                self._rows.add_rel("COMP_HAS_TEXT", comp.name, text.id)
        self._write_component_props(comp.name, comp.props)
        self._write_component_children(comp)

    def _write_component_styles(self, comp: ExtractedComponent) -> None:
        """HAS_STYLE edges plus the component-level (USES_TOKEN) and style-level (STYLE_USES_TOKEN) token links."""
        for style in comp.styles:
            self._put_style_once(style)
            self._rows.add_rel("HAS_STYLE", comp.name, style.id)
            for token in self._tokens_by_value.get(style.value.lower(), []) + self._referenced_tokens(style.value):
                rel_key = f"{comp.name}_{token.id}"
                if rel_key not in self._token_rel_keys:
                    self._token_rel_keys.add(rel_key)
                    self._rows.add_rel("USES_TOKEN", comp.name, token.id)
            self._link_style_to_token(style)

    def _write_component_interactions(self, comp: ExtractedComponent) -> None:
        for inter in comp.interactions:
            if inter.id in self._inserted_inter_ids:
                continue
            self._inserted_inter_ids.add(inter.id)
            self._rows.put_node("Interaction", inter.id, {
                "id": inter.id, "trigger": inter.trigger, "css_prop": inter.css_prop,
                "from_val": inter.from_val, "to_val": inter.to_val, "transition": inter.transition,
            })
            self._rows.add_rel("HAS_INTERACTION", comp.name, inter.id)

    def _write_component_children(self, comp: ExtractedComponent) -> None:
        """
        CONTAINS relationships: collected now for already-collected children,
        deferred for the rest so flush_pending_contains() can retry after all
        nodes exist. order_index is comp.child_refs' own position —
        first-appearance order in the source JSX (see component_extractor.py),
        not alphabetical — so a reader can recover sibling render order
        without re-parsing JSX.
        """
        for order_index, child_name in enumerate(comp.child_refs):
            if child_name in self._resolved_comp_names:
                self._write_contains_edge(comp.name, child_name, order_index)
            else:
                self._pending_contains.add((comp.name, child_name, order_index))

    def flush_pending_contains(self) -> int:
        """
        Retry all deferred CONTAINS edges now that more components may exist.

        Must be called only after every write_component() call for this
        build has completed — a child still unresolved at that point is
        treated as final and permanent (nothing later in the same build
        could still resolve it), not as "maybe next time". Safe to call
        more than once: _contains_keys still guards against duplicate
        edges, and a second call simply finds nothing left pending.

        A child that's still unresolved here is external to the bundle —
        most commonly a library import (e.g. `<ChevronRight />` from
        lucide-react) rather than a local function this pipeline could ever
        have extracted. Before this fix, such a child silently vanished:
        the edge stayed in _pending_contains forever and was only logged at
        debug, never written — an agent asking get_component_children for
        the parent got back nothing, with no signal that a real reference
        existed. Now it gets the same shell-Component treatment
        (_ensure_component_exists, occurrence=UNRESOLVED) already used for
        a screen/section referencing an undefined component — the CONTAINS
        edge is written, and the reference is at least visible by name
        even with no markup/props known for it.

        A child whose name matches an already-declared Screen is skipped
        entirely instead — CONTAINS is typed Component→Component in the
        schema, so "creating a shell" for such a name would actually create
        a second, unrelated Component node that happens to share its name
        with a real Screen (get_component_spec('RestaurantsPage') would
        then "find" an empty shell instead of correctly reporting that name
        as a screen, not a component). write_screen/write_component already
        make this same distinction for their own component_refs via
        _declared_screen_names — this is the same guard, applied here too
        (found in C34 auditing an earlier session's C32 change, confirmed
        against a real rebuild where screen names like DashboardPage showed
        up as "unresolved components").

        Returns the number of new edges created.
        """
        created = 0
        for parent, child, order_index in self._pending_contains:
            if child in self._declared_screen_names:
                continue
            if child not in self._resolved_comp_names:
                self._ensure_component_exists(child)
            if self._write_contains_edge(parent, child, order_index):
                created += 1
        self._pending_contains = set()
        return created

    def _write_contains_edge(self, parent: str, child: str, order_index: int = 0) -> bool:
        """Collect a single CONTAINS edge if not already present. Returns True if new."""
        key = f"{parent}→{child}"
        if key in self._contains_keys:
            return False
        self._contains_keys.add(key)
        self._rows.add_rel("CONTAINS", parent, child, weight=1, order_index=order_index)
        return True

    def write_screen(self, screen: ExtractedScreen, sections: list[ExtractedSection]) -> None:
        """
        Collect the Screen node, USES_COMPONENT edges, Section nodes, and SECTION_USES edges.
        Creates "shell" Component nodes for references that were never extracted as functions.
        """
        component_refs = [
            name for name in screen.component_refs if name not in self._declared_screen_names
        ]
        # A declared screen is completed in place; an undeclared one is written once, like any node.
        put = self._rows.replace_node if screen.name in self._declared_screen_names else self._rows.put_node
        put("Screen", screen.name, self._screen_row(screen, len(component_refs), len(sections)))

        for comp_name in screen.component_refs:
            if comp_name in self._declared_screen_names:
                self._rows.add_rel("USES_SCREEN", screen.name, comp_name)
                continue
            self._ensure_component_exists(comp_name)
            self._rows.add_rel("USES_COMPONENT", screen.name, comp_name)

        self._write_screen_relations(screen)

        for section in sections:
            self._write_section(screen.name, section)

        logger.debug("writer: collected screen %s with %d sections", screen.name, len(sections))

    def _write_section(self, screen_name: str, section: ExtractedSection) -> None:
        self._rows.put_node("Section", section.id, {
            "id": section.id, "screen": section.screen, "name": section.name,
            "styles_json": json.dumps(section.styles),
            "components_json": json.dumps(section.component_refs),
            "texts_json": json.dumps(section.texts),
            "source_code": section.source_code,
            "source_lang": section.source_lang, "detection_method": section.detection_method,
        })
        self._rows.add_rel("HAS_SECTION", screen_name, section.id)
        self._write_section_styles(section.id, section.styles, section.element_styles)
        self._write_section_texts(section.id, section.texts)
        for comp_name in section.component_refs:
            if comp_name in self._declared_screen_names:
                self._rows.add_rel("SECTION_USES_SCREEN", section.id, comp_name)
                continue
            self._ensure_component_exists(comp_name)
            self._rows.add_rel("SECTION_USES", section.id, comp_name)

    def get_stats(self) -> dict[str, int]:
        """Execute STATS_QUERIES and return node/rel counts."""
        stats: dict[str, int] = {}
        for name, cypher in STATS_QUERIES.items():
            try:
                result = self._conn.execute(cypher)
                stats[name] = result.get_next()[0] if result.has_next() else 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("writer: stats query failed for %s: %s", name, exc)
                stats[name] = -1
        stats["write_errors"] = len(self._write_errors)
        return stats

    # ── Private helpers ───────────────────────────────────────────────────────

    def _put_text_once(self, text: TextEntry) -> bool:
        """Collect a UIText node unless one with its id already was. Returns True if new."""
        if text.id in self._inserted_text_ids:
            return False
        self._inserted_text_ids.add(text.id)
        self._rows.put_node("UIText", text.id, {
            "id": text.id, "content": text.content, "text_type": text.text_type,
            "source": text.source, "element": text.element,
        })
        return True

    def _put_style_once(self, style: StyleEntry) -> None:
        """
        Collect a Style node exactly once, no matter how many different
        owners (components, sections) reference the same one — a shared
        CSS class resolves to the same StyleEntry id everywhere it's used
        (StyleEntry.from_css_class's seed is class+property+value, not the
        owner). The caller is responsible for its own ownership edge
        (HAS_STYLE/SECTION_HAS_STYLE) regardless of whether the node
        already existed — skipping the edge here, not just the node, used
        to make every owner after the first silently lose the relationship
        (see docs/changes/C36).
        """
        if style.id in self._inserted_style_ids:
            return
        self._inserted_style_ids.add(style.id)
        self._rows.put_node("Style", style.id, {
            "id": style.id, "element": style.element, "state": style.state,
            "property": style.property, "value": style.value, "media": style.media or "",
        })

    def _write_section_styles(
        self, section_id: str, literal_styles: dict, element_styles: list[StyleEntry],
    ) -> None:
        """
        Collect section container styles as Style nodes linked via SECTION_HAS_STYLE.

        `literal_styles` are property→value pairs from inline style={{}}
        objects found in the section's markup — no selector identity, so
        each is attributed to the section as a whole via StyleEntry.
        for_section. `element_styles` are CSS-class-resolved StyleEntry
        objects that already carry their real selector (element=
        "class:<name>") from resolve_classes() — written as-is, never
        re-wrapped, so a per-class query (find_styles_by_class) can find
        them regardless of which section happened to reference them.
        """
        entries = [
            StyleEntry.for_section(section_id=section_id, property=prop, value=str(value))
            for prop, value in literal_styles.items()
        ]
        entries.extend(element_styles)
        for style in entries:
            self._put_style_once(style)
            self._rows.add_rel("SECTION_HAS_STYLE", section_id, style.id)

    def _write_component_props(self, comp_name: str, props: list[ComponentProp]) -> None:
        """
        Collect ComponentProp nodes and HAS_PROP edges for a component.

        Each declared prop becomes one ComponentProp node. Idempotent — duplicate
        prop ids are tracked and skipped so calling write_component twice is safe.
        """
        for prop in props:
            if prop.id in self._inserted_prop_ids:
                continue
            self._inserted_prop_ids.add(prop.id)
            self._rows.put_node("ComponentProp", prop.id, {
                "id": prop.id, "component_name": prop.component_name,
                "prop_name": prop.prop_name, "default_value": prop.default_value,
            })
            self._rows.add_rel("HAS_PROP", comp_name, prop.id)

    def _write_section_texts(self, section_id: str, texts: list[str]) -> None:
        """
        Collect section text strings as UIText nodes linked via SECTION_HAS_TEXT.

        Each string becomes one UIText node with text_type='section_text' and
        source=section_id. This replaces the opaque texts_json blob as the
        canonical query target for section text content.
        """
        for text in texts:
            entry = TextEntry.for_section(section_id=section_id, text=text)
            if self._put_text_once(entry):
                self._rows.add_rel("SECTION_HAS_TEXT", section_id, entry.id)

    def _ensure_component_exists(self, name: str) -> None:
        """Collect a minimal 'shell' component unless one by that name already was."""
        if name in self._known_comp_names:
            return
        self._known_comp_names.add(name)
        self._rows.put_node("Component", name, {
            "name": name, "comp_type": ComponentType.COMPONENT, "source_code": "", "source_lang": "",
            "declares_inline_styles": False,
            "occurrence": ComponentDefinitionStatus.UNRESOLVED.value, "classes": "",
            "truncated_fields": "", "referenced_data_json": "",
        })

    def _link_style_to_token(self, style: StyleEntry) -> None:
        """
        Collect STYLE_USES_TOKEN edges (Style → Token). A value that references
        custom properties (`var(--accent)`) uses each referenced token in
        every mode it was defined in. Otherwise the value is matched against
        token values — exact case-insensitive match first, then substring —
        and at most one edge is created (first match wins).
        """
        referenced = self._referenced_tokens(style.value)
        if referenced:
            for token in referenced:
                self._rows.add_rel("STYLE_USES_TOKEN", style.id, token.id)
            return

        normalized = style.value.strip().lower()

        # Fast path: exact match via the value index (already lowercased)
        exact_tokens = self._tokens_by_value.get(normalized, [])
        if exact_tokens:
            self._rows.add_rel("STYLE_USES_TOKEN", style.id, exact_tokens[0].id)
            return

        # Substring match: token value appears inside style value (e.g. rgba with hex)
        for token_value_lower, tokens in self._tokens_by_value.items():
            if token_value_lower and len(token_value_lower) >= 4 and token_value_lower in normalized:
                self._rows.add_rel("STYLE_USES_TOKEN", style.id, tokens[0].id)
                return

    def _referenced_tokens(self, value: str) -> list[DesignToken]:
        """Tokens of every custom property `value` references, in every mode."""
        return [
            token
            for name in dict.fromkeys(RE_CUSTOM_PROPERTY_REFERENCE.findall(value))
            for token in self._tokens_by_custom_property.get(name, [])
        ]

    _MAX_TRACKED_WRITE_ERRORS = 50
