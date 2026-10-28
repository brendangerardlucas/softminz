"""Offline regression tests for the exact AA v5 Softminz contract."""
import json
import math
from pathlib import Path
import statistics
import tempfile
import unittest
from unittest.mock import patch

import public_watch as w

WEIGHTS = {
    'aa-briefcase': {'weight': .15, 'tasks': 91},
    'automationbench-aa': {'weight': .05, 'tasks': 657},
    'gdp-pdf': {'weight': .05, 'tasks': 100},
    'frontiercode-2-0': {'weight': .15, 'tasks': 132},
    'terminalbench-4-0': {'weight': .10, 'tasks': 66},
    'terminal-bench-science': {'weight': .15, 'tasks': 70},
    'critpt-v2-hard': {'weight': .10, 'tasks': 40},
    'omniscience': {'weight': .15, 'tasks': 3000},
    'hle-diamond': {'weight': .10, 'tasks': 1000},
}
LEGACY = {
    'terminalBench40': .54, 'frontierCode20': .42, 'omniscience': 29.5,
    'hleDiamond': .47, 'critptAgenticHard': .645,
    'terminalBenchScience': .576, 'analystAgent': .42,
}
NESTED = {
    'terminalbench-4-0': .54, 'frontiercode-2-0': .42,
    'hle-diamond': .47, 'critpt-v2-hard': .645,
    'terminal-bench-science': .576, 'aa-analyst-agent': .42,
}


def flight_page(record):
    return 'self.__next_f.push([1,' + json.dumps(json.dumps(record, separators=(',', ':'))) + '])'


def methodology_html(weights=WEIGHTS):
    rows = ''.join('<tr><td>' + label + '</td><td>' + str(weights[slug]['tasks'])
                   + '</td><td>3</td><td>' + str(weights[slug]['weight'] * 100) + '%</td></tr>'
                   for label, slug in w.II_TABLE_NAMES.items() if slug in weights)
    return '<h2>Artificial Analysis Intelligence Index v5.0</h2><table>' + rows + '</table>'


def complete_models(count=6):
    return {f'm{i}': dict(name=f'Model {i}', cost_task=i + 1,
                         **{b: float(i) + j / 10 for j, b in enumerate(w.BATTERY)})
            for i in range(count)}


class ScoreCompatibilityTests(unittest.TestCase):
    def test_exact_six_versioned_dimensions(self):
        self.assertEqual(w.BATTERY, ['terminalbench_v40', 'frontiercode_v20', 'omniscience_v11',
                                    'hle_diamond', 'critpt_v2_hard', 'terminalbench_science'])
        self.assertNotIn('non_hallucination_rate', w.BATTERY)
        self.assertNotIn('scicode', w.BATTERY)
        self.assertNotIn('lcr', w.BATTERY)

    def test_nested_and_flat_values_agree(self):
        for key, expected in LEGACY.items():
            with self.subTest(key=key):
                nested = dict(scores=NESTED, omniscience=29.5)
                self.assertEqual(w._score_value(nested, key), expected)
                self.assertEqual(w._score_value(LEGACY, key), expected)

    def test_no_old_benchmark_substitution(self):
        old = dict(frontierCode=.99, hle=.99, critpt=.99,
                   critptAgentic=.99, omniscienceV1={'index': 99},
                   scores={'frontiercode': .99, 'humanitys-last-exam': .99, 'critpt': .99})
        for field in ['frontierCode20', 'hleDiamond', 'critptAgenticHard', 'omniscience']:
            self.assertIsNone(w._score_value(old, field), field)

    def test_numeric_missing_zero_and_finite(self):
        for bad in (None, '0.3', True, False, math.nan, math.inf, -math.inf):
            self.assertIsNone(w._score_value({'scores': {'hle-diamond': bad}}, 'hleDiamond'))
        self.assertEqual(w._score_value({'scores': {'hle-diamond': 0}}, 'hleDiamond'), 0)
        self.assertEqual(w._score_value({'hleDiamond': 0, 'scores': {'hle-diamond': 1}}, 'hleDiamond'), 0)
        self.assertEqual(w._score_value({'omniscience': -20}, 'omniscience'), -20)

    def test_scrape_nested_primary_with_flat_evaluation_pages(self):
        common = dict(slug='test-model', name='Test', shortName='Test', deprecated=False,
                      isReasoning=True, isOpenWeights=False, contextWindowTokens=1000000,
                      intelligenceIndex=51., omniscience=29.5)
        primary, evaluation = dict(common, scores=NESTED), dict(common, **{k: v for k, v in LEGACY.items() if k != 'omniscience'})
        def fetch(url, *args):
            return flight_page(primary if url == w.MODELS_PAGE else evaluation)
        with patch.object(w, 'fetch', side_effect=fetch), \
             patch.object(w, '_fetch_cost_breakdown', return_value=({}, 'test')), \
             patch.object(w.time, 'sleep'):
            models, report = w.scrape(ii_weights=WEIGHTS)
        for key in w.BATTERY:
            self.assertIsNotNone(models['test-model'].get(key), key)
        self.assertEqual(models['test-model']['analystAgent'], .42)
        self.assertEqual(sum('validated (' in str(v) for v in report.values()), 7)


class MethodologyAndCostTests(unittest.TestCase):
    def test_v5_table_weights_and_counts(self):
        self.assertEqual(w.parse_ii_methodology_weights(methodology_html()), WEIGHTS)
        modified = methodology_html().replace('<td>40</td>', '<td>40 (hard subset of 70)</td>')
        self.assertEqual(w.parse_ii_methodology_weights(modified)['critpt-v2-hard']['tasks'], 40)

    def test_missing_weights_or_tasks_abort(self):
        cases = [methodology_html({k:v for k,v in WEIGHTS.items() if k != 'frontiercode-2-0'}),
                 methodology_html().replace('<td>132</td>', '<td>0</td>'),
                 methodology_html().replace('<td>15.0%</td>', '<td>0.0%</td>', 1),
                 methodology_html().replace('v5.0', 'v4.3.2')]
        for raw in cases:
            with self.subTest(raw=raw[:100]), tempfile.TemporaryDirectory() as tmp, \
                 patch.object(w, 'DATA', Path(tmp)), patch.object(w, 'fetch', return_value=raw):
                with self.assertRaises(SystemExit):
                    w.load_ii_benchmarks(tmp)

    def test_only_four_expensive_workloads(self):
        self.assertEqual(w.II_COST_SLUGS, {'aa-briefcase', 'terminalbench-4-0',
                                        'frontiercode-2-0', 'terminal-bench-science'})

    def test_deweight_and_task_count_average_not_index_weight_average(self):
        per_task = {'aa-briefcase': 2., 'terminalbench-4-0': 4.,
                    'frontiercode-2-0': 8., 'terminal-bench-science': 16.}
        split = {k: WEIGHTS[k]['weight'] * per_task.get(k, .001) for k in WEIGHTS}
        expected = sum(per_task[k] * WEIGHTS[k]['tasks'] for k in per_task) / 359
        self.assertAlmostEqual(w.cost_per_task(split, WEIGHTS), expected)
        for excluded in set(WEIGHTS) - w.II_COST_SLUGS:
            changed = dict(split, **{excluded: 999999.})
            self.assertAlmostEqual(w.cost_per_task(changed, WEIGHTS), expected)

    def test_zero_component_is_distinct_from_missing_component(self):
        split = dict.fromkeys(WEIGHTS, .1)
        split['aa-briefcase'] = 0.
        expected = sum(split[b] / WEIGHTS[b]['weight'] * WEIGHTS[b]['tasks']
                       for b in w.II_COST_SLUGS) / 359
        self.assertAlmostEqual(w.cost_per_task(split, WEIGHTS), expected)

    def test_partial_bad_or_zero_cost_is_not_invented(self):
        split = {k: .1 for k in WEIGHTS}
        for missing in w.II_COST_SLUGS:
            self.assertIsNone(w.cost_per_task({k:v for k,v in split.items() if k != missing}, WEIGHTS))
        self.assertIsNone(w.cost_per_task(dict.fromkeys(WEIGHTS, 0.), WEIGHTS))
        self.assertIsNone(w.cost_per_task(dict(split, **{'aa-briefcase': -1.}), WEIGHTS))
        self.assertIsNone(w.cost_per_task(dict(split, **{'aa-briefcase': math.nan}), WEIGHTS))


class CostSplitIntegrityTests(unittest.TestCase):
    def record(self):
        values = {k: .01 * (i + 1) for i, k in enumerate(WEIGHTS)}
        return {'intelligenceIndexCostPerTask': {
            'cost': {'total': sum(values.values())},
            'evaluations': [{'slug': k, 'weightedCostPerTask': v} for k,v in values.items()]}}

    def test_complete_split_includes_excluded_components(self):
        r = self.record()
        result = w.extract_cost_split(r)
        self.assertEqual(set(result), set(WEIGHTS))
        self.assertAlmostEqual(sum(result.values()), r['intelligenceIndexCostPerTask']['cost']['total'])

    def test_missing_cheap_component_is_not_complete(self):
        r = self.record()
        r['intelligenceIndexCostPerTask']['evaluations'] = [
            e for e in r['intelligenceIndexCostPerTask']['evaluations'] if e['slug'] != 'omniscience']
        self.assertIsNone(w.extract_cost_split(r))

    def test_duplicate_and_mismatched_totals_abort(self):
        for bad in ['duplicate', 'total']:
            r = self.record(); cost = r['intelligenceIndexCostPerTask']
            if bad == 'duplicate': cost['evaluations'].append(dict(cost['evaluations'][0]))
            else: cost['cost']['total'] += .01
            with self.assertRaises(ValueError): w.extract_cost_split(r)

    def test_nonfinite_negative_or_bool_cost_is_unavailable(self):
        for bad in [math.nan, -1., True]:
            r = self.record()
            r['intelligenceIndexCostPerTask']['evaluations'][0]['weightedCostPerTask'] = bad
            self.assertIsNone(w.extract_cost_split(r))


class CostSourceCoverageTests(unittest.TestCase):
    def cost_record(self, slug, factor=1.):
        values = {k: factor * .01 * (i + 1) for i,k in enumerate(WEIGHTS)}
        record = dict(slug=slug, shortName=slug, name=slug, deprecated=False,
                      isReasoning=True, isOpenWeights=False, contextWindowTokens=100,
                      priceClass='high', modelCreatorName='Test', intelligenceIndex=1.)
        record['intelligenceIndexCostPerTask'] = {'cost': {'total': sum(values.values())},
            'evaluations': [{'slug':k,'weightedCostPerTask':v} for k,v in values.items()]}
        return record

    def primary(self, records):
        return {r['slug']: dict(r, intelligenceIndexCostPerTask=r['intelligenceIndexCostPerTask']['cost']['total'])
                for r in records}

    def test_merge_partial_carriers_by_exact_slug(self):
        a,b,c = self.cost_record('a'),self.cost_record('b',2),self.cost_record('c',3)
        def fetch(url,*args): return flight_page([a,c] if url.endswith('/a') else [b])
        with patch.object(w,'fetch',side_effect=fetch), patch.object(w.time,'sleep'):
            costs,source=w._fetch_cost_breakdown(self.primary([a,b,c]),0)
        self.assertEqual(set(costs),{'a','b','c'})
        self.assertNotEqual(costs['a'],costs['b'])
        self.assertIn('a',source); self.assertIn('b',source)

    def test_missing_published_variant_split_aborts(self):
        a,b=self.cost_record('a'),self.cost_record('b')
        with patch.object(w,'fetch',return_value=flight_page([a])), patch.object(w.time,'sleep'):
            with self.assertRaises(SystemExit): w._fetch_cost_breakdown(self.primary([a,b]),0)

    def test_leaderboard_aggregate_contradiction_aborts(self):
        a=self.cost_record('a'); primary=self.primary([a])
        primary['a']['intelligenceIndexCostPerTask'] += .01
        with patch.object(w,'fetch',return_value=flight_page([a])):
            with self.assertRaises(SystemExit): w._fetch_cost_breakdown(primary,0)

    def test_cached_partial_carrier_is_refetched(self):
        a,b=self.cost_record('a'),self.cost_record('b',2)
        with patch.object(w,'fetch',side_effect=[flight_page([a]),flight_page([a,b])]) as fetch:
            costs,source=w._fetch_cost_breakdown(self.primary([a,b]),12)
        self.assertEqual(set(costs),{'a','b'})
        self.assertEqual(fetch.call_args_list[1].args[2],0)


class CohortTests(unittest.TestCase):
    def test_complete_cohort_sample_sd_and_softmin_bounds(self):
        models = complete_models()
        models['partial'] = {b: 1e9 for b in w.BATTERY[:-1]}
        ranked, rows, stats = w.zscore_battery(models)
        self.assertEqual(len(ranked), 6)
        self.assertIsNone(next(r for r in rows if r['slug'] == 'partial')['softminz'])
        for j, b in enumerate(w.BATTERY):
            self.assertAlmostEqual(stats[b][0], 2.5 + j / 10)
            self.assertAlmostEqual(stats[b][1], statistics.stdev(range(6)))
        for r in ranked:
            zs = list(r['zscores'].values())
            self.assertEqual(len(zs), 6)
            self.assertLessEqual(min(zs) - .0051, r['softminz'])
            self.assertLessEqual(r['softminz'], statistics.mean(zs) + .0051)

    def test_small_and_constant_cohorts_do_not_partially_score(self):
        for models in [complete_models(4), {f'm{i}': dict.fromkeys(w.BATTERY, 1.) for i in range(6)}]:
            ranked, rows, stats = w.zscore_battery(models)
            self.assertEqual(ranked, [])
            self.assertTrue(all(r['softminz'] is None for r in rows))


class PublicationGateTests(unittest.TestCase):
    def check_aborts_before_artifacts(self, report, models):
        with tempfile.TemporaryDirectory() as tmp:
            data, docs = Path(tmp)/'data', Path(tmp)/'docs'
            data.mkdir(); docs.mkdir()
            page, chart = docs/'index.html', docs/'softminz_pareto.png'
            page.write_bytes(b'previous page'); chart.write_bytes(b'previous chart')
            with patch.object(w, 'DATA', data), patch.object(w, 'DOCS', docs), \
                 patch.object(w, 'load_ii_benchmarks', return_value=(WEIGHTS, 'test')), \
                 patch.object(w, 'scrape', return_value=(models, report)), \
                 patch.object(w, 'make_chart', side_effect=AssertionError('must not touch artifacts')):
                with self.assertRaises(SystemExit): w.main()
            self.assertEqual(page.read_bytes(), b'previous page')
            self.assertEqual(chart.read_bytes(), b'previous chart')

    def test_failed_required_source_checks_abort(self):
        for status in ('REJECTED', 'FAILED', 'UNAVAILABLE'):
            with self.subTest(status=status):
                self.check_aborts_before_artifacts({'evaluation': status}, complete_models())

    def test_actual_empty_small_and_constant_cohorts_abort(self):
        for models in [{}, complete_models(4), {f'm{i}': dict.fromkeys(w.BATTERY, 1.) for i in range(6)}]:
            self.check_aborts_before_artifacts({}, models)

    def test_current_documentation_is_rendered(self):
        models = complete_models(); ranked, rows, stats = w.zscore_battery(models)
        page = w.build_html(ranked, w.pareto(ranked,'cost_task','softminz'), stats,
                            {}, models, 'dGVzdA==', WEIGHTS, 'test live')
        for label in w.BENCH_LABEL.values(): self.assertIn(label, page)
        for obsolete in ('seven-benchmark battery', 'Why these seven', 'v4.3.2',
                         'Why the GPT-5.6', 'mandatory non-hallucination'):
            self.assertNotIn(obsolete, page)
        self.assertIn('359', page)
        self.assertEqual(page.count('<td>Model '), 12)


if __name__ == '__main__':
    unittest.main()
