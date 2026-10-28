#!/usr/bin/env python3
"""SoftMinZ public model-value watch — one script, one webpage.

Scrapes Artificial Analysis (free, no key), z-scores seven components
from six benchmarks chosen for scientific-computing relevance, computes the SoftMinZ
index (a soft-minimum of the z-scores over the fully-benched cohort),
prices each model with an agentic-workload cost per task derived from raw
AA cost data, draws the SoftMinZ-vs-cost Pareto frontier, and emits a
single self-contained docs/index.html for GitHub Pages.

Published AA costs and its cache/pricing assumptions only; no added discounts or free-tier substitutions.

SOFTMINZ
--------
Every battery benchmark is z-scored across the same strictly complete cohort.
SoftMinZ is the negative natural log of the mean of e^{-z}:

    SoftMinZ = -ln[ (1/n) * sum_b exp(-z_b) ]

a smooth soft-minimum of the z-scores: min(z) <= SoftMinZ <= mean(z),
with SoftMinZ ~= mean(z) - Var(z)/2 to leading order. Balanced profiles
are rewarded; lopsided ones are discounted. Only fully-benched models are
scored, so n is the same battery size for every model.

COST PER TASK
-------------
Artificial Analysis publishes a per-benchmark "weighted cost per task"
for the benchmarks in its Intelligence Index (per-model split embedded
in public model-page payloads; the leaderboard payload
carries only the aggregate total, used here as a cross-check). We divide
each weighted cost by the benchmark's Intelligence Index weight to recover
the unweighted cost, then average over four expensive agentic workloads
(AA-Briefcase v1.1, Terminal-Bench 4.0, FrontierCode 2.0, and
Terminal-Bench-Science 0.1), weighted by task count:

    C_task = sum_b C_b * T_b / sum_b T_b
"""
import argparse
import base64
import collections
import datetime
import html as htmllib
import json
import math
import pathlib
import re
import statistics
import sys
import time
import urllib.request

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / 'data'
DOCS = HERE / 'docs'
TODAY = datetime.date.today().isoformat()
UA = {'User-Agent': 'Mozilla/5.0 (compatible; softminz-watch/1.0)'}
BASE = 'https://artificialanalysis.ai/evaluations/'
II_METHOD_URL = 'https://artificialanalysis.ai/methodology/intelligence-benchmarking'
REPO_URL = 'https://github.com/brendangerardlucas/softminz'

# AA Intelligence Index v5.0 scientific-computing subset (2026-10-28).
# Never backfill a versioned benchmark with an older evaluation.
BATTERY = ['terminalbench_v40', 'frontiercode_v20', 'omniscience_v11_accuracy',
           'omniscience_v11_non_hallucination', 'hle_diamond',
           'critpt_v2_hard', 'terminalbench_science']
# STRICT COMPLETENESS: partial profiles neither score nor enter any z-pool.
BENCH_LABEL = {
    'terminalbench_v40': 'Terminal-Bench 4.0',
    'frontiercode_v20': 'FrontierCode 2.0',
    'omniscience_v11_accuracy': 'AA-Omniscience v1.1 — Accuracy',
    'omniscience_v11_non_hallucination': 'AA-Omniscience v1.1 — Non-hallucination',
    'hle_diamond': 'HLE-Diamond',
    'critpt_v2_hard': 'CritPt v2 (Hard Subset)',
    'terminalbench_science': 'Terminal-Bench-Science 0.1',
}
BENCH_URL = {
    'terminalbench_v40': BASE + 'terminalbench-v4-0',
    'frontiercode_v20': BASE + 'frontiercode-2-0',
    'omniscience_v11_accuracy': BASE + 'omniscience',
    'omniscience_v11_non_hallucination': BASE + 'omniscience',
    'hle_diamond': BASE + 'hle-diamond',
    'critpt_v2_hard': BASE + 'critpt',
    'terminalbench_science': BASE + 'terminal-bench-science',
}
FIELD_MAP = {
    'terminalbench_v40': 'terminalBench40',
    'frontiercode_v20': 'frontierCode20',
    'omniscience_v11_accuracy': 'omniscienceAccuracy',
    'omniscience_v11_non_hallucination': 'omniscienceNonHallucination',
    'hle_diamond': 'hleDiamond',
    'critpt_v2_hard': 'critptAgenticHard',
    'terminalbench_science': 'terminalBenchScience',
    'intelligence_index': 'intelligenceIndex',
    'analystAgent': 'analystAgent',  # watch-only, never a scoring dimension
}
# Primary data source: the /leaderboards/models page embeds the COMPLETE
# leaderboard model dataset (every available battery field) in its
# Next.js flight payload. As of 2026-08-18 the individual /evaluations/*
# pages only embed the top ~30 records plus name stubs for the rest, so
# scraping them per-page no longer yields the full field. As of 2026-09-10
# the leaderboard's intelligenceIndexCostPerTask is only an aggregate
# total — the per-benchmark cost split comes from a /models carrier page
# (_fetch_cost_breakdown below).
MODELS_PAGE = 'https://artificialanalysis.ai/leaderboards/models'
MODELS_DIR = 'https://artificialanalysis.ai/models/'


def aggregate_cost(record):
    value = record.get('intelligenceIndexCostPerTask')
    if is_number(value):
        return value
    if isinstance(value, dict) and isinstance(value.get('cost'), dict):
        value = value['cost'].get('total')
        return value if is_number(value) else None
    return None


def _fetch_cost_breakdown(records, max_age_h=12):
    """Merge exact-slug v5 splits and require coverage of all published totals.

    Some public model pages embed the full dataset; others only initial selected
    models. Try several carriers, then genuine self-pages for any remaining
    aggregate-bearing model. Never copy a split to a sibling effort variant.
    """
    wanted = {s for s, r in records.items() if aggregate_cost(r) is not None}
    merged, carriers, errors = {}, [], []

    def read_carrier(cand):
        path = DATA / f'model-cost-{cand}.html'
        raw = fetch(MODELS_DIR + cand, path, max_age_h)
        recs = extract_records(flight(raw))
        splits = {slug: split for slug, rec in recs.items()
                  if (split := extract_cost_split(rec)) is not None}
        # A cached initial-selection page can miss variants/new v5 components.
        if max_age_h > 0 and not (wanted - set(merged)) <= set(splits):
            raw = fetch(MODELS_DIR + cand, path, 0)
            recs = extract_records(flight(raw))
            splits = {slug: split for slug, rec in recs.items()
                      if (split := extract_cost_split(rec)) is not None}
        for slug, split in splits.items():
            if slug in merged and any(abs(split[k] - merged[slug][k]) > 1e-6
                                      for k in II_BENCHMARK_SLUGS):
                raise ValueError(f'conflicting cost splits for {slug}')
            expected = aggregate_cost(records.get(slug, {}))
            if expected is not None and abs(sum(split.values()) - expected) > 1e-6:
                raise ValueError(f'cost split disagrees with leaderboard total for {slug}')
            merged[slug] = split
        if splits:
            carriers.append(cand)

    candidates = list(dict.fromkeys(sorted(records)[:5]
                      + (['command-a-plus'] if 'command-a-plus' in records else [])))
    attempted = set()
    for cand in candidates:
        attempted.add(cand)
        try:
            read_carrier(cand)
        except ValueError as exc:
            raise SystemExit(f'FATAL: invalid v5 cost source: {exc}') from exc
        except Exception as exc:
            errors.append(f'{cand}: {exc}')
        if merged and wanted <= set(merged):
            break
    # Recover only published measured costs from the matching model's own page.
    for cand in sorted(wanted - set(merged) - attempted):
        try:
            read_carrier(cand)
        except ValueError as exc:
            raise SystemExit(f'FATAL: invalid v5 cost source: {exc}') from exc
        except Exception as exc:
            errors.append(f'{cand}: {exc}')
        time.sleep(0.25)
    missing = wanted - set(merged)
    if not merged or missing:
        detail = f'missing published splits: {", ".join(sorted(missing))}' if missing else 'no complete v5 splits'
        raise SystemExit(f'FATAL: {detail}; refusing incomplete cost coverage ({"; ".join(errors)}).')
    return merged, '+'.join(carriers)

# Per-evaluation pages cross-check the leaderboard scrape using JSON-LD
# score rows or, when absent, their model payloads:
# page slug -> (payload field, JSON-LD label).
PAGES = {
    'terminalbench-v4-0': ('terminalbench_v40', 'Terminal-Bench 4.0'),
    'frontiercode-2-0': ('frontiercode_v20', 'FrontierCode 2.0'),
    'omniscience': [
        ('omniscience_v11_accuracy', 'AA-Omniscience v1.1 Accuracy'),
        ('omniscience_v11_non_hallucination', 'AA-Omniscience v1.1 Non-Hallucination Rate'),
    ],
    'hle-diamond': ('hle_diamond', 'HLE-Diamond'),
    'critpt': ('critpt_v2_hard', 'CritPt v2 (Hard Subset)'),
    'terminal-bench-science': ('terminalbench_science', 'Terminal-Bench-Science 0.1'),
    'artificial-analysis-intelligence-index': ('intelligence_index', 'Intelligence Index'),
}

# Fixed identity of the expensive-workload cost subset, not per-model selection.
II_COST_SLUGS = {'aa-briefcase', 'terminalbench-4-0', 'frontiercode-2-0',
                 'terminal-bench-science'}
# All nine components are required for the aggregate cost cross-check.
II_TABLE_NAMES = {
    'AA-Briefcase v1.1': 'aa-briefcase',
    'AutomationBench-AA': 'automationbench-aa',
    'GDP.pdf': 'gdp-pdf',
    'FrontierCode 2.0': 'frontiercode-2-0',
    'Terminal-Bench 4.0': 'terminalbench-4-0',
    'Terminal-Bench-Science 0.1': 'terminal-bench-science',
    'CritPt v2 (Hard Subset)': 'critpt-v2-hard',
    'AA-Omniscience v1.1': 'omniscience',
    'HLE-Diamond': 'hle-diamond',
}
II_BENCHMARK_SLUGS = set(II_TABLE_NAMES.values())
COST_LABEL = {slug: label for label, slug in II_TABLE_NAMES.items()}
COST_SLUG_ALIASES = {'terminalbench-v4-0': 'terminalbench-4-0'}


# ---------------------------------------------------------------------------
# Scraping helpers (AA publishes per-model records inside Next.js flight
# payloads; each model is one nested JSON object, so fields can never leak
# between models. Overlapping evaluation-page scores cross-check the
# leaderboard values; missing comparison data is reported explicitly.)
# ---------------------------------------------------------------------------
def fetch(url, cache_path, max_age_h=12):
    p = pathlib.Path(cache_path)
    if p.exists():
        age = (datetime.datetime.now().timestamp() - p.stat().st_mtime) / 3600
        if age < max_age_h:
            return p.read_text(errors='ignore')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read().decode('utf-8', errors='ignore')
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw)
    return raw


def flight(raw):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', raw)
    return ''.join(json.loads('"' + c + '"') for c in chunks)


def extract_records(payload):
    """{slug: record_dict} — each model's own nested object from the payload.

    Objects are found by brace-matching outward from each "shortName"
    anchor until one parses as a dict containing 'slug' and 'shortName'.
    Deserialising the whole record makes cross-model field leakage
    structurally impossible. (AA renamed short_name -> shortName in their
    flight payload on 2026-08-18; stub records without scores carry no
    shortName and are skipped automatically.)
    """
    out = {}
    for m in re.finditer(r'"shortName":"', payload):
        j = m.start()
        for _ in range(200):
            j = payload.rfind('{', 0, j)
            if j < 0:
                break
            depth, in_str, esc, end = 0, False, False, None
            cap = min(j + 2_000_000, len(payload))
            for k in range(j, cap):
                c = payload[k]
                if in_str:
                    if esc:
                        esc = False
                    elif c == '\\':
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = k
                        break
            if end is None:
                break
            try:
                obj = json.loads(payload[j:end + 1])
            except Exception:
                continue
            if (isinstance(obj, dict) and 'slug' in obj and 'shortName' in obj
                    and len(obj) >= 10):
                s = obj['slug']
                if s not in out or len(obj) > len(out[s]):
                    out[s] = obj
                break
    return out


def jsonld_scores(raw, label):
    """Ground truth {slug: value} from the page's JSON-LD 'X: Score' block."""
    truth = {}
    for b in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', raw, re.S):
        try:
            d = json.loads(htmllib.unescape(b))
        except Exception:
            continue
        if not isinstance(d, dict) or 'data' not in d:
            continue
        name = str(d.get('name', ''))
        if not name.lower().endswith('score') or label.lower() not in name.lower():
            continue
        for row in d['data']:
            if 'detailsUrl' not in row:
                continue
            nums = [v for k, v in row.items()
                    if k != 'detailsUrl' and isinstance(v, (int, float))]
            if len(nums) == 1:
                truth[row['detailsUrl'].rsplit('/', 1)[-1]] = nums[0]
    return truth


# AA 2026-10-26: leaderboard benchmark values moved into a slug-keyed
# scores object; evaluation pages still carry the legacy flat fields.
SCORE_SLUGS = {
    'terminalBench40': 'terminalbench-4-0',
    'frontierCode20': 'frontiercode-2-0',
    'hleDiamond': 'hle-diamond',
    'critptAgenticHard': 'critpt-v2-hard',
    'terminalBenchScience': 'terminal-bench-science',
    'analystAgent': 'aa-analyst-agent',
    'omniscienceAccuracy': 'omniscience-accuracy',
    'omniscienceNonHallucination': 'omniscience-non-hallucination',
}


def is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _score_value(record, key):
    """Read the exact named evaluation; reject booleans/non-finite values."""
    value = record.get(key)
    if not is_number(value):
        scores = record.get('scores')
        value = scores.get(SCORE_SLUGS.get(key, key)) if isinstance(scores, dict) else None
    # Evaluation pages publish current v1.1 accuracy and hallucination rate
    # directly in this breakdown. Never use omniscienceV1 or its old total.
    components = ('omniscienceAccuracy', 'omniscienceNonHallucination')
    if not is_number(value) and key in components:
        breakdown = record.get('omniscienceBreakdown')
        if isinstance(breakdown, dict):
            if key == 'omniscienceAccuracy':
                value = breakdown.get('accuracy')
            else:
                rate = breakdown.get('hallucinationRate')
                value = 1. - rate if is_number(rate) and 0. <= rate <= 1. else None
    if not is_number(value) or (key in components and not 0. <= value <= 1.):
        return None
    return value


def extract_cost_split(record):
    """Return an exact v5 split; missing data is unavailable, contradictions fatal."""
    cost = record.get('intelligenceIndexCostPerTask')
    if not isinstance(cost, dict) or not isinstance(cost.get('evaluations'), list):
        return None
    split = {}
    for item in cost['evaluations']:
        if not isinstance(item, dict) or not isinstance(item.get('slug'), str):
            return None
        slug = COST_SLUG_ALIASES.get(item['slug'], item['slug'])
        value = item.get('weightedCostPerTask')
        if slug in split:
            raise ValueError(f'duplicate cost component: {slug}')
        if not is_number(value) or value < 0:
            return None
        split[slug] = value
    if set(split) != II_BENCHMARK_SLUGS:
        return None
    aggregate = cost.get('cost')
    total = aggregate.get('total') if isinstance(aggregate, dict) else None
    if not is_number(total) or total < 0:
        return None
    if not math.isclose(sum(split.values()), total, rel_tol=0., abs_tol=1e-6):
        raise ValueError('v5 cost split disagrees with its carrier aggregate')
    return split


def cost_per_task(weighted, ii_weights):
    """Deweight and task-count-average the same four workloads for every model."""
    total, tasks = 0.0, 0
    for slug in sorted(II_COST_SLUGS):
        cost = weighted.get(slug)
        info = ii_weights.get(slug, {})
        weight, count = info.get('weight'), info.get('tasks')
        if (not is_number(cost) or cost < 0 or not is_number(weight) or weight <= 0
                or type(count) is not int or count <= 0):
            return None
        total += (cost / weight) * count
        tasks += count
    return total / tasks if tasks and total > 0 else None


def scrape(max_age_h=12, ii_weights=None):
    models = collections.defaultdict(dict)
    report = {}
    if not ii_weights:
        raise ValueError('ii_weights is required — call load_ii_benchmarks() first')

    # --- primary scrape: the complete model dataset from /leaderboards/models
    try:
        raw = fetch(MODELS_PAGE, DATA / 'leaderboards-models.html', max_age_h)
        records = extract_records(flight(raw))
    except Exception as e:
        report['leaderboards/models'] = f'FAILED: {e}'
        return dict(models), report
    if not records:
        report['leaderboards/models'] = 'FAILED: 0 records extracted'
        return dict(models), report

    counts = collections.Counter()
    for s, rec in records.items():
        nm = rec.get('name') or rec.get('shortName') or s
        models[s].setdefault('name', nm)
        for f, key in FIELD_MAP.items():
            v = _score_value(rec, key)
            if isinstance(v, (int, float)):
                models[s][f] = float(v)
                counts[f] += 1
        # leaderboard cost is an II-weighted aggregate, not the
        # per-benchmark split: keep it only as a cross-check of the split
        # fetched below (sum of split must equal the published total).
        total = aggregate_cost(rec)
        if total is not None:
            models[s]['_ii_cost_total'] = total
    # AA public model-page payloads carry per-benchmark splits. Some pages
    # contain full data, some selected models: require every leaderboard
    # aggregate-bearing model to have its own exact validated v5 split.
    costmap, carrier = _fetch_cost_breakdown(records, max_age_h)
    n_checked = n_bad = 0
    for s, weighted in costmap.items():
        if s not in models:
            continue
        cost = cost_per_task(weighted, ii_weights)
        if cost is not None:
            models[s]['cost_task'] = cost
            counts['cost_task'] += 1
        exp = models[s].pop('_ii_cost_total', None)
        if exp is not None:
            n_checked += 1
            if abs(sum(weighted.values()) - exp) > 1e-6:
                n_bad += 1
    if n_bad:
        print(f'FATAL: cost split sums disagree with leaderboard totals '
              f'({n_bad}/{n_checked}). Cost semantics drifted — refusing to publish.',
              file=sys.stderr)
        sys.exit(1)
    source_zeros = sum(1 for s, split in costmap.items() if s in models and sum(split.values()) == 0)
    report[f'models/{carrier}'] = (f'v5 cost split ({len(costmap)} complete source splits, '
                                   f'{n_checked} leaderboard totals cross-checked, '
                                   f'{counts["cost_task"]} positive leaderboard prices, '
                                   f'{source_zeros} source-zero prices excluded)')
    report['leaderboards/models'] = (
        f'{len(records)} records — '
        + ', '.join(f'{f}:{counts[f]}' for f in FIELD_MAP if counts[f]))

    # --- cross-validation: JSON-LD score rows when available; otherwise
    # the evaluation page's own model payload. AA's JSON-LD now sometimes
    # contains only Dataset metadata, without any numeric score rows.
    # Mismatches reject that benchmark's values.
    for slug, page_checks in PAGES.items():
        checks = page_checks if isinstance(page_checks, list) else [page_checks]
        def report_key(field):
            return f'{slug}/{field}' if len(checks) > 1 else slug
        try:
            raw = fetch(BASE + slug, DATA / f'{slug}.html', max_age_h)
        except Exception as exc:
            for field, label in checks:
                report[report_key(field)] = f'validation FAILED: {exc}'
            time.sleep(0.5)
            continue
        evaluation_records = None
        for field, label in checks:
            key = report_key(field)
            try:
                truth = jsonld_scores(raw, label)
                source = 'JSON-LD'
                if not truth:
                    if evaluation_records is None:
                        evaluation_records = extract_records(flight(raw))
                    truth = {s: value for s, rec in evaluation_records.items()
                             if (value := _score_value(rec, FIELD_MAP[field])) is not None}
                    source = 'evaluation-page payload (JSON-LD score rows unavailable)'
                checked = bad = 0
                for s, exp in truth.items():
                    got = models.get(s, {}).get(field)
                    if got is None:
                        continue
                    checked += 1
                    if abs(got - exp) > 1e-6:
                        bad += 1
                if checked and bad:
                    for s in models:
                        models[s].pop(field, None)
                    report[key] = f'REJECTED ({bad}/{checked} mismatched vs {source})'
                elif not checked:
                    report[key] = 'validation UNAVAILABLE (no overlapping source scores)'
                else:
                    report[key] = f'validated ({checked} checked vs {source})'
            except Exception as exc:
                report[key] = f'validation FAILED: {exc}'
        time.sleep(0.5)
    return dict(models), report


# ---------------------------------------------------------------------------
# Live Intelligence Index weights — parsed from AA's methodology page on
# every run. No hardcoded fallback: if the page is unreachable or its table
# cannot be parsed, the run dies (see load_ii_benchmarks).
# ---------------------------------------------------------------------------
def _td_text(td):
    return htmllib.unescape(re.sub(r'<[^>]+>', '', td)).strip()


def parse_ii_methodology_weights(raw):
    """Parse {slug: {'weight': float, 'tasks': int}} from the methodology
    page HTML (table columns: Evaluation | Questions | ... | Weighting)."""
    weights = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', raw, re.S):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if not cells:
            continue
        texts = [_td_text(c) for c in cells]
        slug = eval_idx = None
        for i, t in enumerate(texts):
            if t in II_TABLE_NAMES:
                slug, eval_idx = II_TABLE_NAMES[t], i
                break
        if slug is None or eval_idx is None or eval_idx + 1 >= len(texts):
            continue
        weight_cell = next((t for t in texts if t.endswith('%')), None)
        if weight_cell is None:
            continue
        m = re.search(r'^(\d[\d,]*)', texts[eval_idx + 1])
        if not m:
            continue
        weights[slug] = {'weight': float(weight_cell.rstrip('%')) / 100.0,
                         'tasks': int(m.group(1).replace(',', ''))}
    return weights


def load_ii_benchmarks(cache_dir, max_age_h=12):
    """Load II weights/task counts live from AA. Returns (dict, source_str).

    No fallback: if the page cannot be fetched or its table parsed, the run
    DIES rather than publish costs computed from stale weights. Requires
    every cost benchmark present with a positive weight."""
    DATA.mkdir(exist_ok=True)
    try:
        raw = fetch(II_METHOD_URL, pathlib.Path(cache_dir) / 'methodology.html', max_age_h)
    except Exception as e:
        print(f'FATAL: could not fetch AA methodology page: {e}', file=sys.stderr)
        sys.exit(1)
    parsed = parse_ii_methodology_weights(raw)
    missing = II_BENCHMARK_SLUGS - set(parsed)
    valid_version = bool(re.search(r'Intelligence Index v5\.0', _td_text(raw)))
    if (not valid_version or missing or set(parsed) != II_BENCHMARK_SLUGS
            or any(not is_number(v['weight']) or v['weight'] <= 0
                   or type(v['tasks']) is not int or v['tasks'] <= 0 for v in parsed.values())
            or not math.isclose(sum(v['weight'] for v in parsed.values()), 1., abs_tol=1e-6)):
        print(f'FATAL: AA methodology table unparseable or incomplete '
              f'(missing: {sorted(missing) or "none"}; parsed {len(parsed)} rows). '
              f'Refusing to publish costs from stale weights.', file=sys.stderr)
        sys.exit(1)
    return parsed, 'live (AA v5.0 methodology page, parsed this run)'


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AA-AnalystAgent watch (user directive 2026-09-05): NOT scored (30-model
# frontier-only coverage; not yet representative). This standing check logs
# coverage every run; the directive is to strongly consider adding it to the
# battery once AA publishes broad evaluation.
# ---------------------------------------------------------------------------
ANALYST_AGENT_WATCH_THRESHOLD = 100


def _watch_analyst_agent(models):
    n = sum(1 for d in models.values() if d.get('analystAgent') is not None)
    total = len(models)
    line = (f'analystAgent watch: {n}/{total} models evaluated '
            f'(threshold {ANALYST_AGENT_WATCH_THRESHOLD})')
    if n >= ANALYST_AGENT_WATCH_THRESHOLD:
        line += ' — THRESHOLD REACHED: strongly consider adding to battery'
    print(line, file=sys.stderr)
    return n


def zscore_battery(models):
    """Normalize every dimension over the same complete cohort; score all components or none."""
    rows = []
    for slug, d in models.items():
        r = {'slug': slug, 'name': d.get('name', slug)}
        for f in BATTERY:
            r[f] = d.get(f)
        r['cost_task'] = d.get('cost_task')
        r['ii'] = d.get('intelligence_index')
        rows.append(r)

    # z-pools: STRICT — only models with the complete battery contribute
    # to the mean/SD (partial profiles neither receive a score nor move
    # the statistics).
    complete = [r for r in rows if all(is_number(r.get(f)) for f in BATTERY)]
    zstats = {}
    for f in BATTERY:
        vals = [r[f] for r in complete]
        if len(vals) >= 5:
            mu = sum(vals) / len(vals)
            # Sample SD (Bessel-corrected, n-1): the measured field is treated
            # as a sample of the evaluations one actually encounters, so the
            # z-scale estimates the underlying spread rather than describing
            # only today's cohort.
            sd = (sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
            if sd > 0:
                zstats[f] = (mu, sd)

    for r in rows:
        r['zscores'] = {}
        for f in BATTERY:
            if is_number(r.get(f)) and f in zstats:
                r['zscores'][f] = (r[f] - zstats[f][0]) / zstats[f][1]
        r['battery_ok'] = all(is_number(r.get(f)) for f in BATTERY)
        if r['battery_ok'] and set(zstats) == set(BATTERY):
            zs = list(r['zscores'].values())
            r['softminz'] = round(-math.log(sum(math.exp(-z) for z in zs) / len(zs)), 2)
        else:
            r['softminz'] = None

    ranked = sorted([r for r in rows if r['softminz'] is not None],
                    key=lambda r: (-r['softminz'], r['slug']))
    for i, r in enumerate(ranked, 1):
        r['rank'] = i
    return ranked, rows, zstats


def pareto(items, xkey, ykey):
    """Best-in-class per price: no cheaper item has >= y."""
    pts = sorted([r for r in items if r.get(xkey) and r.get(ykey) is not None],
                 key=lambda r: r[xkey])
    front, best = [], -1e9
    for r in pts:
        if r[ykey] > best:
            front.append(r)
            best = r[ykey]
    return front


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
def make_chart(ranked, front, out_path):
    pts = [r for r in ranked if r.get('cost_task') and r.get('softminz') is not None]
    fig, ax = plt.subplots(figsize=(11.5, 6.8))
    ax.scatter([r['cost_task'] for r in pts], [r['softminz'] for r in pts],
               s=30, color='#c7d0d9', alpha=0.75, zorder=2,
               label=f'Other models (n={len(pts) - len(front)})')
    fx = [r['cost_task'] for r in front]
    fy = [r['softminz'] for r in front]
    ax.plot(fx, fy, '--', color='#7a8894', lw=1.4, zorder=3, alpha=0.9)
    cmap = plt.get_cmap('turbo')
    marks = ['o', 's', 'D', '^', 'v', 'P', 'X', '*', 'h', '<', '>', 'p']
    for i, r in enumerate(front):
        ax.scatter([r['cost_task']], [r['softminz']],
                   s=132 if marks[i % len(marks)] != '*' else 210,
                   marker=marks[i % len(marks)],
                   color=cmap(0.06 + 0.88 * i / max(len(front) - 1, 1)),
                   edgecolors='white', linewidths=1.0, zorder=5,
                   label=f'{i + 1}. {r["name"][:40]}  (${r["cost_task"]:.3f})')
    ax.set_xscale('log')
    ax.set_xlabel('Agentic cost per task (USD, log scale)')
    ax.set_ylabel(r'SoftMinZ = $-\ln\left[\frac{1}{n}\sum_{b} e^{-z_b}\right]$'
                  ' (soft-min of battery z-scores)')
    ax.set_title('SoftMinZ vs cost per agentic task', fontweight='bold',
                 loc='left', fontsize=12)
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f'${v:g}' if v >= 1 else f'${v:.3f}'.rstrip('0')))
    ax.grid(alpha=0.22)
    ax.legend(loc='center left', bbox_to_anchor=(1.005, 0.5), fontsize=8.2,
              title='Pareto frontier — cheapest first', title_fontsize=8.8,
              frameon=True, framealpha=0.95, borderpad=0.7, labelspacing=0.62)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches='tight')
    plt.close(fig)


# ---------------------------------------------------------------------------
# Webpage
# ---------------------------------------------------------------------------
CSS = """
:root { --ink:#1c2733; --mut:#5c6b7a; --line:#dde4ea; --accent:#0f2a43; --pareto:#0f6b3a; }
* { box-sizing:border-box; }
body { margin:0; color:var(--ink); background:#fbfcfd;
       font:16px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:40px 22px 70px; }
h1 { font-size:1.7rem; margin:0 0 4px; color:var(--accent); }
h2 { font-size:1.25rem; margin:2.2em 0 .5em; color:var(--accent); }
h3 { font-size:1.02rem; margin:1.6em 0 .4em; }
.sub { color:var(--mut); margin:0 0 26px; }
.math { display:block; background:#f2f5f8; border:1px solid var(--line); border-radius:8px;
        padding:14px 18px; margin:12px 0; font-family:'SF Mono',Consolas,Menlo,monospace;
        font-size:15px; overflow-x:auto; text-align:center; }
.plot { width:100%; border:1px solid var(--line); border-radius:10px; margin:14px 0 8px; }
table { border-collapse:collapse; width:100%; font-size:14.5px; }
thead th { position:sticky; top:0; background:var(--accent); color:#fff; text-align:left;
           padding:8px 12px; font-weight:600; }
th.num, td.num { text-align:right; font-variant-numeric:tabular-nums; }
tbody td { padding:6px 12px; border-bottom:1px solid var(--line); }
tbody tr:nth-child(even) { background:#f4f7f9; }
tr.frontier td { font-weight:600; }
tbody tr:hover { background:#eaf1f6; }
.tblwrap { max-height:70vh; overflow:auto; border:1px solid var(--line); border-radius:10px; }
.sortctl { display:flex; align-items:center; gap:14px; margin:6px 0 10px; flex-wrap:wrap; }
.sortctl label { font-weight:600; color:var(--mut); font-size:14px; }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.seg a { display:inline-block; border:0; background:#fff; color:var(--ink); padding:7px 16px;
         font-size:15px; font-weight:500; min-height:40px; min-width:110px; text-align:center;
         text-decoration:none; line-height:28px; }
.seg a + a { border-left:1px solid var(--line); }
.seg a.on, .seg a:active { background:var(--accent); color:#fff; font-weight:600; }
/* No-JS ranking toggle: :target swaps which table + button is active.
   Order inside #ranking: anchor spans, then .sortctl, then both tables. */
#rank-smz-anchor, #rank-cost-anchor { position:relative; top:-90px; visibility:hidden; }
#rank-cost-table { display:none; }
#rank-cost-anchor:target ~ #rank-cost-table { display:block; }
#rank-cost-anchor:target ~ #rank-smz-table { display:none; }
#rank-cost-anchor:target ~ .sortctl .seg a[href="#rank-cost-anchor"] { background:var(--accent); color:#fff; font-weight:600; }
#rank-cost-anchor:target ~ .sortctl .seg a[href="#rank-smz-anchor"] { background:#fff; color:var(--ink); font-weight:500; }
#ranknote { color:var(--mut); font-size:13px; }
#rank-cost-anchor:target ~ .sortctl #ranknote { display:none; }
#rank-cost-anchor:target ~ .sortctl #ranknote-cost { display:inline; }
#ranknote-cost { display:none; color:var(--mut); font-size:13px; }
.note { color:var(--mut); font-size:13.5px; }
footer { margin-top:48px; padding-top:16px; border-top:1px solid var(--line);
         color:var(--mut); font-size:13.5px; }
code { background:#eef2f6; border-radius:4px; padding:1px 5px; font-size:.92em; }
"""


def esc(s):
    return htmllib.escape(str(s), quote=True)


def fmt_cost(v):
    return '—' if v is None else f'${v:.4f}'


def build_html(ranked, front, zstats, report, models, img_b64, ii_weights, ii_source):
    frontier_slugs = {r['slug'] for r in front}
    n_scored = len(ranked)
    n_measured = len(models)
    n_cost = sum(1 for r in ranked if r.get('cost_task') is not None)

    battery_items = ''.join(
        f'<li><a href="{BENCH_URL[b]}">{esc(BENCH_LABEL[b])}</a></li>' for b in BATTERY)
    cost_rows = ''.join(
        f'<tr><td>{esc(COST_LABEL[b])}</td><td class="num">{ii_weights[b]["weight"]:.0%}</td>'
        f'<td class="num">{ii_weights[b]["tasks"]:,}</td></tr>' for b in sorted(II_COST_SLUGS))
    all_weight_rows = ''.join(
        f'<tr><td>{esc(COST_LABEL[b])}</td><td class="num">{info["weight"]:.0%}</td>'
        f'<td class="num">{info["tasks"]:,}</td></tr>' for b, info in ii_weights.items())
    cost_total_tasks = sum(ii_weights[b]['tasks'] for b in II_COST_SLUGS)
    stats_rows = ''.join(
        f'<tr><td>{esc(BENCH_LABEL[b])}</td><td class="num">{zstats[b][0]:.6f}</td>'
        f'<td class="num">{zstats[b][1]:.6f}</td></tr>' for b in BATTERY)

    rows_smz = sorted(ranked, key=lambda r: (-r['softminz'], r['slug']))
    rows_cost = sorted(ranked, key=lambda r: (r.get('cost_task') is None,
                                              r.get('cost_task') or 0,
                                              -r['softminz'], r['slug']))

    def table_rows(rows, frontier_slugs):
        out = []
        for r in rows:
            cls = ' class="frontier"' if r['slug'] in frontier_slugs else ''
            out.append(
                f'<tr{cls}><td>{esc(r["name"])}</td>'
                f'<td class="num">{r["softminz"]:.2f}</td>'
                f'<td class="num">{fmt_cost(r.get("cost_task"))}</td></tr>')
        return chr(10).join(out)

    tbl_head = ('<thead><tr><th>Model / variant</th><th class="num">SoftMinZ</th>'
                '<th class="num">Cost per task</th></tr></thead>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LLM Index for Scientific Computing</title>
<meta name="description" content="SoftMinZ — a soft-minimum index over a seven-component AA v5 battery chosen for scientific-computing relevance, ranked against raw cost per agentic task. Only models evaluated on every battery benchmark are scored. Updated daily from Artificial Analysis data.">
<meta property="og:title" content="LLM Index for Scientific Computing (SoftMinZ)">
<meta property="og:description" content="Frontier LLMs ranked by a soft-minimum performance index for scientific computing vs raw cost per agentic task. Updated daily.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://softminz.org/">
<meta property="og:image" content="https://softminz.org/softminz_pareto.png">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='%230f2a43'/><text x='32' y='45' font-family='sans-serif' font-size='40' font-weight='700' fill='white' text-anchor='middle'>Z</text></svg>">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>LLM Index for Scientific Computing</h1>
<p class="sub">Generated {TODAY} · {n_scored} models scored from {n_measured} measured by
<a href="https://artificialanalysis.ai">Artificial Analysis</a> · raw cost data only</p>

<img class="plot" alt="SoftMinZ vs cost per agentic task scatter with Pareto frontier"
     src="data:image/png;base64,{img_b64}">
<p class="note">Each point is a model: vertical position is the SoftMinZ performance index,
horizontal position the raw cost of one agentic task (log scale). The dashed line is the
Pareto frontier — models for which no cheaper model is at least as good. Frontier members are
colour- and shape-coded; everything else is grey.</p>

<h2>Full ranking</h2>
<p class="note">Every scored model. Bold rows are Pareto frontier members. Use the two
buttons to switch the ranking — they need no JavaScript. In cost view, models with no
published cost data sort last.</p>
<div id="ranking">
<span id="rank-smz-anchor"></span><span id="rank-cost-anchor"></span>
<div class="sortctl">
  <label>Rank by</label>
  <span class="seg">
    <a class="on" href="#rank-smz-anchor">Highest SoftMinZ</a><a href="#rank-cost-anchor">Lowest cost per task</a>
  </span>
  <span id="ranknote">Best model first (highest SoftMinZ).</span>
  <span id="ranknote-cost">Cheapest model first (lowest cost per task).</span>
</div>
<div class="tblwrap" id="rank-smz-table">
<table>
{tbl_head}
<tbody>
{table_rows(rows_smz, frontier_slugs)}
</tbody>
</table>
</div>
<div class="tblwrap" id="rank-cost-table">
<table>
{tbl_head}
<tbody>
{table_rows(rows_cost, frontier_slugs)}
</tbody>
</table>
</div>
</div>

<h2>What SoftMinZ measures</h2>
<p>SoftMinZ uses seven separately standardized components from six benchmarks in the
<a href="{II_METHOD_URL}">Artificial Analysis Intelligence Index v5.0</a>,
selected for scientific computing:</p>
<ul>{battery_items}</ul>
<p>Terminal-Bench 4.0 measures general terminal execution; FrontierCode 2.0 tests
changes to real software repositories; Terminal-Bench-Science 0.1 covers scientific
terminal workflows. CritPt v2's hard subset and HLE-Diamond test difficult scientific
reasoning and knowledge. AA-Omniscience v1.1 contributes two distinct inputs:
<strong>accuracy</strong> and <strong>non-hallucination rate</strong> (1 minus AA’s
hallucination rate). Each gets its own cohort mean, sample standard deviation and z-score.</p>
<p><strong>The combined Omniscience Index is not scored.</strong> Accuracy and
non-hallucination each enter the partition sum once, alongside the five other components.
The former SciCode, AA-LCR, original HLE and original CritPt measurements are not used.
FrontierCode 1.x, full CritPt v2 and AA-Omniscience v1 cannot substitute for the named
versions or hard subset. Versions are not treated as interchangeable.</p>

<h3>Complete cohort, sample z-scores</h3>
<p>A model must have a finite score on <strong>all seven components</strong> to receive
SoftMinZ or contribute to any component's normalization. Partial profiles are excluded
from both the ranking and all z-score pools. Every component uses the same complete
cohort of {n_scored} models, with its mean and sample standard deviation:</p>
<div class="math">z<sub>b</sub> = (x<sub>b</sub> − μ<sub>b</sub>) / s<sub>b</sub>
&nbsp; ; &nbsp; s<sub>b</sub> uses the n − 1 denominator</div>
<div class="math">Z = Σ<sub>i=1…7</sub> exp(−z<sub>i</sub>)<br>
SoftMinZ = −ln(Z / 7)</div>
<p>The partition function is divided by seven to take the <strong>mean of the
Boltzmann factors</strong>, not a linear average of the z-scores. AA's Intelligence
Index weights do <strong>not</strong> weight the performance score. A component's
local influence is exp(−z<sub>i</sub>) / Z, so weaker components matter more; there
are no fixed 1/7 linear score weights. The soft-minimum lies
between a model's worst and mean z-score. Weak dimensions receive more influence:
balanced excellence is rewarded, while strength on one benchmark cannot linearly
cancel weakness on another.</p>
<p class="note">The battery, evaluation versions and cohort changed with AA v5.0.
These values and rankings are not directly comparable with either the former
pre-v5 battery or the initial six-component v5 score that used the combined Omniscience Index. Missing data is never filled with older benchmark versions.</p>
<table><thead><tr><th>Score component</th><th class="num">Cohort mean</th>
<th class="num">Sample SD</th></tr></thead><tbody>{stats_rows}</tbody></table>
<p class="note">All seven raw inputs are published score fractions. Omniscience accuracy and
non-hallucination are used directly as separate rates, not reconstructed from the combined Index.
If the cohort is too small or any required spread is zero, generation aborts rather than
computing a partial-dimension index.</p>

<h2>Cost per expensive agentic task</h2>
<p>The cost axis is a <strong>separate workload selection</strong> from the science
performance battery. We retain the original technique: read AA's published weighted
per-benchmark cost per task, divide by that benchmark's current Intelligence Index
weight, and average the unweighted costs using task counts.</p>
<p>The four selected workloads are AA-Briefcase v1.1, Terminal-Bench 4.0,
FrontierCode 2.0 and Terminal-Bench-Science 0.1. They are the clear high-cost,
long-running agentic-workload group in the v5 published data. This is a fixed set for
every model, not a model-specific choice of whichever measurements look favorable.</p>
<table><thead><tr><th>Cost workload</th><th class="num">Live II weight</th>
<th class="num">Task count</th></tr></thead><tbody>{cost_rows}</tbody></table>
<div class="math">C<sub>b</sub> = weightedCostPerTask<sub>b</sub> / w<sub>b</sub><br>
C<sub>task</sub> = Σ<sub>b∈cost subset</sub> C<sub>b</sub> T<sub>b</sub>
/ Σ<sub>b∈cost subset</sub> T<sub>b</sub></div>
<p>Today's denominator is {cost_total_tasks:,} tasks across those four workloads.
Task counts and weights are parsed from AA's live methodology table. Repeats are not
multiplied into the task counts: the input is AA's published per-task cost, not the
cost of our rerunning its evaluations.</p>
<p>AA-Omniscience v1.1 and HLE-Diamond have many cheap questions and do not enter the
cost average. GDP.pdf, AutomationBench-AA and CritPt v2 (Hard Subset) are also excluded
from this cost subset because their typical published per-task costs are substantially
lower than the four selected workloads. A benchmark can be included in performance
without being included in cost, and vice versa. GDPval-AA and AA-LCR are no longer
members of the v5 Intelligence Index and supply no cost weights here.</p>
<p>All nine current Intelligence Index cost components, including the excluded cheap
ones, must be present in a cost split and must sum to AA's published total before the
four-workload cost is accepted. Costs are never inferred from token prices, a related
model or another reasoning level. Only {n_cost} of {n_scored} scored models have a
complete positive published cost today; the remainder show — and are excluded from
the log-cost chart and Pareto frontier, not treated as free. Source-zero prices are
also excluded rather than promoted as zero-cost winners. A zero in one published
component is retained if the complete four-workload average is positive. AA’s reported costs retain
its published cache-hit and pricing assumptions; they are not cache-free estimates.</p>

<h2>How this differs from AA's Intelligence Index v5.0</h2>
<p>AA's v5.0 index covers Knowledge Work, Coding, Science and General, at 25% each.
Its weights and task counts, parsed for this run, are shown below. AA-Omniscience's
15% share comprises 10% accuracy and 5% non-hallucination. SoftMinZ uses those two
measured rates as independently standardized components, but does not copy AA’s 2:1
performance weighting: every component enters the normalized partition sum once.</p>
<table><thead><tr><th>AA v5 evaluation</th><th class="num">Live II weight</th>
<th class="num">Task count</th></tr></thead><tbody>{all_weight_rows}</tbody></table>
<p>We use AA's weights only to undo its cost weighting. Our performance index uses
sample z-scores across a strict complete cohort and a nonlinear soft-minimum, rather
than AA's weighted average of normalized evaluation scores. Our narrower battery
emphasizes scientific computing and intentionally omits knowledge-work deliverable
benchmarks such as AA-Briefcase and AutomationBench from performance scoring.</p>

<h2>Reproducibility</h2>
<p class="note">Scraped scores are cross-checked against overlapping scores on each
evaluation page, using JSON-LD score rows when available and the evaluation-page model
payload otherwise. A benchmark whose parsed values disagree is rejected rather than
published; missing comparison data is reported as unavailable, never as validated, and aborts generation.
Intelligence Index weights and task counts used in the cost model are parsed live from
the <a href="{II_METHOD_URL}">AA methodology page</a> on every run (today: {esc(ii_source)});
if that page is unreachable or its table cannot be parsed, the run aborts rather than
publish costs computed from stale weights.
Today's scrape: {esc('; '.join(f'{k}: {v}' for k, v in sorted(report.items())))}.
One script generates this page — see the <a href="{REPO_URL}">repository</a>.</p>

<footer>SoftMinZ daily watch · data ©
<a href="https://artificialanalysis.ai">Artificial Analysis</a> · generated {TODAY} ·
methodology and code in the <a href="{REPO_URL}">repository</a></footer>
</div>
</body>
</html>
"""


def main(max_age_h=12):
    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)

    ii_weights, ii_source = load_ii_benchmarks(DATA, max_age_h=max_age_h)
    print(f'II weights: {ii_source}', file=sys.stderr)
    for slug in sorted(ii_weights):
        w = ii_weights[slug]
        print(f"  {slug:48s} weight={w['weight']:.2f} tasks={w['tasks']}", file=sys.stderr)

    print('Scraping Artificial Analysis...', file=sys.stderr)
    models, report = scrape(max_age_h=max_age_h, ii_weights=ii_weights)
    print(f'{len(models)} models scraped', file=sys.stderr)
    _watch_analyst_agent(models)
    rejected = [k for k, v in report.items()
                if any(status in str(v) for status in ('REJECTED', 'FAILED', 'UNAVAILABLE'))]
    if rejected:
        print('FATAL: rejected/failed/unavailable pages:', ', '.join(rejected), file=sys.stderr)
        raise SystemExit(1)

    ranked, all_rows, zstats = zscore_battery(models)
    print(f'scored (battery-passing): {len(ranked)} of {len(all_rows)}', file=sys.stderr)
    if not ranked or set(zstats) != set(BATTERY):
        print('FATAL: no complete scored cohort/statistics; preserving published artifacts.',
              file=sys.stderr)
        raise SystemExit(1)

    front = pareto(ranked, 'cost_task', 'softminz')
    print(f'pareto frontier: {len(front)} models', file=sys.stderr)

    img = DATA / 'softminz_pareto.png'
    make_chart(ranked, front, img)
    img_b64 = base64.b64encode(img.read_bytes()).decode()
    # Also publish the chart under docs/ so og:image has a real URL to
    # point at when the page link is shared.
    (DOCS / 'softminz_pareto.png').write_bytes(img.read_bytes())

    # docs/CNAME is GitHub's custom-domain binding. The pipeline must preserve
    # it across regenerations or the custom domain silently detaches on the
    # next deploy — write it back if a regeneration ever removes it.
    cname = DOCS / 'CNAME'
    if not cname.exists():
        cname.write_text('softminz.org\n')
        print('restored docs/CNAME (custom-domain binding)', file=sys.stderr)

    page = DOCS / 'index.html'
    page.write_text(build_html(ranked, front, zstats, report, models, img_b64,
                               ii_weights, ii_source))
    print(f'wrote {page} ({page.stat().st_size} bytes)', file=sys.stderr)

    print('\nTOP 10 BY SOFTMINZ:')
    for r in ranked[:10]:
        c = fmt_cost(r.get('cost_task'))
        print(f"  {r['rank']:>3}. {r['name'][:36]:<36} SoftMinZ {r['softminz']:>6}  {c}/task")
    print('\nPARETO FRONTIER (cheapest first):')
    for r in front:
        print(f"  ${r['cost_task']:>7.4f}  SoftMinZ {r['softminz']:>6}  {r['name']}")
    g = next((r for r in ranked if 'gemini-3-1-pro' in r['slug']), None)
    if g:
        print(f"\nGemini 3.1 Pro: rank {g['rank']}, SoftMinZ {g['softminz']}, {fmt_cost(g.get('cost_task'))}/task")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fresh', action='store_true', help='bypass all source caches')
    args = parser.parse_args()
    main(max_age_h=0 if args.fresh else 12)
