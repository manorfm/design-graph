"""
Resolve component re-export bindings: `const Badge = window.V6K.Pill;`.

Some prototypes rename a component and keep the old name alive as a plain
assignment for backward compatibility, instead of wrapping it in a function.
Neither RE_COMP_FN nor RE_COMP_ARROW_FN treats that as a component
definition (there's no function body to extract), so JSX references to the
alias name would otherwise resolve to an empty, unresolved component shell —
losing the props, styles and JSX that were already captured under the real
name. Resolving the alias up front means every reference converges on the
one component that actually has that information.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from design_graph.core.patterns import RE_COMPONENT_ALIAS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComponentAlias:
    """A validated `const Alias = ns.Target;` re-export binding."""

    name: str
    target: str

    def __post_init__(self) -> None:
        if self.name == self.target:
            raise ValueError(f"component alias cannot reference itself: {self.name}")


def extract_component_aliases(js: str, known_component_names: set[str]) -> dict[str, str]:
    """
    Find re-export bindings whose target is a component already extracted
    from this same source, and return {alias_name: target_name}.

    A target outside known_component_names is not an alias we can act on —
    it's either not a component at all (a theme/constants namespace member)
    or one this pass never saw, and guessing would be worse than leaving the
    reference to resolve on its own.
    """
    aliases: dict[str, str] = {}
    for match in RE_COMPONENT_ALIAS.finditer(js):
        name, target = match.group(1), match.group(2)
        try:
            alias = ComponentAlias(name=name, target=target)
        except ValueError:
            logger.debug("alias_extractor: skipping degenerate alias %r → %r", name, target)
            continue
        if alias.target in known_component_names:
            aliases[alias.name] = alias.target
    return aliases


def apply_aliases(refs: list[str], aliases: dict[str, str]) -> list[str]:
    """Replace each alias name in refs with its target, sorted and deduped."""
    return sorted({aliases.get(ref, ref) for ref in refs})
