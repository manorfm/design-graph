"""
A reference is only resolved from the lexical scope recorded for it when that
scope covers the reference's own source occurrence. Relabelling an occurrence
to a disjoint sibling scope, together with a target that is nearest from that
scope, must be refused instead of published as a proved local binding.

The facts below are real classifier output (scopes, declarations and reads)
recorded from the pinned private parser, so no parser is needed to run them.
"""

from dataclasses import replace

import pytest

from design_graph.model.reference_accounting import ReferenceAccounting

FACTS = {
    "disjoint-sibling": (
        "function Other(){const X=[38];return X[0];} function Probe(){const X=[260];return X[0];}",
        [
            (0, None, "program", (0, 88)),
            (1, 0, "function", (0, 43)),
            (2, 1, "block", (16, 43)),
            (3, 0, "function", (44, 88)),
            (4, 3, "block", (60, 88)),
        ],
        [
            (0, "Other", "function", 0, (0, 43), (9, 14)),
            (1, "X", "const", 2, (17, 30), (23, 24)),
            (2, "Probe", "function", 0, (44, 88), (53, 58)),
            (3, "X", "const", 4, (61, 75), (67, 68)),
        ],
        [("X", (37, 38), 2, 1), ("X", (82, 83), 4, 3)],
    ),
    "ancestor": (
        "const X=[38]; function Probe(){const X=[260];return X[0];}",
        [
            (0, None, "program", (0, 58)),
            (1, 0, "function", (14, 58)),
            (2, 1, "block", (30, 58)),
        ],
        [
            (0, "X", "const", 0, (0, 13), (6, 7)),
            (1, "Probe", "function", 0, (14, 58), (23, 28)),
            (2, "X", "const", 2, (31, 45), (37, 38)),
        ],
        [("X", (52, 53), 2, 2)],
    ),
    "nested-block": (
        "const X=1; function Probe(){ {const X=2; X;} return X;}",
        [
            (0, None, "program", (0, 55)),
            (1, 0, "function", (11, 55)),
            (2, 1, "block", (27, 55)),
            (3, 2, "block", (29, 44)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (11, 55), (20, 25)),
            (2, "X", "const", 3, (30, 40), (36, 37)),
        ],
        [("X", (41, 42), 3, 2), ("X", (52, 53), 2, 0)],
    ),
    "closure": (
        "const X=1; function Probe(){const X=2; return ()=>X;}",
        [
            (0, None, "program", (0, 53)),
            (1, 0, "function", (11, 53)),
            (2, 1, "block", (27, 53)),
            (3, 2, "function", (46, 51)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (11, 53), (20, 25)),
            (2, "X", "const", 2, (28, 38), (34, 35)),
        ],
        [("X", (50, 51), 3, 2)],
    ),
    "parameters": (
        "const X=1; function Probe(p=X){const X=2;return p+X;}",
        [
            (0, None, "program", (0, 53)),
            (1, 0, "function", (11, 53)),
            (2, 1, "block", (30, 53)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (11, 53), (20, 25)),
            (2, "p", "parameter", 1, (26, 29), (26, 27)),
            (3, "X", "const", 2, (31, 41), (37, 38)),
        ],
        [("X", (28, 29), 1, 0), ("p", (48, 49), 2, 2), ("X", (50, 51), 2, 3)],
    ),
    "computed-template": (
        "const X=1;function Probe(p){return {[X]:`${X}-${p}`};}",
        [
            (0, None, "program", (0, 54)),
            (1, 0, "function", (10, 54)),
            (2, 1, "block", (27, 54)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (10, 54), (19, 24)),
            (2, "p", "parameter", 1, (25, 26), (25, 26)),
        ],
        [("X", (37, 38), 2, 0), ("X", (43, 44), 2, 0), ("p", (48, 49), 2, 2)],
    ),
    "switch": (
        "const X=1; function Probe(){switch(X){case 1: const X=2; return X;}}",
        [
            (0, None, "program", (0, 68)),
            (1, 0, "function", (11, 68)),
            (2, 1, "block", (27, 68)),
            (3, 2, "block", (28, 67)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (11, 68), (20, 25)),
            (2, "X", "const", 3, (46, 56), (52, 53)),
        ],
        [("X", (35, 36), 2, 0), ("X", (64, 65), 3, 2)],
    ),
    "unicode": (
        'const emoji="😀é"; const X=1; function Probe(){return X;}',
        [
            (0, None, "program", (0, 60)),
            (1, 0, "function", (33, 60)),
            (2, 1, "block", (49, 60)),
        ],
        [
            (0, "emoji", "const", 0, (0, 21), (6, 11)),
            (1, "X", "const", 0, (22, 32), (28, 29)),
            (2, "Probe", "function", 0, (33, 60), (42, 47)),
        ],
        [("X", (57, 58), 2, 1)],
    ),
    "hoist-var": (
        "function Probe(){return X;var X=1;}",
        [
            (0, None, "program", (0, 35)),
            (1, 0, "function", (0, 35)),
            (2, 1, "block", (16, 35)),
        ],
        [
            (0, "Probe", "function", 0, (0, 35), (9, 14)),
            (1, "X", "var", 1, (26, 34), (30, 31)),
        ],
        [("X", (24, 25), 2, 1)],
    ),
    "tdz-let": (
        "function Probe(){return X;let X=1;}",
        [
            (0, None, "program", (0, 35)),
            (1, 0, "function", (0, 35)),
            (2, 1, "block", (16, 35)),
        ],
        [
            (0, "Probe", "function", 0, (0, 35), (9, 14)),
            (1, "X", "let", 2, (26, 34), (30, 31)),
        ],
        [("X", (24, 25), 2, 1)],
    ),
    "ancestor-target-legit": (
        "const X=1; function Probe(){return X;}",
        [
            (0, None, "program", (0, 38)),
            (1, 0, "function", (11, 38)),
            (2, 1, "block", (27, 38)),
        ],
        [
            (0, "X", "const", 0, (0, 10), (6, 7)),
            (1, "Probe", "function", 0, (11, 38), (20, 25)),
        ],
        [("X", (35, 36), 2, 0)],
    ),
}


def accounting(case):
    source, scopes, declarations, references = FACTS[case]
    return ReferenceAccounting(
        len(source.encode("utf-8")),
        "contextual-jsx-1",
        tuple(
            {"id": i, "parent": parent, "kind": kind, "span": list(span)}
            for i, parent, kind, span in scopes
        ),
        tuple(
            {
                "id": i,
                "name": name,
                "kind": kind,
                "scope": scope,
                "span": list(span),
                "binding_span": list(binding),
            }
            for i, name, kind, scope, span, binding in declarations
        ),
        tuple(
            {
                "id": i,
                "name": name,
                "span": list(span),
                "scope": scope,
                "target": target,
                "role": "read",
                "status": "proved",
            }
            for i, (name, span, scope, target) in enumerate(references)
        ),
        (),
    )


def relabel(analysis, span, scope, target):
    references = tuple(
        {**r, "scope": scope, "target": target} if r["span"] == list(span) else r
        for r in analysis.references
    )
    assert references != analysis.references
    return replace(analysis, references=references)


@pytest.mark.parametrize("case", list(FACTS))
def test_captured_facts_remain_valid(case):
    accounting(case).validate()


def test_disjoint_sibling_scope_and_target_relabel_is_refused():
    analysis = accounting("disjoint-sibling")
    # Probe's read [82,83) moved to Other's block (scope 2 covers [16,43)) and
    # to Other's X, which is the nearest X from that scope.
    with pytest.raises(ValueError, match="outside its lexical scope"):
        relabel(analysis, (82, 83), scope=2, target=1).validate()


def test_switch_discriminant_keeps_its_enclosing_scope_and_outer_binding():
    # The switch block [28,67) spatially contains the discriminant [35,36),
    # yet the discriminant is read in the enclosing body scope: the reference
    # need only lie inside its own scope, not inside the innermost one.
    analysis = accounting("switch")
    analysis.validate()
    by_span = {tuple(r["span"]): (r["scope"], r["target"]) for r in analysis.references}
    assert by_span == {(35, 36): (2, 0), (64, 65): (3, 2)}


def test_unicode_read_span_is_counted_in_utf8_bytes():
    source = FACTS["unicode"][0]
    analysis = accounting("unicode")
    analysis.validate()
    (read,) = analysis.references
    assert source.encode("utf-8")[slice(*read["span"])] == b"X"


@pytest.mark.xfail(
    strict=True,
    reason="V2-R1 ancestor relabel: the module scope still contains the read; "
    "containment alone cannot tell it is not the active scope",
)
def test_ancestor_scope_and_target_relabel_is_refused():
    analysis = accounting("ancestor")
    with pytest.raises(ValueError):
        relabel(analysis, (52, 53), scope=0, target=0).validate()
