"""
Portuguese/English alias map for the MCP search tool.

Keeping aliases isolated here means search.py has no language-specific
knowledge and aliases can be extended without touching any other module.
"""

from __future__ import annotations

_ALIASES: dict[str, list[str]] = {
    # Components PT → technical names
    "botão":       ["Btn", "Button", "button"],
    "botao":       ["Btn", "Button", "button"],
    "modal":       ["Modal", "Dialog", "Confirm", "Overlay"],
    "dialogo":     ["Modal", "Dialog"],
    "diálogo":     ["Modal", "Dialog"],
    "cartão":      ["Card", "SectionCard", "RestCard", "MenuCard"],
    "cartao":      ["Card", "SectionCard"],
    "tabela":      ["Table", "DataTable", "Grid"],
    "aba":         ["Tab", "TabBar"],
    "abas":        ["Tab", "Tabs"],
    "badge":       ["Badge", "Tag", "Pill", "Chip"],
    "tag":         ["Badge", "Tag"],
    "entrada":     ["Input", "Field", "TextField"],
    "campo":       ["Input", "Field"],
    "formulario":  ["Form", "FormSection", "SectorForm"],
    "formulário":  ["Form", "FormSection"],
    "menu":        ["Menu", "Nav", "Sidebar", "Topbar"],
    "barra":       ["Bar", "Header", "Topbar", "Nav"],
    "gaveta":      ["Drawer", "ProfileDrawer"],
    "painel":      ["Panel", "TweaksPanel", "StripePanel"],
    "secao":       ["Section", "SectionCard"],
    "seção":       ["Section", "SectionCard"],
    "toggle":      ["Toggle", "Switch", "SwitchRow"],
    "switch":      ["Toggle", "Switch"],
    "lista":       ["List", "InventoryItemsList", "ComponentsList"],
    "kpi":         ["KpiCard", "KPI", "metric"],
    "grafico":     ["Chart", "AreaChart", "DonutChart", "Sparkline"],
    "gráfico":     ["Chart", "AreaChart", "DonutChart"],
    "avatar":      ["Avatar", "RestaurantAvatar"],
    "icone":       ["Icon", "IconBtn"],
    "ícone":       ["Icon", "IconBtn"],
    "cor":         ["color", "primary", "bg"],
    "fundo":       ["background", "bg"],
    "hover":       ["hover", "mouseenter"],
    "primario":    ["primary", "#ffb81c"],
    "primário":    ["primary", "#ffb81c"],
    # Screens / layout
    "tela":        ["Screen", "Page", "screen", "page"],
    # Typography
    "tipografia":  ["typography", "Typography", "font", "Font", "text"],
    # Shadow tokens
    "sombra":      ["shadow", "Shadow"],
    # Radius tokens
    "raio":        ["radius", "Radius"],
    "arredondado": ["radius", "rounded"],
    # Status colors
    "sucesso":     ["success", "#22c55e"],
    "erro":        ["danger", "error", "#ef4444"],
    "info":        ["info", "#60a5fa"],
    "premium":     ["premium", "#a78bfa"],
}


def get_aliases() -> dict[str, list[str]]:
    """Return a copy of the alias map. Callers cannot mutate the internal map."""
    return dict(_ALIASES)
