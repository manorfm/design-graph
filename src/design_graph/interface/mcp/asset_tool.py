"""
get_asset — write a resource's files (a font family's files, an image) into
the workspace so an agent can use them, instead of putting bytes in a reply.

Everything lands under ASSETS_DIR in the workspace, in one folder per
resource. Folder and file names are derived here — a slug of the resource
name, the content's hash and an extension from a fixed list — never taken
from the prototype as given; a folder that resolves outside ASSETS_DIR, or
an ASSETS_DIR that is a symbolic link, is refused. A file is written only
when its content matches the hash it was stored under.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from design_graph.model.graph.reader import GraphReader

ASSETS_DIR = "design-graph-assets"
_EXTENSIONS = {
    "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf", "font/otf": ".otf",
    "image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
}
_MAX_SLUG_CHARS = 60


def get_asset(reader: GraphReader, name: str, workspace: Path) -> str:
    files = reader.get_resource_files(name)
    if not files:
        return f"Nenhum arquivo guardado para '{name}'. get_resources() lista as fontes e imagens que têm arquivos."
    base = workspace / ASSETS_DIR
    if base.is_symlink():
        return f"Recusado: {ASSETS_DIR}/ é um link simbólico — os arquivos só são gravados numa pasta real do workspace."
    folder = base / _slug(name)
    if not folder.resolve().is_relative_to(base.resolve()):
        return f"Recusado: o destino de '{name}' sairia de {ASSETS_DIR}/."

    written, refused = [], []
    for file in files:
        if hashlib.sha256(file["content"]).hexdigest() != file["sha256"]:
            refused.append(file["sha256"][:16])
            continue
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{file['sha256'][:16]}{_EXTENSIONS.get(file['mime'], '.bin')}"
        if not path.exists():
            path.write_bytes(file["content"])
        written.append(f"- `{path.relative_to(workspace).as_posix()}` ({file['mime']}, {len(file['content']):,} bytes)")

    lines = [f"# Arquivos de {name}", "", *written]
    if refused:
        lines.append(f"\n> {len(refused)} arquivo(s) não gravado(s): o conteúdo não confere com o hash guardado.")
    return "\n".join(lines)


def _slug(name: str) -> str:
    """A folder name made only of lowercase letters, digits and hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:_MAX_SLUG_CHARS].strip("-")
    return slug or "recurso"
