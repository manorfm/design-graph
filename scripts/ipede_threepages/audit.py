"""Conservative trace triage; shell strings cannot prove filesystem isolation."""
import json
import re
from .common import write_json


def audit(root):
    findings=[]
    for lane in ['A','B']:
        path=root/'runs'/lane/'evidence'/'observed-events.jsonl'
        count=0;commands=[]
        if path.exists():
            for line in path.read_text().splitlines():
                event=json.loads(line)['event'];item=event.get('item',{})
                if item.get('type')=='mcp_tool_call': count+=event.get('type')=='item.completed'
                command=item.get('command')
                if command:
                    commands.append(command)
                    suspicious=re.findall(r'(?:https?://\S+|/[^\s\'";]+|\.\./\S*)',str(command))
                    if suspicious:findings.append(dict(lane=lane,item_id=item.get('id'),access_candidates=suspicious))
        write_json(root/'runs'/lane/'evidence'/'access-audit.private.json',dict(
            mcp_completed_items=count,commands=commands,review='required',
            limitations='shell expansion, obfuscation and subprocess accesses need manual review; no enforced isolation'))
    write_json(root/'access-audit.private.json',dict(findings=findings,review='required'))
    return findings
