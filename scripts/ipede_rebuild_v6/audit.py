"""Conservative copy/trace gate; a clean string scan alone never accepts an output."""
import re
from difflib import SequenceMatcher
from pathlib import Path
from bs4 import BeautifulSoup
from design_graph.capture.bundler import read_bundle


def script_and_styles(source):
    text=Path(source).read_text(); bundle=read_bundle(text)
    parts=[text] if bundle is None else [bundle.template, *[
        bundle.entry(k).decode('utf-8',errors='replace') for k,e in bundle.manifest.items()
        if 'javascript' in e['mime'] or 'css' in e['mime']]]
    return parts


def copy_scan(source, output):
    text=Path(output).read_text(); soup=BeautifulSoup(text,'html.parser')
    if soup.find('iframe') or soup.find('script',src=True):
        raise ValueError('iframe or external/transplanted script')
    if re.search(r'(?i)(ReactDOM|createRoot\(|text/babel|__bundler/|V6Pages|data:text/html)',text):
        raise ValueError('original framework/bootstrap marker')
    if not soup.find('style'): raise ValueError('new CSS required')
    # Whitespace insensitive contiguous source reuse; detects CSS and common
    # transpilation-preserved literals/identifiers. Semantic rewrites still need
    # private human review with traces: never claim this proves independence.
    clean=lambda s:re.sub(r'\s+','',s)
    outputs=[clean(e.get_text()) for e in soup.find_all(['style','script'])]
    for original in script_and_styles(source):
        original=clean(original)
        for new in outputs:
            if new and SequenceMatcher(None,new,original,autojunk=True).find_longest_match().size>=160:
                raise ValueError('copied script/style segment')
    return {'automated_scan':'passed','independence':None,'human_trace_review_required':True}


def trace_gate(events, lane, workspace=None, forbidden_roots=()):
    """Conservative rejection; human access/independence review is still mandatory.

    No claim of read isolation: shell indirection/obfuscation can evade this scan.
    Scan invocations (not returned source text, which may mention frameworks).
    """
    import json
    for event in events:
        item = event.get('item', {})
        kind = item.get('type', '')
        if kind in {'web_search', 'collab_tool_call', 'image_generation'}:
            raise ValueError('prohibited generation tool')
        if lane == 'A' and kind == 'mcp_tool_call':
            raise ValueError('MCP used by A')
        invocation = {k:v for k,v in item.items() if k in {
            'command','arguments','tool','server','changes','path'}}
        invocation.update({k:v for k,v in event.items() if k in {'command','arguments','path'}})
        text = json.dumps(invocation, ensure_ascii=False)
        if re.search(r'(?i)\brm\s+[^;\n]*-[a-z]*[rf]|\b(?:rmdir|unlink)\b|shutil\.rmtree', text):
            raise ValueError('destructive cleanup during session')
        if workspace:
            from .lifecycle import physical
            real = str(physical(workspace))
            for raw in re.findall(re.escape(real) + r"[^\s\"\\;|&<>]*", text):
                if raw == real or raw.startswith(real+'/'):
                    if not Path(raw).resolve().is_relative_to(Path(real)):
                        raise ValueError('symlink/outside workspace access')
            # Require a path boundary: sibling names sharing a prefix stay forbidden.
            text = re.sub(re.escape(real) + r'(?=/|[\"\s]|$)', '.', text)
        if re.search(r'(?i)(auth\.json|\.env\b|oracle|\.\./|dangerously-bypass|require_escalated|\$HOME|~[/]|/proc/|/etc/|/home/)', text):
            raise ValueError('forbidden access or escalation in trace')
        if any(str(root) in text for root in forbidden_roots):
            raise ValueError('private/parent/sibling access')
        # Absolute paths must be confined to the session; generic system executables
        # are reviewable but never authorize reads of system/private material.
        for path in re.findall(r'(?<![\w:./])/(?:[\w. -]+/)*[\w.~-]+', text):
            if workspace and not Path(path).resolve().is_relative_to(Path(workspace).resolve()):
                if not path.startswith(('/usr/bin/', '/bin/')):
                    raise ValueError('absolute access outside session')
        if re.search(r'(?i)(playwright|puppeteer|selenium|chrom(?:e|ium)|firefox|browser|devtools|https?://|socket|listen\s*\(|createServer|http\.server|http-server|\b(?:vite|webpack|esbuild|babel|tsc|rollup|parcel|next|react|vue|svelte)\b|\bnpx\b|\b(?:pip|npm|pnpm|yarn)\s+(?:install|add|exec|run)|\b(?:curl|wget|nc|socat)\b)', text):
            raise ValueError('browser/listener/framework/transpilation/network invocation')
    return {'automated_trace_review':'passed','manual_access_review_required':True,
            'manual_independence_review_required':True, 'read_isolation':False}
