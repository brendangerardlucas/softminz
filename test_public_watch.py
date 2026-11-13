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
    'terminalBench40': .54, 'frontierCode20': .42, 'omniscienceAccuracy': .4763333333333333, 'omniscienceNonHallucination': .6549968173138129,
    'hleDiamond': .47, 'critptAgenticHard': .645,
    'terminalBenchScience': .576, 'analystAgent': .42,
}
NESTED = {
    'terminalbench-4-0': .54, 'frontiercode-2-0': .42,
    'omniscience-accuracy': .4763333333333333,
    'omniscience-non-hallucination': .6549968173138129,
    'hle-diamond': .47, 'critpt-v2-hard': .645,
    'terminal-bench-science': .576, 'aa-analyst-agent': .42,
    'aa-briefcase': 1500.25, 'automationbench-aa': .5937591715646424,
    'gdp-pdf': .21,
}
NEW_FLAT = {
    'briefcaseElo': 1500.25, 'automationBenchPartialScore': .5937591715646424,
    'gdpPdfAllPass': .21,
}


def flight_page(record):
    return 'self.__next_f.push([1,' + json.dumps(json.dumps(record, separators=(',', ':'))) + '])'


def methodology_html(weights=WEIGHTS):
    rows = ''.join('<tr><td>' + label + '</td><td>' + str(weights[slug]['tasks'])
                   + '</td><td>3</td><td>' + str(weights[slug]['weight'] * 100) + '%</td></tr>'
                   for label, slug in w.II_TABLE_NAMES.items() if slug in weights)
    return '<h2>Artificial Analysis Intelligence Index v5.0</h2><table>' + rows + '</table>'


def complete_models(count=6, battery=None):
    battery = w.BATTERY if battery is None else battery
    return {f'm{i}': dict(name=f'Model {i}', cost_task=i + 1,
                         **{b: float(i) + j / 10 for j, b in enumerate(battery)})
            for i in range(count)}


class ScoreCompatibilityTests(unittest.TestCase):
    def test_exact_seven_versioned_components(self):
        self.assertEqual(w.BATTERY, ['terminalbench_v40', 'frontiercode_v20', 'omniscience_v11_accuracy',
                                    'omniscience_v11_non_hallucination', 'hle_diamond',
                                    'critpt_v2_hard', 'terminalbench_science'])
        self.assertNotIn('omniscience_v11', w.BATTERY)
        self.assertNotIn('scicode', w.BATTERY)
        self.assertNotIn('lcr', w.BATTERY)

    def test_nested_and_flat_values_agree(self):
        for key, expected in LEGACY.items():
            with self.subTest(key=key):
                nested = dict(scores=NESTED, omniscience=99.)
                self.assertEqual(w._score_value(nested, key), expected)
                self.assertEqual(w._score_value(LEGACY, key), expected)

    def test_no_old_benchmark_substitution(self):
        old = dict(frontierCode=.99, hle=.99, critpt=.99,
                   critptAgentic=.99, omniscienceV1={'index': 99},
                   scores={'frontiercode': .99, 'humanitys-last-exam': .99, 'critpt': .99})
        for field in ['frontierCode20', 'hleDiamond', 'critptAgenticHard', 'omniscienceAccuracy', 'omniscienceNonHallucination']:
            self.assertIsNone(w._score_value(old, field), field)

    def test_current_v11_breakdown_components_not_legacy_total(self):
        record = {'omniscience': 99.,
                  'omniscienceBreakdown': {'accuracy': .6, 'hallucinationRate': .25},
                  'omniscienceV1': {'accuracy': .1, 'hallucinationRate': .9}}
        self.assertEqual(w._score_value(record, 'omniscienceAccuracy'), .6)
        self.assertEqual(w._score_value(record, 'omniscienceNonHallucination'), .75)
        for old in [{'omniscience': 99.}, {'omniscienceV1': record['omniscienceV1']},
                    {'omniscienceBreakdown': {'total': {'accuracy': .99, 'hallucinationRate': .01}}}]:
            self.assertIsNone(w._score_value(old, 'omniscienceAccuracy'))
            self.assertIsNone(w._score_value(old, 'omniscienceNonHallucination'))

    def test_component_probability_bounds_and_zero(self):
        for key,slug in [('omniscienceAccuracy','omniscience-accuracy'),
                         ('omniscienceNonHallucination','omniscience-non-hallucination')]:
            for bad in [-.1, 1.1, True, math.nan, math.inf]:
                self.assertIsNone(w._score_value({'scores':{slug:bad}},key))
            self.assertEqual(w._score_value({'scores':{slug:0.}},key),0.)
            self.assertEqual(w._score_value({'scores':{slug:1.}},key),1.)

    def test_numeric_missing_zero_and_finite(self):
        for bad in (None, '0.3', True, False, math.nan, math.inf, -math.inf):
            self.assertIsNone(w._score_value({'scores': {'hle-diamond': bad}}, 'hleDiamond'))
        self.assertEqual(w._score_value({'scores': {'hle-diamond': 0}}, 'hleDiamond'), 0)
        self.assertEqual(w._score_value({'hleDiamond': 0, 'scores': {'hle-diamond': 1}}, 'hleDiamond'), 0)
        self.assertEqual(w._score_value({'omniscience': -20}, 'omniscience'), -20)

    def test_scrape_nested_primary_with_flat_evaluation_pages(self):
        common = dict(slug='test-model', name='Test', shortName='Test', deprecated=False,
                      isReasoning=True, isOpenWeights=False, contextWindowTokens=1000000,
                      intelligenceIndex=51., omniscience=100*(.4763333333333333 - (1-.4763333333333333)*(1-.6549968173138129)))
        primary = dict(common, scores=NESTED)
        evaluation = dict(common, **{k:v for k,v in LEGACY.items()
                          if k not in ('omniscienceAccuracy','omniscienceNonHallucination')},
                          **NEW_FLAT)
        evaluation['omniscienceBreakdown'] = {'accuracy': .4763333333333333,
                                              'hallucinationRate': 1-.6549968173138129}
        evaluation['omniscienceV1'] = {'accuracy': .99, 'hallucinationRate': .99}
        def fetch(url, *args):
            return flight_page(primary if url == w.MODELS_PAGE else evaluation)
        with patch.object(w, 'fetch', side_effect=fetch), \
             patch.object(w, '_fetch_cost_breakdown', return_value=({}, 'test')), \
             patch.object(w.time, 'sleep'):
            models, report = w.scrape(ii_weights=WEIGHTS)
        for key in w.BATTERY:
            self.assertIsNotNone(models['test-model'].get(key), key)
        for key in w.BATTERY_ALL:
            self.assertIsNotNone(models['test-model'].get(key), key)
        self.assertEqual(models['test-model']['analystAgent'], .42)
        self.assertEqual(sum('validated (' in str(v) for v in report.values()), 13)


class MethodologyAndCostTests(unittest.TestCase):
    def test_v5_table_weights_and_counts(self):
        self.assertEqual(w.parse_ii_methodology_weights(methodology_html()), WEIGHTS)
        modified = methodology_html().replace('<td>40</td>', '<td>40 (hard subset of 70)</td>')
        self.assertEqual(w.parse_ii_methodology_weights(modified)['critpt-v2-hard']['tasks'], 40)

    def test_frontiercode_aa_label_alias(self):
        renamed = methodology_html().replace('FrontierCode 2.0', 'FrontierCode-AA 2.0')
        self.assertEqual(w.parse_ii_methodology_weights(renamed), WEIGHTS)

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
            self.assertEqual(len(zs), 7)
            self.assertLessEqual(min(zs) - .0051, r['softminz'])
            self.assertLessEqual(r['softminz'], statistics.mean(zs) + .0051)

    def test_both_omni_components_mandatory_and_combined_index_ignored(self):
        models = complete_models()
        baseline = w.zscore_battery(models)
        for field in ['omniscience_v11_accuracy','omniscience_v11_non_hallucination']:
            partial = {b: 999. for b in w.BATTERY if b != field}
            partial['omniscience_v11'] = 999.
            models['missing-'+field] = partial
        ranked, rows, stats = w.zscore_battery(models)
        self.assertEqual(stats,baseline[2])
        self.assertEqual(len(ranked),6)
        self.assertTrue(all(r['softminz'] is None for r in rows if r['slug'].startswith('missing-')))
        for model in models.values(): model['omniscience_v11'] = -999.
        self.assertEqual(w.zscore_battery(models)[0],ranked)

    def test_normalized_mean_of_seven_boltzmann_factors(self):
        ranked, rows, stats = w.zscore_battery(complete_models())
        for row in ranked:
            zs=[row['zscores'][b] for b in w.BATTERY]
            expected=-math.log(sum(math.exp(-z) for z in zs)/7)
            self.assertEqual(row['softminz'],round(expected,2))
            # Normalization is an additive ln(7), not a linear score average.
            raw=-math.log(sum(math.exp(-z) for z in zs))
            self.assertAlmostEqual(expected-raw,math.log(7))

    def test_heterogeneous_profiles_are_not_linear_or_aa_weighted(self):
        profiles = [list(range(8)), list(reversed(range(8))),
                    [1,4,2,6,0,7,3,5], [6,1,7,0,5,2,4,3],
                    [2,3,4,5,6,7,0,1], [4,0,5,1,6,2,7,3],
                    [3,4,5,6,7,0,1,2]]
        models = {f'm{i}': {b: profiles[j][i]/7 for j,b in enumerate(w.BATTERY)}
                  for i in range(8)}
        ranked, rows, stats = w.zscore_battery(models)
        for row in ranked:
            factors=[math.exp(-row['zscores'][b]) for b in w.BATTERY]
            expected=-math.log(sum(factors)/7)
            self.assertEqual(row['softminz'], round(expected,2))
        row=next(r for r in ranked if r['slug']=='m0')
        zs=[row['zscores'][b] for b in w.BATTERY]
        linear=statistics.mean(zs)
        factors=[math.exp(-z) for z in zs]
        accuracy_i=w.BATTERY.index('omniscience_v11_accuracy')
        aa_weighted=-math.log((sum(factors)+factors[accuracy_i])/8)
        self.assertGreater(abs(row['softminz']-linear),.05)
        self.assertGreater(abs(row['softminz']-aa_weighted),.02)

    def test_small_and_constant_cohorts_do_not_partially_score(self):
        for models in [complete_models(4), {f'm{i}': dict.fromkeys(w.BATTERY, 1.) for i in range(6)}]:
            ranked, rows, stats = w.zscore_battery(models)
            self.assertEqual(ranked, [])
            self.assertTrue(all(r['softminz'] is None for r in rows))


class HeadToHeadTests(unittest.TestCase):
    def rows(self):
        return w.zscore_battery(complete_models())[0]

    def test_exports_every_scored_model_and_full_precision_z(self):
        ranked=self.rows(); data=w.comparison_data(ranked)
        self.assertEqual(data['cohort_size'],len(ranked))
        self.assertEqual([c['key'] for c in data['components']],w.BATTERY)
        self.assertEqual({m['slug'] for m in data['models']},{r['slug'] for r in ranked})
        for model,row in zip(data['models'],ranked):
            self.assertEqual(model['z'],[row['zscores'][b] for b in w.BATTERY])
        self.assertNotEqual(data['default_a'],data['default_b'])

    def test_default_recent_pair_when_present(self):
        ranked=self.rows()
        ranked[0]['slug']='gpt-6-astra-high'; ranked[1]['slug']='claude-opus-5-5'
        data=w.comparison_data(ranked)
        self.assertEqual(data['default_a'],'gpt-6-astra-high')
        self.assertEqual(data['default_b'],'claude-opus-5-5')

    def test_missing_preferred_model_falls_back_to_two_distinct_models(self):
        ranked=self.rows(); ranked[0]['slug']='claude-opus-5-5'
        data=w.comparison_data(ranked)
        self.assertNotEqual(data['default_a'],data['default_b'])

    def test_server_rendered_fallback_controls_and_seven_rows(self):
        page=w.render_head_to_head(self.rows())
        self.assertIn('id="h2h-controls" disabled',page)
        self.assertIn('<noscript>',page)
        self.assertEqual(page.count('<tr data-component='),7)
        self.assertIn('Δz = Model A − Model B',page)
        self.assertIn('does not recalculate the normalization',page)
        self.assertIn('aria-live="polite"',page)

    def test_safe_json_round_trip_and_html_escaping(self):
        import re
        ranked=self.rows(); hostile='</script><img src=x onerror=alert(1)>&"'
        ranked[0]['name']=hostile
        page=w.render_head_to_head(ranked)
        payload=re.search(r'<script type="application/json" id="h2h-data">(.*?)</script>',page,re.S).group(1)
        self.assertNotIn('<',payload)
        self.assertEqual(json.loads(payload)['models'][0]['name'],hostile)
        self.assertNotIn('<img src=x onerror=',page)
        self.assertIn('&lt;/script&gt;',page)

    def test_unpriced_scored_models_are_not_filtered_out(self):
        ranked=self.rows(); ranked[0]['cost_task']=None
        data=w.comparison_data(ranked)
        self.assertEqual(len(data['models']),len(ranked))
        self.assertIsNone(data['models'][0]['cost_task'])

    def test_panels_sit_inside_their_benchmark_set_view(self):
        models=complete_models(battery=w.BATTERY_ALL)
        ranked,rows,stats=w.zscore_battery(models)
        ranked_all,_,stats_all=w.zscore_battery(models,w.BATTERY_ALL)
        page=w.build_html(ranked,[],stats,ranked_all,[],stats_all,{},models,'dGVzdA==',
                          'dGVzdA==',WEIGHTS,'test')
        self.assertLess(page.index('id="all9-cost-table"'),page.index('id="head-to-head-all"'))
        self.assertLess(page.index('id="head-to-head-all"'),page.index('id="view-sci"'))
        self.assertLess(page.index('id="view-sci"'),page.index('id="rank-cost-table"'))
        self.assertLess(page.index('id="rank-cost-table"'),page.index('id="head-to-head"'))
        self.assertLess(page.index('id="head-to-head"'),page.index('<h2>What SoftMinZ measures'))


class OmniscienceModeTests(unittest.TestCase):
    def test_net_consistency_rejects_contradictions_and_skips_incomplete(self):
        good = {'omniscience': 25.0, 'scores': {'omniscience-accuracy': .5,
                'omniscience-non-hallucination': .5}}
        bad = dict(good, omniscience=26.0)
        self.assertEqual(w.validate_omniscience_consistency({'good': good, 'partial': {'omniscience': 10}}), 1)
        with self.assertRaisesRegex(ValueError, 'bad'):
            w.validate_omniscience_consistency({'bad': bad})

    def test_four_view_html_has_independent_payloads_and_unique_ids(self):
        import re
        models = complete_models(battery=w.BATTERY_ALL)
        for i, model in enumerate(models.values()):
            model['omniscience_v11_combined'] = float(i*i)
        variants = {}
        for key, battery in [('all-combined', w.BATTERY_ALL_COMBINED), ('sci-combined', w.BATTERY_COMBINED)]:
            ranked, _, stats = w.zscore_battery(models, battery)
            variants[key] = (ranked, w.pareto(ranked, 'cost_task', 'softminz'), stats, 'dGVzdA==')
        sci, _, ss = w.zscore_battery(models, w.BATTERY)
        all_, _, sa = w.zscore_battery(models, w.BATTERY_ALL)
        page = w.build_html(sci, [], ss, all_, [], sa, {}, models, 'dGVzdA==', 'dGVzdA==', WEIGHTS, 'test', variants=variants)
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))
        for prefix, battery in [('h2h-all-combined', w.BATTERY_ALL_COMBINED), ('h2h-sci-combined', w.BATTERY_COMBINED)]:
            payload = json.loads(re.search(r'<script type="application/json" id="'+prefix+r'-data">(.*?)</script>', page, re.S).group(1))
            self.assertEqual([c['key'] for c in payload['components']], battery)
            self.assertEqual(len(payload['models']), 6)
        self.assertIn('data-mode="combined"', page)
        self.assertEqual(page.count('data:image/png;base64,dGVzdA=='), 4)

    def test_combined_jsonld_does_not_read_accuracy_as_net_score(self):
        raw = '<script type="application/ld+json">' + json.dumps({
            'name': 'AA-Omniscience v1.1 Accuracy: Score',
            'data': [{'detailsUrl': '/models/example', 'value': .5}]}) + '</script>'
        label = next(label for field, label in w.PAGES['omniscience'] if field == 'omniscience_v11_combined')
        self.assertEqual(w.jsonld_scores(raw, label), {})

    def test_combined_score_is_published_v11_net_and_range_checked(self):
        self.assertEqual(w._score_value({'omniscience': 42.5, 'omniscienceV1': 99}, 'omniscience'), 42.5)
        for bad in (-100.1, 100.1, float('nan'), True):
            self.assertIsNone(w._score_value({'omniscience': bad}, 'omniscience'))
        self.assertIsNone(w._score_value({'omniscienceV1': 88}, 'omniscience'))
        self.assertIsNone(w._score_value({'scores': {'omniscience': 88}}, 'omniscience'))
        self.assertEqual(w._score_value({'omniscience': -100}, 'omniscience'), -100)
        self.assertEqual(w._score_value({'omniscience': 100}, 'omniscience'), 100)

    def test_combined_batteries_replace_two_rates_with_one_metric(self):
        for split, combined in ((w.BATTERY, w.BATTERY_COMBINED),
                                (w.BATTERY_ALL, w.BATTERY_ALL_COMBINED)):
            self.assertEqual(len(combined), len(split) - 1)
            self.assertIn('omniscience_v11_combined', combined)
            self.assertNotIn('omniscience_v11_accuracy', combined)
            self.assertNotIn('omniscience_v11_non_hallucination', combined)
            self.assertEqual(set(combined) - {'omniscience_v11_combined'},
                             set(split) - {'omniscience_v11_accuracy', 'omniscience_v11_non_hallucination'})

    def test_modes_normalize_independent_complete_cohorts(self):
        models = complete_models(battery=w.BATTERY_ALL)
        for i, model in enumerate(models.values()):
            model['omniscience_v11_combined'] = float(i * i)
        models['combined_only'] = dict(models['m0'])
        del models['combined_only']['omniscience_v11_accuracy']
        split, _, split_stats = w.zscore_battery(models, w.BATTERY_ALL)
        combined, _, combined_stats = w.zscore_battery(models, w.BATTERY_ALL_COMBINED)
        self.assertEqual(len(split), 6)
        self.assertEqual(len(combined), 7)
        self.assertEqual(set(split_stats), set(w.BATTERY_ALL))
        self.assertEqual(set(combined_stats), set(w.BATTERY_ALL_COMBINED))
        for row in combined:
            zs = [row['zscores'][key] for key in w.BATTERY_ALL_COMBINED]
            self.assertEqual(row['softminz'], round(-math.log(sum(math.exp(-z) for z in zs)/len(zs)), 2))


class AllBenchmarksTests(unittest.TestCase):
    def test_all_battery_is_ten_components_with_split_omniscience(self):
        self.assertEqual(w.BATTERY_ALL, w.BATTERY + ['briefcaseElo',
                                                    'automationBenchPartialScore',
                                                    'gdpPdfAllPass'])
        self.assertEqual(len(w.BATTERY_ALL), 10)
        self.assertIn('omniscience_v11_accuracy', w.BATTERY_ALL)
        self.assertIn('omniscience_v11_non_hallucination', w.BATTERY_ALL)
        self.assertNotIn('omniscience_v11', w.BATTERY_ALL)
        self.assertNotIn('omniscience', w.BATTERY_ALL)

    def test_new_fields_read_flat_and_nested_sources(self):
        flat = dict(NEW_FLAT)
        nested = {'scores': {'aa-briefcase': NEW_FLAT['briefcaseElo'],
                             'automationbench-aa': NEW_FLAT['automationBenchPartialScore'],
                             'gdp-pdf': NEW_FLAT['gdpPdfAllPass']}}
        for key, val in NEW_FLAT.items():
            self.assertEqual(w._score_value(flat, key), val)
            self.assertEqual(w._score_value(nested, key), val)
            self.assertIsNone(w._score_value({}, key))

    def test_zscore_all_battery_scores_ten_components(self):
        models = complete_models(battery=w.BATTERY_ALL)
        ranked, rows, stats = w.zscore_battery(models, w.BATTERY_ALL)
        self.assertEqual(set(stats), set(w.BATTERY_ALL))
        self.assertEqual(len(ranked), 6)
        for row in ranked:
            self.assertEqual(len(row['zscores']), 10)
            zs = [row['zscores'][b] for b in w.BATTERY_ALL]
            self.assertAlmostEqual(row['softminz'],
                                   round(-math.log(sum(math.exp(-z) for z in zs) / 10), 2))

    def test_zscore_battery_defaults_to_science_subset(self):
        models = complete_models()
        ranked, rows, stats = w.zscore_battery(models)
        self.assertEqual(set(stats), set(w.BATTERY))

    def dual_page(self):
        models = complete_models(battery=w.BATTERY_ALL)
        ranked_sci, _, stats_sci = w.zscore_battery(models)
        ranked_all, _, stats_all = w.zscore_battery(models, w.BATTERY_ALL)
        return w.build_html(ranked_sci, w.pareto(ranked_sci, 'cost_task', 'softminz'),
                            stats_sci, ranked_all,
                            w.pareto(ranked_all, 'cost_task', 'softminz'), stats_all,
                            {}, models, 'dGVzdA==', 'dGVzdA==', WEIGHTS, 'test live')

    def test_html_renders_both_views_with_all_benchmarks_default(self):
        page = self.dual_page()
        for vid in ('id="view-all"', 'id="view-sci"', 'id="set-all-anchor"',
                    'id="set-sci-anchor"', 'id="all9-smz-table"',
                    'id="all9-cost-table"', 'id="rank-smz-table"',
                    'id="rank-cost-table"'):
            self.assertIn(vid, page)
        self.assertIn('#view-sci { display:none; }', page)
        self.assertEqual(page.count('<td>Model '), 24)
        self.assertIn('ten components', page)
        for label in ('AA-Briefcase v1.1', 'AutomationBench-AA', 'GDP.pdf'):
            self.assertIn(label, page)

    def test_html_embeds_both_charts(self):
        page = self.dual_page()
        self.assertEqual(page.count('data:image/png;base64,dGVzdA=='), 2)

    def test_each_view_has_its_own_head_to_head_panel(self):
        import re
        page = self.dual_page()
        for vid in ('id="head-to-head-all"', 'id="head-to-head"',
                    'data-h2h="h2h-all"', 'data-h2h="h2h"',
                    'id="h2h-all-data"', 'id="h2h-data"',
                    'id="h2h-all-controls"', 'id="h2h-controls"'):
            self.assertIn(vid, page)
        self.assertLess(page.index('id="head-to-head-all"'), page.index('id="view-sci"'))
        self.assertLess(page.index('id="view-sci"'), page.index('id="head-to-head"'))
        self.assertIn('10 all-benchmarks components', page)
        self.assertIn('7 science components', page)
        all_payload = re.search(r'<script type="application/json" id="h2h-all-data">(.*?)</script>',
                                page, re.S).group(1)
        sci_payload = re.search(r'<script type="application/json" id="h2h-data">(.*?)</script>',
                                page, re.S).group(1)
        self.assertEqual(len(json.loads(all_payload)['components']), 10)
        self.assertEqual(len(json.loads(sci_payload)['components']), 7)
        self.assertEqual(page.count('<script>'), 1)

    def test_comparison_data_uses_given_battery(self):
        models = complete_models(battery=w.BATTERY_ALL)
        ranked_all, _, _ = w.zscore_battery(models, w.BATTERY_ALL)
        data = w.comparison_data(ranked_all, w.BATTERY_ALL)
        self.assertEqual([c['key'] for c in data['components']], w.BATTERY_ALL)
        for model in data['models']:
            self.assertEqual(len(model['z']), 10)


class PublicationGateTests(unittest.TestCase):
    def test_render_failure_preserves_existing_artifacts(self):
        models = complete_models(battery=w.BATTERY_ALL)
        for i, model in enumerate(models.values()):
            model['omniscience_v11_combined'] = i * i
        with tempfile.TemporaryDirectory() as tmp:
            data, docs = Path(tmp)/'data', Path(tmp)/'docs'
            data.mkdir(); docs.mkdir()
            names = ['index.html', 'softminz_pareto.png', 'softminz_pareto_science.png',
                     'softminz_pareto_all-combined.png', 'softminz_pareto_sci-combined.png']
            for name in names: (docs/name).write_bytes(b'previous')
            def fake_chart(ranked, front, path): path.write_bytes(b'new chart')
            with patch.object(w, 'DATA', data), patch.object(w, 'DOCS', docs), \
                 patch.object(w, 'load_ii_benchmarks', return_value=(WEIGHTS, 'test')), \
                 patch.object(w, 'scrape', return_value=(models, {})), \
                 patch.object(w, 'make_chart', side_effect=fake_chart), \
                 patch.object(w, 'build_html', side_effect=RuntimeError('render failed')):
                with self.assertRaisesRegex(RuntimeError, 'render failed'): w.main()
            for name in names: self.assertEqual((docs/name).read_bytes(), b'previous', name)

    def test_combined_cohort_is_required_before_artifacts(self):
        self.check_aborts_before_artifacts({}, complete_models(battery=w.BATTERY_ALL))

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
        models = complete_models(battery=w.BATTERY_ALL)
        ranked, rows, stats = w.zscore_battery(models)
        ranked_all, _, stats_all = w.zscore_battery(models, w.BATTERY_ALL)
        page = w.build_html(ranked, w.pareto(ranked,'cost_task','softminz'), stats,
                            ranked_all, w.pareto(ranked_all,'cost_task','softminz'),
                            stats_all, {}, models, 'dGVzdA==', 'dGVzdA==',
                            WEIGHTS, 'test live')
        for label in w.BENCH_LABEL.values(): self.assertIn(label, page)
        for obsolete in ('six-benchmark battery', 'one scoring dimension', 'v4.3.2',
                         'Why the GPT-5.6', 'mandatory non-hallucination'):
            self.assertNotIn(obsolete, page)
        self.assertIn('359', page)
        self.assertEqual(page.count('<td>Model '), 24)


if __name__ == '__main__':
    unittest.main()
