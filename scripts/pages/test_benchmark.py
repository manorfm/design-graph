#!/usr/bin/env python3
"""Pinned public handoff, static metric traceability and publication boundary."""
import hashlib
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

from preview import ROOT, SITE, PREFIX, PUBLIC_FILES, server
from test_static import Document, load_export

HASHES = {
    'report.md': '2c61f4b25a5eaaa1168984fd5aa9c49ca2c4a92036de8edd4ae47d8ecce3e08f',
    'data.json': 'b3bca3aa4107d50c518fc17cb6681a34a36832d24ff5994002da9b69ac701b27',
}


def check_metrics(tags, data):
    metrics = [a for _, a in tags if 'data-source' in a]
    assert len(metrics) == 32, len(metrics)
    for attrs in metrics:
        value = data
        for key in attrs['data-source'].split('/'):
            value = value[int(key)] if isinstance(value, list) else value[key]
        assert json.loads(attrs['data-value']) == value, attrs
    paths = {a['data-source'] for a in metrics}
    required = {'runs/B/mcp_completed', 'runs/B/mcp_useful_target_correct',
                'runs/A/seconds', 'runs/B/seconds', 'runs/B/setup_index_seconds',
                'runs/B/readiness_seconds', 'runs/B/accepted_seconds'}
    required |= {f'evaluation/{i}/diagnostic_rgb_mae_fraction'
                 for i,e in enumerate(data['evaluation']) if e['lane'] in ('A','B')}
    assert required <= paths, required - paths
    return metrics


class BenchmarkContract(unittest.TestCase):
    def setUp(self):
        self.source = (SITE / 'index.html').read_text()
        self.section = self.source.split('<section id="benchmarks"')[1].split('</section>')[0]
        self.doc = Document(self.section)
        self.data = json.loads((SITE / 'benchmark-ipede-v2/data.json').read_text())

    def test_published_landing_preserved(self):
        # Pinned to local 63042a7; all existing copy/CTAs remain byte-identical.
        normalized = re.sub(r'<section id="benchmarks".*?</section>\n', '', self.source, flags=re.S)
        normalized = normalized.replace('<a href="#benchmarks">Benchmarks</a>', '')
        self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(),
                         'fac2cf9c5ef26ae0a6130e9c37bc2d870d59a66af978e021a3310a0e00b5f650')
        css = (SITE/'assets/style.css').read_bytes()
        self.assertEqual(hashlib.sha256(css[:10380]).hexdigest(),
                         '462d65b645b9cae81b0c59afbd9399efe6d81f6d84315b4f1ca5b9d8a415102d')
        for name,digest in {
            'main.js': 'ec0a2fb9ab8086936ca8051d194e1fb189cc191c3d46e2bbeb4e9031a75eb8a3',
            'theme.js': 'a370bf6072511269af6b96d30586b2e8a046a4f0b4bc0acd970b56fa29068841',
            'mark.svg': '412f4e2d4e843e3a56eb91a6d88de942afd3985772cf6f8231693714170fa26e',
        }.items():
            self.assertEqual(hashlib.sha256((SITE/'assets'/name).read_bytes()).hexdigest(),digest)

    def test_frozen_scope_and_unavailable_context(self):
        self.assertEqual(self.data['samples_per_condition'],1)
        self.assertFalse(self.data['causal_comparison_valid'])
        self.assertTrue(self.data['independent_qa_pending'])
        self.assertEqual(self.data['evaluator']['browser_contexts'],18)
        for lane in ('original','A','B'):
            entries=[e for e in self.data['evaluation'] if e['lane']==lane]
            self.assertEqual(len(entries),6)
            self.assertEqual(sum(e['steps_passed'] for e in entries),86)
            self.assertEqual(sum(e['steps_expected'] for e in entries),86)
            self.assertTrue(all(e['functional_passed'] and e['browser_errors']==0
                                and e['external_requests']==0 and e['capture_error'] is None
                                and e['accepted_seconds'] is None for e in entries))
        for context in (self.data['runs']['A']['telemetry']['context'], self.data['runs']['B']['context']):
            self.assertTrue(all(v is None for v in context.values()))
        self.assertEqual(self.data['runs']['B']['queried_pages'],[1,2,3])
        self.assertEqual(self.data['historical_B_v3']['mcp_completed'],0)
        self.assertIsNone(self.data['historical_B_v4']['usage'])

    def test_pinned_handoff_and_public_inventory(self):
        for name, digest in HASHES.items():
            self.assertEqual(hashlib.sha256((SITE / 'benchmark-ipede-v2' / name).read_bytes()).hexdigest(), digest)
        self.assertEqual({p.name for p in (SITE / 'benchmark-ipede-v2').iterdir()}, set(HASHES))
        self.assertEqual({p.relative_to(SITE).as_posix() for p in SITE.rglob('*') if p.is_file()}, PUBLIC_FILES)
        self.assertFalse(any(p.is_symlink() for p in SITE.rglob('*')))
        for p in SITE.rglob('*'):
            if p.suffix in ('.html', '.md', '.json', '.js', '.css'):
                self.assertNotRegex(p.read_text(), r'/home/|\.hermes/|PRIVATE/|sk-[A-Za-z0-9]{16,}|BEGIN .*PRIVATE KEY')

    def test_trace_values_and_rendered_precision(self):
        metrics = check_metrics(self.doc.tags, self.data)
        for attrs in metrics:
            value = json.loads(attrs['data-value'])
            shown = 'Unavailable' if value is None else format(value, attrs.get('data-format', ''))
            pattern = r'data-source="'+re.escape(attrs['data-source'])+r'"[^>]*>'+re.escape(shown)+r'</span>'
            self.assertRegex(self.section, pattern)
        mae = [a for a in metrics if a['data-source'].endswith('/diagnostic_rgb_mae_fraction')]
        self.assertEqual(len(mae), 12)
        self.assertTrue(all(a['data-format'] == '.9f' for a in mae))
        self.assertEqual(sum(json.loads(a['data-value']) == 0 for a in mae), 6)

    def test_labels_limits_and_no_unsupported_claims(self):
        text = ' '.join(' '.join(self.doc.text).split())
        for label in ('Causal effect NOT IDENTIFIED', 'n=1 per condition', 'Final independent QA pending',
                      'gpt-6.1-sol', 'medium reasoning', '900 seconds and 90 tools',
                      'Retrieval and context', 'Generation time and usage', 'Fidelity and interaction',
                      'not retrieval accuracy', 'compaction', 'overflow', 'not an effective context window',
                      '86/86 steps for each of original, A and B', 'Mobile usability FAIL',
                      '1280×900', '390×844', 'Grupos de Componentes', 'Restaurantes', 'Estoque',
                      'Premium retained', 'Empty gray KPI icon placeholders', 'not functional gains',
                      'not percentage accuracy, SSIM, similarity', 'incomplete query 5 ground truth',
                      'Free versus Premium', 'zero MCP calls', 'no final usage',
                      'not specified in public handoff', 'not an independent reconstruction',
                      'OS and model caches were uncontrolled', 'No captures are publicly available due to privacy',
                      'ebdbeb24323d7143e0186622a7389b963e5ed350', 'c68e1cbfd2c13ec5be68ae2a9314470a7c15652b'):
            # The source describes both methods together.
            if label == 'not an independent reconstruction': label = 'Neither is an independent reconstruction'
            self.assertIn(label, text)
        self.assertNotRegex(text, r'\d\s*%|\$\s*\d|\b(?:faster|cheaper|pixel-perfect|100%|0\.162\.1|1\.64\.1)\b')
        self.assertEqual(sum(t == 'table' for t,a in self.doc.tags), 3)
        self.assertEqual(sum(t == 'caption' for t,a in self.doc.tags), 3)
        self.assertTrue(all('scope' in a for t,a in self.doc.tags if t == 'th'))
        self.assertIn('href="#benchmarks">Benchmarks', self.source)
        self.assertLess(self.source.index('id="benchmarks"'), self.source.index('id="faq"'))

    def test_nested_http_downloads_and_security(self):
        with server(0) as httpd:
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{httpd.server_port}'
            try:
                for name,digest in HASHES.items():
                    with urlopen(base+PREFIX+'benchmark-ipede-v2/'+name) as response:
                        self.assertEqual(response.status,200)
                        self.assertEqual(hashlib.sha256(response.read()).hexdigest(),digest)
                for path in ('benchmark-ipede-v2/', 'assets/', '.git/config', 'README.md',
                             'benchmark-ipede-v2/%2e%2e/index.html', '%2e%2e/README.md',
                             'benchmark-ipede-v2/%252e%252e/README.md', 'benchmark-ipede-v2/private.png'):
                    with self.assertRaises(HTTPError) as error: urlopen(base+PREFIX+path)
                    self.assertEqual(error.exception.code,404)
                    error.exception.close()
                # Even an allowlisted file cannot be a symlink to public or private content.
                p=SITE/'benchmark-ipede-v2/data.json'; original=p.read_bytes()
                try:
                    p.unlink(); p.symlink_to(SITE/'index.html')
                    with self.assertRaises(HTTPError) as error: urlopen(base+PREFIX+'benchmark-ipede-v2/data.json')
                    self.assertEqual(error.exception.code,404); error.exception.close()
                    with self.assertRaises(ValueError): load_export()(ROOT/'.venv/forbidden-symlink-export')
                finally:
                    p.unlink(); p.write_bytes(original)
            finally:
                httpd.shutdown(); thread.join()

    def test_export_contains_exact_nested_handoff_and_rejects_extra(self):
        (ROOT/'.venv').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.venv',prefix='benchmark-export-') as temporary:
            output=load_export()(Path(temporary)/'public')
            for name,digest in HASHES.items():
                self.assertEqual(hashlib.sha256((output/'benchmark-ipede-v2'/name).read_bytes()).hexdigest(),digest)
            extra=SITE/'benchmark-ipede-v2/unapproved.txt'
            try:
                extra.write_text('synthetic privacy control')
                with self.assertRaises(ValueError): load_export()(Path(temporary)/'rejected')
            finally: extra.unlink()


if __name__ == '__main__':
    unittest.main(verbosity=2)
