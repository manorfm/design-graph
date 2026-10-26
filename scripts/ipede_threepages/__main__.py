import argparse
import os
from pathlib import Path
from .common import environment, root_path


def main():
    p=argparse.ArgumentParser(description='Auditable three-page instrument; preparation never starts agents')
    p.add_argument('phase',choices=['prepare','preflight','preflight-v5','run-b-v4','run-b-v5','run','evaluate','report'])
    p.add_argument('--scratch',required=True)
    p.add_argument('--baseline',type=Path,help='existing frozen v3 round root (read only)')
    p.add_argument('--source',type=Path)
    p.add_argument('--python',type=Path,help='existing Python environment for standalone preflight/B-only run')
    p.add_argument('--browser',type=Path)
    p.add_argument('--approval',type=Path)
    p.add_argument('--functional-plan',type=Path)
    args=p.parse_args();root=root_path(args.scratch)
    if args.phase in {'run-b-v4','run-b-v5'} and args.baseline:
        baseline=args.baseline.resolve()
        if root==baseline or baseline in root.parents or root in baseline.parents:
            p.error('B-only scratch must be separate from baseline')
    os.umask(0o077);os.environ.update(environment(root))
    if args.phase=='prepare':
        if not args.source or not args.browser or not args.functional_plan:
            p.error('prepare requires --source, --browser and evaluator-only --functional-plan')
        from .prepare import prepare
        print(prepare(root,args.source,args.browser,args.functional_plan))
    elif args.phase in {'preflight','preflight-v5'}:
        if not args.python:p.error('preflight requires --python pointing to existing environment')
        from .preflight import preflight
        if args.phase=='preflight-v5':
            print(preflight(root,args.python.absolute(),Path(__file__).resolve().parents[2],version='v5'))
        else:
            print(preflight(root,args.python.absolute(),Path(__file__).resolve().parents[2]))
    elif args.phase=='run-b-v4':
        if not args.baseline or not args.python:p.error('run-b-v4 requires --baseline and --python')
        from .b_v4 import run_b_v4
        print(run_b_v4(root,args.baseline.resolve(),args.python.absolute(),Path(__file__).resolve().parents[2]))
    elif args.phase=='run-b-v5':
        if not args.baseline or not args.python:p.error('run-b-v5 requires --baseline and --python')
        from .b_v5 import run_b_v5
        print(run_b_v5(root,args.baseline.resolve(),args.python.absolute(),Path(__file__).resolve().parents[2]))
    elif args.phase=='run':
        if not args.approval:p.error('run requires explicit parent freeze approval file')
        from .runner import run
        run(root,args.approval)
    elif args.phase=='evaluate':
        from .evaluate import evaluate
        evaluate(root)
    else:
        from .report import report
        print(report(root))

if __name__=='__main__': main()
