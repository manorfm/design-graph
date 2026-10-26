import argparse
import os
from pathlib import Path
from .common import environment, root_path


def main():
    p=argparse.ArgumentParser(description='Auditable three-page instrument; preparation never starts agents')
    p.add_argument('phase',choices=['prepare','run','evaluate','report'])
    p.add_argument('--scratch',required=True)
    p.add_argument('--source',type=Path)
    p.add_argument('--browser',type=Path)
    p.add_argument('--approval',type=Path)
    p.add_argument('--functional-plan',type=Path)
    args=p.parse_args();root=root_path(args.scratch);os.umask(0o077);os.environ.update(environment(root))
    if args.phase=='prepare':
        if not args.source or not args.browser or not args.functional_plan:
            p.error('prepare requires --source, --browser and evaluator-only --functional-plan')
        from .prepare import prepare
        print(prepare(root,args.source,args.browser,args.functional_plan))
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
