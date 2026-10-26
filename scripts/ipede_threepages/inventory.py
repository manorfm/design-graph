"""Neutral decode and conservative routing evidence. Unknown syntax requires review."""
from __future__ import annotations
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from design_graph.capture.bundler import read_bundle
from design_graph.capture.resources import is_infrastructure, is_script, script_resource
from .common import digest, fresh, write_json


def decode(source, out):
    """Manifest insertion order, then inline template scripts; UTF-8 byte offsets.

    Uses the inspected production decoder and vendor signature classifier only;
    it does not use graph extraction to determine experimental route truth.
    """
    out = fresh(out)
    bundle = read_bundle(Path(source).read_text())
    if bundle is None:
        raise ValueError('expected a self-contained manifest/template bundle')
    (out/'template.html').write_text(bundle.template)
    resources, modules, cursor = [], [], 0
    for i, (key, entry) in enumerate(bundle.manifest.items()):
        data = bundle.entry(key)
        path = out/f'resource-{i:03d}'
        path.write_bytes(data)
        resource = script_resource(key, data, bundle.urls.get(key, '')) if is_script(entry['mime']) else None
        application = resource is not None and not is_infrastructure(resource)
        record = dict(id=key, file=path.name, mime=entry['mime'], bytes=len(data), sha256=digest(path),
                      application=application, classification=resource.kind.value if resource else 'asset',
                      declared_url=bundle.urls.get(key))
        if application:
            text = data.decode('utf-8', errors='strict')
            record['application_offset_bytes'] = cursor
            modules.append(dict(file=path.name, text=text, offset=cursor, id=key))
            cursor += len(data) + 1
        resources.append(record)
    for i, script in enumerate(BeautifulSoup(bundle.template, 'html.parser').find_all('script')):
        if script.get('src') or not script.get_text().strip():
            continue
        text = script.get_text()
        path = out/f'inline-{i:03d}.js'
        path.write_text(text)
        modules.append(dict(file=path.name, text=text, offset=cursor, id=f'inline:{i}'))
        cursor += len(text.encode()) + 1
    (out/'application.js').write_text('\n'.join(m['text'] for m in modules))
    write_json(out/'resources.json', resources)
    return bundle, resources, modules


def byte_offset(text, character):
    return len(text[:character].encode('utf-8'))


def route_inventory(modules):
    combined = '\n'.join(m['text'] for m in modules)
    nav = re.search(r'^const\s+NAV\s*=\s*\[(.*?)\n\];', combined, re.S | re.M)
    app = re.search(r'^function\s+App\s*\(', combined, re.M)
    if not nav or not app:
        raise ValueError('unsupported router: explicit private route decision required')
    routes = re.findall(r"key:\s*'([^']+)'\s*,\s*label:\s*'([^']+)'", nav[1])
    defaults = re.search(r'^const\s+TWEAK_DEFAULTS\s*=\s*/\*EDITMODE-BEGIN\*/(.*?)/\*EDITMODE-END\*/', combined, re.S | re.M)
    defaults = json.loads(defaults[1]) if defaults else {}
    definitions = {}
    for module in modules:
        for match in re.finditer(r'\bfunction\s+(\w+)\s*\(', module['text']):
            # Earliest declaration is evidence, aliases below resolve actual router targets.
            definitions.setdefault(match[1], (module, match.start()))
    aliases = dict(re.findall(r'window\.[\w.]+\.(\w+)\s*=\s*(\w+)\s*;', combined))
    inventory = []
    for ordinal, (key, label) in enumerate(routes):
        route = re.search(r"page\s*===\s*'" + re.escape(key) + r"'\s*\?\s*\(", combined[app.start():])
        if route:
            start = app.start()+route.start()
            branch = combined[start:]
            end = re.search(r"\)\s*:\s*page\s*===|\)\s*:\s*\(\s*<PlaceholderPage", branch)
            branch = branch[:end.start()] if end else branch
            tags = re.findall(r'<([\w.]+)', branch)
            targets = [x.split('.')[-1] for x in tags if x.split('.')[-1] in definitions or x.split('.')[-1] in aliases]
            # restaurants has an explicit list/detail state; default is the list.
            target = next((x for x in reversed(targets) if x.endswith('Page') or x.endswith('PageV6')), targets[0] if targets else None)
        else:
            start = combined.index('<PlaceholderPage', app.start())
            target = 'PlaceholderPage'
        target = aliases.get(target, target)
        if target not in definitions:
            raise ValueError(f'unresolved route {key}: {target}; parent decision required')
        module, pos = definitions[target]
        head = module['text'][pos:]
        next_def = re.search(r'\nfunction\s+', head[1:])
        body = head[:next_def.start()+1] if next_def else head
        states = re.findall(r'const\s*\[([^\]]+)\]\s*=\s*(?:React\.)?useState\(([^\n]*)', body)
        inventory.append(dict(key=key, label=label, component=target, nav_ordinal=ordinal,
            module=module['file'], module_offset_bytes=byte_offset(module['text'], pos),
            application_offset_bytes=module['offset']+byte_offset(module['text'], pos),
            route_offset_bytes=byte_offset(combined, start), placeholder=target=='PlaceholderPage',
            entry=dict(nav_label=label, storage='empty fresh context', tweaks=defaults,
                       selectedRestaurant=None, profileOpen=False, local_state_initializers=states)))
    inventory.sort(key=lambda x:(x['application_offset_bytes'], x['nav_ordinal']))
    # Secondary surfaces are kept as candidates with real render callsites, never helper declarations.
    nested = []
    for module in modules:
        for match in re.finditer(r"(?:\b(?:tab|view|step)\s*===\s*[^\n]{0,160}|selectedRestaurant\s*\?\s*\(|showProfile[^\n]{0,80})", module['text']):
            nested.append(dict(module=module['file'], module_offset_bytes=byte_offset(module['text'],match.start()),
                               evidence=match.group(), eligible=False,
                               exclusion_reason='nested surface excluded by settled root NAV scope'))
    eligible = [r for r in inventory if not r['placeholder']]
    if len(eligible) < 3:
        raise ValueError('at least three implemented root NAV routes required')
    for route in inventory:
        route['eligible'] = not route['placeholder']
        route['exclusion_reason'] = ('shared placeholder has no page-specific implementation or primary functionality'
                                     if route['placeholder'] else None)
    indexes = [0, (len(eligible)-1)//2, len(eligible)-1]
    return dict(routes=inventory, eligible_routes=eligible, nested_candidates=nested, defaults=defaults,
                scope_decision='parent-settled: actual root NAV routes only; shared placeholders and nested surfaces excluded',
                ordering='decoded application UTF-8 bytes; manifest insertion order then inline template scripts; newline separators; ties NAV order',
                median_convention='lower (n-1)//2', selection_indexes=indexes,
                selection=[eligible[i] for i in indexes], review_required=False)
