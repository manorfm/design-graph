#!/usr/bin/env python3
"""Serve only site/ at the eventual Pages prefix, using the Python stdlib."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / 'site'
PREFIX = '/design-graph/'
PUBLIC_FILES = frozenset({
    'index.html', '.nojekyll', 'assets/main.js', 'assets/theme.js',
    'assets/style.css', 'assets/mark.svg',
    'benchmark-ipede-v2/report.md', 'benchmark-ipede-v2/data.json',
})


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path == PREFIX[:-1]:
            self.send_response(301)
            self.send_header('Location', PREFIX)
            self.end_headers()
            return None
        if not path.startswith(PREFIX) or any(p in ('.', '..') for p in path.split('/')):
            self.send_error(404)
            return None
        relative = path[len(PREFIX):] or 'index.html'
        unresolved = SITE / relative
        target = unresolved.resolve()
        if (relative not in PUBLIC_FILES or not target.is_relative_to(SITE)
                or not target.is_file() or SITE.is_symlink()
                or any(p.is_symlink() for p in [unresolved, *unresolved.parents])):
            self.send_error(404)
            return None
        self.path = '/' + relative
        return super().send_head()


def server(port=8000):
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    with server(args.port) as httpd:
        print(f'Preview: http://127.0.0.1:{httpd.server_port}{PREFIX}', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
