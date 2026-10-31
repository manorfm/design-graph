"""Bounded real pinned native captures; no database or assembly."""

import json
import os
import subprocess
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
NODE = Path(os.environ["DG_CAPTURE_NODE"])
ENGINE = Path(os.environ["DG_CAPTURE_ENGINE"])
FP = os.environ["DG_CAPTURE_FINGERPRINT"]


def test_native_opt_in_source_syntax_and_unchanged_legacy():
    request = {
        "source": "const K=window.V6K; K.hueFromName();",
        "engine": str(ENGINE),
        "syntax": "js",
        "source_type": "script",
    }

    def run():
        result = subprocess.run(
            [
                str(NODE),
                str(ROOT / "src/design_graph/capture/binding_engine/capture.mjs"),
            ],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return json.loads(result.stdout)

    legacy = run()
    assert "source_syntax" not in legacy
    request["source_syntax"] = "source-syntax/1"
    extended = run()
    assert "source_syntax" in extended, (
        "native producer discarded requested source syntax"
    )
    syntax = extended.pop("source_syntax")
    assert extended == legacy
    assert syntax["version"] == "source-syntax/1"
    assert len(syntax["aliases"]) == 1
    assert any(u["key"]["name"] == "hueFromName" for u in syntax["uses"])


def test_typed_candidate_projection_uses_native_value_not_property_name():
    from design_graph.capture.binding_capture import BindingCapture

    producer = BindingCapture(node=NODE, toolchain=ENGINE, fingerprint=FP)
    capture = getattr(producer, "capture_source_syntax", None)
    assert callable(capture), "producer lacks explicit checked source-syntax capture"
    provider = capture(
        b"function actualHelper() {} const hueFromName=99; window.V6K={hueFromName:actualHelper};",
        locator="fixture:provider",
        source_type="script",
        syntax="js",
    )
    consumer = capture(
        b"const K=window.V6K; K.hueFromName();",
        locator="fixture:consumer",
        source_type="script",
        syntax="js",
    )
    from design_graph.model.source_syntax import (
        SourceInventory,
        SourceSyntaxCapture,
        project_candidates,
    )

    restored = SourceSyntaxCapture.from_json(provider.to_json())
    assert restored == provider
    scope = SourceInventory(
        "snapshot:test",
        "fixture:input",
        (provider.lexical.ir.units[0].id, consumer.lexical.ir.units[0].id),
    )
    result = project_candidates(
        scope, (provider, consumer), consumer.lexical.ir.units[0].id, "u1"
    )
    assert result.status == "source-candidate"
    assert result.runtime_claim is False
    assert len(result.candidates) == 1
    target = result.candidates[0]
    binding = next(b for b in provider.lexical.ir.bindings if b.id == target.binding)
    assert binding.name == "actualHelper"
    assert {
        "host-root-unknown",
        "global-writes-unknown",
        "execution-order-unknown",
        "unknown-scripts",
    } <= set(result.unresolved_alternatives)


P = "function actualHelper() { return 7; } const hueFromName=99; window.V6K={hueFromName:actualHelper};"
C = 'const K=window.V6K; function Avatar(){ return K.hueFromName("a"); }'


@lru_cache(maxsize=64)
def captured(source, locator="fixture:unit"):
    from design_graph.capture.binding_capture import BindingCapture

    return BindingCapture(
        node=NODE, toolchain=ENGINE, fingerprint=FP
    ).capture_source_syntax(
        source.encode(), locator=locator, source_type="script", syntax="js"
    )


def select(provider=P, consumer=C):
    from design_graph.model.source_syntax import SourceInventory, project_candidates

    p, c = (
        captured(provider, "fixture:provider"),
        captured(consumer, "fixture:consumer"),
    )
    unit = c.source_syntax.unit
    use = c.source_syntax.uses[-1]
    return project_candidates(
        SourceInventory("snapshot:test", "fixture:input", (p.source_syntax.unit, unit)),
        (p, c),
        unit,
        use.id,
    )


@pytest.mark.parametrize(
    "provider,consumer,status,count,risk",
    [
        (
            P,
            C.replace("function Avatar()", "function Avatar(K)"),
            "unresolved",
            0,
            None,
        ),
        (
            P,
            "function Avatar(window){ const K=window.V6K; return K.hueFromName(); }",
            "unresolved",
            0,
            None,
        ),
        (
            P,
            C.replace("const K=", "let K=").replace(
                "; function", "; K=other; function"
            ),
            "source-candidate",
            1,
            "alias-mutable-or-reassigned",
        ),
        (
            P.replace("hueFromName:actualHelper", '["hueFromName"]:actualHelper'),
            C,
            "unresolved",
            0,
            "unsupported-publication-object",
        ),
        (
            P + "window.V6K={hueFromName:actualHelper};",
            C,
            "ambiguous",
            2,
            "duplicate-publication-candidates",
        ),
        (
            P.replace(
                "hueFromName:actualHelper",
                "hueFromName:actualHelper,hueFromName:actualHelper",
            ),
            C,
            "unresolved",
            0,
            "missing-or-duplicate-property",
        ),
        (
            P + "window.V6K.hueFromName=replacement;",
            C,
            "source-candidate",
            1,
            "global-writes-unknown",
        ),
        (
            P.replace(
                "hueFromName:actualHelper", "get hueFromName(){return actualHelper}"
            ),
            C,
            "unresolved",
            0,
            "unsupported-publication-object",
        ),
        (P, C, "source-candidate", 1, "unknown-scripts"),
        (
            "function actualHelper(){} function publish(window){window.V6K={hueFromName:actualHelper};}",
            C,
            "unresolved",
            0,
            None,
        ),
        (
            P.replace(
                "hueFromName:actualHelper", "hueFromName(){return actualHelper()}"
            ),
            C,
            "unresolved",
            0,
            "unsupported-publication-object",
        ),
        (
            P.replace("hueFromName:actualHelper", "...other,hueFromName:actualHelper"),
            C,
            "unresolved",
            0,
            "unsupported-publication-object",
        ),
    ],
)
def test_finite_controls(provider, consumer, status, count, risk):
    result = select(provider, consumer)
    assert result.status == status
    assert len(result.candidates) == count
    assert result.runtime_claim is False
    if risk:
        assert risk in result.unresolved_alternatives


def test_computed_use_is_explicit_unsupported_not_static_member():
    c = captured('const K=window.V6K; K["hueFromName"](); K?.hueFromName();')
    assert not any(u.key.name == "hueFromName" for u in c.source_syntax.uses)
    assert len(c.source_syntax.unsupported) == 2


@pytest.mark.parametrize("prefix", ["", "\ufeff", "// 😀\r\n"])
def test_escaped_keys_astral_bom_crlf_native_identity(prefix):
    p = prefix + P.replace("hueFromName:actualHelper", r"hue\u0046romName:actualHelper")
    c = prefix + C.replace("K.hueFromName", r"K.hue\u{46}romName")
    result = select(p, c)
    assert result.status == "source-candidate"
    assert result.runtime_claim is False


@pytest.mark.parametrize(
    "mutation",
    [
        "key",
        "foreign-ref",
        "declaration",
        "binding",
        "unit",
        "span",
        "bool-int",
        "kind",
        "native-target",
        "unknown",
        "version",
    ],
)
def test_hostile_closed_admission(mutation):
    from design_graph.model.source_syntax import SourceSyntaxCapture

    value = asdict(captured(P))
    s = value["source_syntax"]
    if mutation == "key":
        s["publications"][0]["members"][0]["key"]["name"] = "fabricated"
    elif mutation == "foreign-ref":
        s["publications"][0]["members"][0]["value_reference"] = "foreign:ref0"
    elif mutation == "declaration":
        value = asdict(captured(C))
        value["source_syntax"]["aliases"][0]["declaration"] = "d999"
    elif mutation == "binding":
        value = asdict(captured(C))
        value["source_syntax"]["aliases"][0]["binding"] = "b:" + "0" * 64
    elif mutation == "unit":
        s["unit"] = "u:" + "0" * 64
    elif mutation == "span":
        s["publications"][0]["object_span"]["end"] += 1
    elif mutation == "bool-int":
        s["publications"][0]["members"][0]["computed"] = 0
    elif mutation == "kind":
        s["publications"][0]["members"][0]["kind"] = "getter"
    elif mutation == "native-target":
        value["lexical"]["ir"]["resolutions"][-1]["target"] = "b:" + "0" * 64
    elif mutation == "unknown":
        s["checked"] = True
    elif mutation == "version":
        value["version"] = "binding-capture/3"
    with pytest.raises(ValueError):
        SourceSyntaxCapture.from_json(json.dumps(value))


def test_removed_unsupported_alternative_and_typed_false_bool_rejected():

    c = captured(
        P.replace("hueFromName:actualHelper", "get hueFromName(){return actualHelper}")
    )
    with pytest.raises(ValueError, match="alternative"):
        replace(c, source_syntax=replace(c.source_syntax, unsupported=())).check()
    c = captured(P)
    pub = c.source_syntax.publications[0]
    member = replace(pub.members[0], computed=0)
    with pytest.raises(ValueError):
        replace(
            c,
            source_syntax=replace(
                c.source_syntax, publications=(replace(pub, members=(member,)),)
            ),
        ).check()


def test_foreign_inventory_legacy_unknown_and_reader_is_parser_free(monkeypatch):
    from design_graph.model.source_syntax import (
        SourceInventory,
        SourceSyntaxCapture,
        project_candidates,
        syntax_status,
    )

    p, c = captured(P), captured(C)
    assert syntax_status(c.lexical) == "unknown"
    assert syntax_status(c) == "captured"
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("reader spawned parser")
    )
    assert SourceSyntaxCapture.from_json(p.to_json()) == p
    with pytest.raises(ValueError, match="inventory"):
        project_candidates(
            SourceInventory("snapshot:test", "fixture:input", (p.source_syntax.unit,)),
            (p, c),
            c.source_syntax.unit,
            "u1",
        )
    with pytest.raises(ValueError, match="unknown"):
        project_candidates(
            SourceInventory("snapshot:test", "fixture:input", (p.source_syntax.unit,)),
            (p.lexical,),
            p.source_syntax.unit,
            "u0",
        )
    result = select()
    assert result.runtime_claim is False
    assert result.unresolved_alternatives


def test_publication_key_must_be_key_not_another_valid_identifier_token():
    from design_graph.model.source_syntax import Span, Token

    c = captured(P)
    pub = c.source_syntax.publications[0]
    member = pub.members[0]
    ref = next(r for r in c.lexical.ir.references if r.id == member.value_reference)
    changed = replace(member, key=Token(ref.name, Span(ref.start, ref.end)))
    with pytest.raises(ValueError, match="property"):
        replace(
            c,
            source_syntax=replace(
                c.source_syntax, publications=(replace(pub, members=(changed,)),)
            ),
        ).check()


def test_proto_setter_is_not_a_publication_value_property():
    result = select(
        "function actualHelper(){} window.V6K={__proto__:actualHelper};",
        "const K=window.V6K; K.__proto__();",
    )
    assert result.status == "unresolved"
    assert result.runtime_claim is False


def test_utf8_midpoint_span_and_candidate_unit_caps(monkeypatch):
    import design_graph.model.source_syntax as m

    c = captured("// 😀\r\n" + C)
    alias = c.source_syntax.aliases[0]
    with pytest.raises(ValueError, match="UTF8"):
        replace(
            c,
            source_syntax=replace(
                c.source_syntax,
                aliases=(
                    replace(
                        alias, declarator_span=m.Span(4, alias.declarator_span.end)
                    ),
                ),
            ),
        ).check()
    monkeypatch.setattr(m, "MAX_CANDIDATES", 1)
    with pytest.raises(ValueError, match="candidate budget"):
        select(P + "window.V6K={hueFromName:actualHelper};", C)
    with pytest.raises(ValueError, match="inventory"):
        m.project_candidates(
            m.SourceInventory(
                "snapshot:test", "fixture:input", (c.source_syntax.unit,)
            ),
            (c,) * (m.MAX_UNITS + 1),
            c.source_syntax.unit,
            "u1",
        )


def test_producer_refuses_missing_adapter_pin_entries(tmp_path, monkeypatch):
    from design_graph.capture.binding_capture import BindingCapture

    p = BindingCapture(node=NODE, toolchain=ENGINE, fingerprint=FP)
    p.assets = tmp_path
    (tmp_path / "source-syntax-pin.json").write_text(
        '{"version":"source-syntax-producer/1","files":{}}'
    )
    monkeypatch.setattr(p, "_verify_toolchain", lambda: None)
    monkeypatch.setattr(
        p, "_capture_native", lambda *a, **kw: pytest.fail("unverified producer ran")
    )
    with pytest.raises(ValueError, match="producer pin"):
        p.capture_source_syntax(
            C.encode(), locator="fixture:unit", source_type="script", syntax="js"
        )


def test_finite_transport_and_projection_work_budget(monkeypatch):
    import design_graph.model.source_syntax as m

    _p, c = captured(P), captured(C)
    with pytest.raises(ValueError):
        m.SourceSyntaxCapture.from_json(
            "[" * (m.MAX_DEPTH + 1) + "]" * (m.MAX_DEPTH + 1)
        )
    with pytest.raises(ValueError):
        m.SourceSyntaxCapture.from_json('{"version":1,"version":2}')
    monkeypatch.setattr(m, "MAX_FACTS", 0)
    with pytest.raises(ValueError, match="budget"):
        c.check()
    monkeypatch.setattr(m, "MAX_FACTS", 20_000)
    monkeypatch.setattr(m, "MAX_WORK", 0, raising=False)
    with pytest.raises(ValueError, match="work budget"):
        select()
