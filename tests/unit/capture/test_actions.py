"""What an event handler does, read from how it is written — shared by every capture."""

import pytest

from design_graph.capture.actions import effect_of, trigger_of


@pytest.mark.parametrize("handler,effect", [
    ("e => setTeamName(e.target.value)", "muda estado teamName"),
    ("() => setMemberRole(r)", "muda estado memberRole"),
    ("() => this.setState({ papel: o.id })", "muda estado papel"),
    ("onClose", "repassa ao pai onClose"),
    ("handleGenerateKey", "chama handleGenerateKey"),
    ("() => { setOpen(false); onSave(draft); }", "muda estado open · repassa ao pai onSave"),
    ("() => navigate('/apps')", "chama navigate"),
    ("{{o.pick}}", "chama o.pick"),
])
def test_the_effect_is_read_from_the_handler(handler, effect):
    assert effect_of(handler) == effect


@pytest.mark.parametrize("attribute,trigger", [
    ("onClick", "click"), ("onChange", "change"), ("onKeyDown", "keydown"), ("onClose", "close"),
    ("sc-camel-on-click", "click"), ("sc-on-submit", "submit"),
])
def test_the_trigger_is_read_from_the_attribute(attribute, trigger):
    assert trigger_of(attribute) == trigger
