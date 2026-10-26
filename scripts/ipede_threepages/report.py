"""Allowlisted aggregate export; never copies client HTML, text, traces or paths."""
import json
from .common import CONTRACT, ROUND, fresh, write_json


def report(root):
    runs=json.loads((root/'run-results.private.json').read_text())
    evaluations=json.loads((root/'evaluation-results.private.json').read_text())
    out=fresh(root/'report')
    safe={lane:{key:data.get(key) for key in ['seconds','total_seconds','cold_index_seconds','tool_calls',
          'raw_mcp_item_events','time_limit_seconds','tool_limit','exit_code','stop_reason','raw_usage','output_artifact_observations',
          'observer_resolution_seconds','accepted_timing','accepted_timing_reason']} for lane,data in runs.items()}
    # Explicit field allowlist prevents evaluator copy/paths leaking through new fields.
    fields=['lane','page','viewport','functional_passed','browser_errors','diagnostic_rgb_mae_fraction',
            'visual_review','accepted','accepted_seconds','artifact_timing_distinct']
    data=dict(contract=CONTRACT,round=ROUND,samples_per_condition=1,order=['A','B'],runs=safe,
              evaluation=[{k:item.get(k) for k in fields} for item in evaluations],
              isolation='procedural, unrestricted shell; access audit required',
              limitations=['n=1 each; no universal gain claim','raw session usage only; no per-page token allocation',
                'OAuth billing not exposed; no token-to-money conversion','DOM/layout and pixel metrics diagnostic only',
                'visual/functional/manual access audit required before acceptance','all failures retained; no implicit reruns'])
    write_json(out/'data.json',data)
    (out/'report.md').write_text('# Three-page experiment\n\nContract: '+CONTRACT+'; round: '+ROUND+'.\n\n'
        'n=1 per condition, serial A then B. See data.json for raw session usage, elapsed seconds, tool counts, '
        'cold B indexing and artifact observations. Acceptance remains pending until human visual and access review. '
        'No money estimates or per-page token splits. DOM/layout and pixel metrics are diagnostic. '
        'Private evidence is retained outside this sanitized report; packaging is a later phase.\n')
    return out
