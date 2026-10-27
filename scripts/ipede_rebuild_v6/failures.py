"""Frozen single-attempt policy. Only enumerated local failures may continue."""
from .common import write_json
from .protocol import ORDER

LOCAL = {'delivery', 'timeout', 'tool_limit', 'validation', 'output_before_screen_queries'}
POLICY = {'attempts_per_position':1, 'local_continue':sorted(LOCAL),
          'unknown':'stop round', 'guard_refusal':'stop round; never retry',
          'acceptance':'separate human gate; artifact does not imply acceptance'}


class LocalFailure(ValueError):
    pass


def sequence(root, attempt):
    path = root/'positions.json'
    if path.exists():
        import json
        initial=root/'preparation/positions.initial.private.json'
        marker=root/'collection-attempt.private.json'
        if not initial.is_file() or marker.exists() or json.loads(path.read_text()) != json.loads(initial.read_text()):
            raise ValueError('positions already exist; no retry')
        with marker.open('x') as stream: stream.write('{}\n')
    rows = [dict(page=p,lane=l,status='planned',reason=None,artifact=None,accepted=None) for p,l in ORDER]
    write_json(path, rows)
    stopped = None
    for row in rows:
        if stopped:
            row.update(status='not_started', reason=stopped)
        else:
            row['status']='started'; write_json(path,rows)
            try:
                result = attempt(row['page'], row['lane'])
                reason = result.get('stop_reason')
                row.update(status='failed' if reason else 'completed', reason=reason,
                           artifact=result.get('artifact'))
                if reason and reason not in LOCAL: stopped=reason
            except Exception as exc:
                reason = 'validation' if isinstance(exc,LocalFailure) else 'systemic_unknown'
                output=root/f"sessions/{row['page']}-{row['lane']}/work/output/page.html"
                artifact=output.is_file()
                if (root/'preparation/runtime.private.json').exists():
                    from .lifecycle import workspace
                    try: artifact=(workspace(root,f"{row['page']}-{row['lane']}")/'output/page.html').is_file()
                    except (ValueError,OSError): artifact=None
                row.update(status='failed',reason=reason,artifact=artifact)
                # Diagnostics remain private; public matrix uses stable reason codes.
                write_json(root/f"failure-{row['page']}-{row['lane']}.json",dict(type=type(exc).__name__, diagnostic=str(exc)))
                if reason not in LOCAL: stopped=reason
        write_json(path, rows)
    return rows
