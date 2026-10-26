"""Fail-closed native event/RPC matching, shared by live and final B audits."""
import base64
import json
import re
import unicodedata


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().lower())


def matched_calls(folder):
    streams = {'client': b'', 'server': b''}
    for line in (folder/'transcript.jsonl').read_text().splitlines():
        record = json.loads(line)
        streams[record['direction']] += base64.b64decode(record['bytes'], validate=True)
    # The final line may still be in flight. Only complete RPC messages count.
    requests = [json.loads(line) for line in streams['client'].split(b'\n')[:-1] if line.strip()]
    responses = [json.loads(line) for line in streams['server'].split(b'\n')[:-1] if line.strip()]
    events = [json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    native = [e['item'] for e in events if e.get('type') == 'item.completed'
              and e.get('item', {}).get('type') == 'mcp_tool_call'
              and e['item'].get('server') == 'design-graph' and e['item'].get('status') == 'completed'
              and e['item'].get('error') is None and isinstance(e['item'].get('result'), dict)
              and not e['item']['result'].get('isError', False)]
    catalogue = {tool['name'] for response in responses
                 if 'result' in response and isinstance(response['result'], dict)
                 for tool in response['result'].get('tools', [])}
    for request in requests:
        if request.get('method') != 'tools/call': continue
        params = request['params']
        if params['name'] not in catalogue: continue
        found = [r for r in responses if r.get('id') == request['id'] and 'result' in r and 'error' not in r]
        if len(found) != 1: continue
        result = found[0]['result']
        if result.get('isError') or not result.get('content'): continue
        if any(item.get('tool') == params['name'] and item.get('arguments') == params.get('arguments', {})
               and item['result'].get('content') == result['content'] for item in native):
            yield params, result


def covered_screens(folder, selections):
    covered = set()
    for params, result in matched_calls(folder):
        if params['name'] not in {'get_screen', 'assemble_page', 'get_component', 'get_full', 'get_tokens'}:
            continue
        args = params.get('arguments', {})
        target = args.get('screen') if params['name'] == 'get_tokens' else args.get('screen', args.get('name'))
        text = '\n'.join(c.get('text', '') for c in result['content'] if c.get('type') == 'text')
        # Reject diagnostics, empty specs and echoes. Require substantive source/design data.
        if re.search(r'(?im)^\s*(?:#{1,6}\s*)?(?:screen not found|tela .*não encontrad|componente .*não encontrad|no (?:screen|component)|unknown (?:screen|component)|unavailable|error\s*:)', text): continue
        if len(text) < 80 or not re.search(r'(?i)(component|section|seç|style|token|source|```|<\w+|function\s)', text): continue
        for index, selected in enumerate(selections, 1):
            aliases = {normalize(selected[k]) for k in ('key', 'label', 'component') if selected.get(k)}
            if normalize(target) in aliases and any(alias in normalize(text) for alias in aliases):
                covered.add(index)
    return covered
