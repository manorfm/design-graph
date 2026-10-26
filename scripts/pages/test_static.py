#!/usr/bin/env python3
"""Dependency-free landing contract, HTTP-prefix and isolated-export tests."""
from html.parser import HTMLParser
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from preview import ROOT, SITE, PREFIX, server
from importlib.util import spec_from_file_location, module_from_spec


def load_export():
    spec = spec_from_file_location('pages_export', ROOT / 'scripts/pages/export.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.export


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.blocks = []
        self.in_code = False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'code' and attrs.get('id', '').startswith('code-'):
            self.in_code = True
            self.blocks.append('')

    def handle_endtag(self, tag):
        if tag == 'code':
            self.in_code = False

    def handle_data(self, data):
        self.text.append(data)
        if self.in_code:
            self.blocks[-1] += data


class LandingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (SITE / 'index.html').read_text()
        cls.doc = Document(cls.source)
        cls.spec = (ROOT / 'docs/pages/design-spec.md').read_text()

    def test_exact_six_copy_blocks(self):
        expected = re.findall(r'```(?:bash|json)\n(.*?)\n```', self.spec, re.S)
        self.assertEqual(len(expected), 6)
        self.assertEqual(self.doc.blocks, expected)
        self.assertEqual(sum('data-copy' in a for _, a in self.doc.tags), 6)
        pipx = re.search(r'<details class="pipx">(.*?)</details>', self.source, re.S)
        self.assertIsNotNone(pipx)
        self.assertIn('id="code-1"', pipx.group(1))

    def test_public_copy_and_examples(self):
        # Every backtick-delimited public literal in section 4, apart from
        # fragment/attribute instructions and explicitly optional prompt copy.
        public = self.spec.split('## 4.')[1].split('## 5.')[0]
        public = re.sub(r'```.*?```', '', public, flags=re.S)
        skip = {'design-graph', 'id="main"', 'Copy prompt', 'lang="en"'}
        text = ' '.join(' '.join(self.doc.text).split())
        for literal in re.findall(r'`([^`\n]+)`', public):
            if literal.startswith('#') or literal in skip:
                continue
            with self.subTest(literal=literal):
                # Title and description are metadata, not body text.
                metadata = ' '.join(a.get('content', '') for _, a in self.doc.tags)
                self.assertIn(literal, text + ' ' + metadata)
        self.assertEqual(sum(t == 'article' and a.get('class') == 'example' for t, a in self.doc.tags), 4)

    def test_structure_links_and_assets(self):
        ids = [a['id'] for _, a in self.doc.tags if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([a['id'] for t, a in self.doc.tags if t == 'section'],
                         ['top', 'overview', 'setup', 'examples', 'features', 'benchmarks', 'faq', 'start'])
        self.assertEqual(sum(t == 'h1' for t, _ in self.doc.tags), 1)
        self.assertEqual(sum(t == 'h2' for t, _ in self.doc.tags), 7)
        registry = set(re.findall(r'`(https://[^`]+)`', self.spec.split('## 6.')[1].split('## 7.')[0]))
        for tag, attrs in self.doc.tags:
            for attr in ('href', 'src'):
                if attr not in attrs:
                    continue
                value = attrs[attr]
                if value.startswith('#'):
                    self.assertIn(value[1:], ids)
                elif value.startswith('https://'):
                    self.assertIn(value, registry)
                    self.assertNotIn('target', attrs)
                    self.assertEqual(tag, 'a' if attrs.get('rel') != 'canonical' else 'link')
                else:
                    self.assertTrue(value.startswith('assets/') or value in ('benchmark-ipede-v2/report.md', 'benchmark-ipede-v2/data.json'), value)
                    self.assertTrue((SITE / value).is_file())
        self.assertTrue((SITE / '.nojekyll').is_file())
        self.assertEqual((SITE / '.nojekyll').stat().st_size, 0)
        css = (SITE / 'assets/style.css').read_text()
        self.assertNotRegex(css, r'@import|https?://|url\(')
        for heading in ('supported-prototypes', 'install', 'configure-the-mcp-server', 'mcp-tools'):
            headings = re.findall(r'^## (.+)$', (ROOT / 'README.md').read_text(), re.M)
            self.assertIn(heading, [h.lower().replace(' ', '-') for h in headings])

    def test_prefix_http(self):
        with server(0) as httpd:
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{httpd.server_port}'
            try:
                for p in [SITE / 'index.html', *sorted((SITE / 'assets').iterdir())]:
                    url = base + PREFIX + p.relative_to(SITE).as_posix()
                    with urlopen(url) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read(), p.read_bytes())
                for path in ('/', '/README.md', '/design-graph/../README.md', '/design-graph/%2e%2e/README.md'):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(base + path)
                    self.assertEqual(error.exception.code, 404)
                    error.exception.close()
            finally:
                httpd.shutdown()
                thread.join()

    def test_isolated_export(self):
        export = load_export()
        # Keep all artifacts in the authorized worktree.
        (ROOT / '.venv').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / '.venv', prefix='pages-export-test-') as temporary:
            destination = Path(temporary) / 'output'
            export(destination)
            def files(path):
                return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob('*') if p.is_file()}
            self.assertEqual(files(destination), files(SITE))
            with self.assertRaises(FileExistsError):
                export(destination)
            with self.assertRaises(ValueError):
                export(SITE / 'nested')


if __name__ == '__main__':
    unittest.main(verbosity=2)
