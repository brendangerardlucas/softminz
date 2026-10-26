"""Offline regression tests for AA payload compatibility and publication gates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import public_watch as w

LEGACY = {
    'hle': 0.51, 'scicode': 0.55, 'critpt': 0.31,
    'terminalBench40': 0.54, 'lcr': 0.79,
    'omniscienceNonHallucination': 0.49, 'analystAgent': 0.42,
}
NESTED = {
    'humanitys-last-exam': 0.51, 'scicode': 0.55, 'critpt': 0.31,
    'terminalbench-4-0': 0.54,
    'artificial-analysis-long-context-reasoning': 0.79,
    'omniscience-non-hallucination': 0.49, 'aa-analyst-agent': 0.42,
}


def flight_page(record):
    return 'self.__next_f.push([1,' + json.dumps(json.dumps(record, separators=(',', ':'))) + '])'


class ScoreCompatibilityTests(unittest.TestCase):
    def test_nested_and_legacy_values_agree(self):
        for key, expected in LEGACY.items():
            with self.subTest(key=key):
                self.assertEqual(w._score_value({'scores': NESTED}, key), expected)
                self.assertEqual(w._score_value(LEGACY, key), expected)

    def test_missing_non_numeric_and_zero_values(self):
        self.assertIsNone(w._score_value({'scores': {'critpt': None}}, 'critpt'))
        self.assertIsNone(w._score_value({'scores': {'critpt': '0.3'}}, 'critpt'))
        self.assertIsNone(w._score_value({'scores': []}, 'critpt'))
        self.assertEqual(w._score_value({'scores': {'critpt': 0}}, 'critpt'), 0)
        self.assertEqual(w._score_value({'critpt': 0, 'scores': {'critpt': 1}}, 'critpt'), 0)

    def test_scrape_nested_primary_with_legacy_evaluation_pages(self):
        common = dict(slug='test-model', name='Test', shortName='Test',
                      deprecated=False, isReasoning=True, isOpenWeights=False,
                      contextWindowTokens=1000000, intelligenceIndex=51.0,
                      omniscience=40.0)
        primary = dict(common, scores=NESTED)
        evaluation = dict(common, **LEGACY)
        def fetch(url, *args):
            return flight_page(primary if url == w.MODELS_PAGE else evaluation)
        weights = {key: {'weight': 0.1, 'tasks': 1} for key in w.II_COST_SLUGS}
        with patch.object(w, 'fetch', side_effect=fetch), \
             patch.object(w, '_fetch_cost_breakdown', return_value=({}, 'test')), \
             patch.object(w.time, 'sleep'):
            models, report = w.scrape(ii_weights=weights)
        row = models['test-model']
        for key in w.BATTERY:
            self.assertIsNotNone(row.get(key), key)
        self.assertEqual(row['non_hallucination_rate'], 0.49)
        self.assertEqual(row['analystAgent'], 0.42)
        self.assertEqual(sum('validated (' in str(v) for v in report.values()), 7)


class PublicationGateTests(unittest.TestCase):
    def check_aborts_before_artifacts(self, report, ranked, stats):
        with tempfile.TemporaryDirectory() as tmp:
            data, docs = Path(tmp)/'data', Path(tmp)/'docs'
            data.mkdir(); docs.mkdir()
            page, chart = docs/'index.html', docs/'softminz_pareto.png'
            page.write_bytes(b'previous page'); chart.write_bytes(b'previous chart')
            with patch.object(w, 'DATA', data), patch.object(w, 'DOCS', docs), \
                 patch.object(w, 'load_ii_benchmarks', return_value=({}, 'test')), \
                 patch.object(w, 'scrape', return_value=({}, report)), \
                 patch.object(w, 'zscore_battery', return_value=(ranked, [], stats)), \
                 patch.object(w, 'make_chart', side_effect=AssertionError('must not touch artifacts')):
                with self.assertRaises(SystemExit):
                    w.main()
            self.assertEqual(page.read_bytes(), b'previous page')
            self.assertEqual(chart.read_bytes(), b'previous chart')

    def test_rejected_failed_or_unavailable_checks_abort(self):
        for status in ('REJECTED', 'FAILED', 'UNAVAILABLE'):
            with self.subTest(status=status):
                self.check_aborts_before_artifacts({'evaluation': status}, [{}], dict.fromkeys(w.BATTERY))

    def test_empty_cohort_aborts(self):
        self.check_aborts_before_artifacts({}, [], {})

    def test_incomplete_zscore_statistics_abort(self):
        self.check_aborts_before_artifacts({}, [{}], {})


if __name__ == '__main__':
    unittest.main()
