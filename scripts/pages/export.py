#!/usr/bin/env python3
"""Copy only site/ into a new isolated directory in this worktree; never publish."""
import argparse
from pathlib import Path
import shutil

from preview import PUBLIC_FILES

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / 'site'


def export(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT) or destination == ROOT or destination.is_relative_to(SITE):
        raise ValueError('Choose a new destination inside this worktree, outside site/.')
    if destination.exists():
        raise FileExistsError(f'Destination already exists: {destination}')
    if SITE.is_symlink() or any(p.is_symlink() for p in SITE.rglob('*')):
        raise ValueError('Site must contain regular files, not symlinks.')
    files = {p.relative_to(SITE).as_posix() for p in SITE.rglob('*') if p.is_file()}
    if files != PUBLIC_FILES:
        raise ValueError('Site contents differ from the explicit public file allowlist.')
    shutil.copytree(SITE, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(export(args.destination))


if __name__ == '__main__':
    main()
