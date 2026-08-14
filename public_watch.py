#!/usr/bin/env python3
"""SoftMinZ public model-value watch — one script, one webpage.

Scrapes Artificial Analysis (free, no key), z-scores a fixed 9-benchmark
battery chosen for scientific-computing relevance, computes the SoftMinZ
index (a coverage-normalised soft-minimum of the z-scores), prices each
model with an agentic-workload cost per task derived from raw AA cost
data, draws the SoftMinZ-vs-cost Pareto frontier, and emits a single
self-contained docs/index.html for GitHub Pages.

No vendor discounts, no portal pricing, no free tiers: raw cost data only.

SOFTMINZ
--------
Every battery benchmark is z-scored across all models measured on it.
SoftMinZ is the negative natural log of the mean of e^{-z}:

    SoftMinZ = -ln[ (1/n) * sum_b exp(-z_b) ]

a smooth soft-minimum of the z-scores: min(z) <= SoftMinZ <= mean(z),
with SoftMinZ ~= mean(z) - Var(z)/2 to leading order. Balanced profiles
are rewarded; lopsided ones are discounted. The 1/n normalisation keeps
the score from inflating with coverage — how many benchmarks a model was
measured on does not affect the value.

COST PER TASK
-------------
Artificial Analysis publishes a per-benchmark "weighted cost per task"
for the benchmarks in its Intelligence Index. We divide each weighted
cost by the benchmark's Intelligence Index weight to recover the
unweighted cost, then average over the four benchmarks that represent
real agentic workflow spend (GDPval-AA v2, tau3-Banking, Terminal-Bench
v2.1, AA-LCR), weighted by task count:

    C_task = sum_i C_i * T_i / sum_i T_i
"""
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

# ---------------------------------------------------------------------------
# The scoring battery: nine benchmarks, chosen for relevance to scientific
# computing. tau3-banking is deliberately NOT scored (see webpage text).
# ---------------------------------------------------------------------------
MATHSCI = ['gpqa', 'critpt', 'hle', 'omniscience']            # science & knowledge
CODESCI = ['scicode', 'livecodebench', 'terminalbench_hard']  # code & agents
TRUST = 'non_hallucination_rate'
LONGCTX = 'lcr'
BATTERY = MATHSCI + CODESCI + [TRUST, LONGCTX]
COVERAGE_FLOOR = 7
MANDATORY = {'critpt', 'non_hallucination_rate'}

BENCH_LABEL = {
    'gpqa': 'GPQA Diamond', 'hle': "Humanity's Last Exam",
    'critpt': 'CritPt', 'omniscience': 'AA-Omniscience',
    'scicode': 'SciCode', 'livecodebench': 'LiveCodeBench',
    'terminalbench_hard': 'Terminal-Bench Hard',
    'lcr': 'AA-LCR (long-context reasoning)',
    'non_hallucination_rate': 'Non-hallucination rate',
}
# Evaluation-page links used for inline citations on the webpage.
BENCH_URL = {
    'gpqa': 'https://artificialanalysis.ai/evaluations/gpqa-diamond',
    'hle': 'https://artificialanalysis.ai/evaluations/humanitys-last-exam',
    'critpt': 'https://artificialanalysis.ai/evaluations/critpt',
    'omniscience': 'https://artificialanalysis.ai/evaluations/omniscience',
    'scicode': 'https://artificialanalysis.ai/evaluations/scicode',
    'livecodebench': 'https://artificialanalysis.ai/evaluations/livecodebench',
    'terminalbench_hard': 'https://artificialanalysis.ai/evaluations/terminalbench-hard',
    'lcr': 'https://artificialanalysis.ai/evaluations/artificial-analysis-long-context-reasoning',
}

# AA evaluations pages to scrape: page slug -> (payload field, JSON-LD label, display)
PAGES = {
    'gpqa-diamond':   ('gpqa', 'GPQA Diamond'),
    'humanitys-last-exam': ('hle', "Humanity's Last Exam"),
    'scicode':        ('scicode', 'SciCode'),
    'critpt':         ('critpt', 'CritPt'),
    'livecodebench':  ('livecodebench', 'LiveCodeBench'),
    'terminalbench-hard': ('terminalbench_hard', 'Terminal-Bench Hard'),
    'omniscience':    ('omniscience', 'Omniscience Index'),
    'artificial-analysis-long-context-reasoning': ('lcr', 'AA-LCR'),
    'artificial-analysis-intelligence-index': ('intelligence_index_v4_1', 'Intelligence Index'),
}

# Intelligence Index weights and task counts are loaded LIVE from AA's
# methodology page on EVERY run (load_ii_benchmarks below). There is NO
# hardcoded fallback: if the page is unreachable or its table cannot be
# parsed, the run dies rather than publish costs computed from stale weights.
#
# Which benchmarks represent agentic workflow cost (II_COST_SLUGS) is an
# IDENTITY choice, not a weight, so it is pinned here and does not drift
# when AA revises the methodology.
II_COST_SLUGS = {'gdpval-aa', 'tau3-banking', 'terminalbench-v2-1',
                 'artificial-analysis-long-context-reasoning'}

II_TABLE_NAMES = {
    'GDPval-AA v2': 'gdpval-aa', '𝜏³-Banking': 'tau3-banking',
    'Terminal-Bench v2.1': 'terminalbench-v2-1', 'SciCode': 'scicode',
    "HLE (Humanity's Last Exam)": 'humanitys-last-exam',
    'GPQA Diamond': 'gpqa-diamond', 'CritPt': 'critpt',
    'AA-Omniscience': 'omniscience',
    'AA-LCR': 'artificial-analysis-long-context-reasoning',
}


# ---------------------------------------------------------------------------
# Scraping helpers (AA publishes per-model records inside Next.js flight
# payloads; each model is one nested JSON object, so fields can never leak
# between models. Every score is cross-validated against the page's JSON-LD
# Score block before being accepted.)
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

    Objects are found by brace-matching outward from each "short_name"
    anchor until one parses as a dict containing 'slug' and 'short_name'.
    Deserialising the whole record makes cross-model field leakage
    structurally impossible.
    """
    out = {}
    for m in re.finditer(r'"short_name":"', payload):
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
            if (isinstance(obj, dict) and 'slug' in obj and 'short_name' in obj
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


def scrape(max_age_h=12, ii_weights=None):
    models = collections.defaultdict(dict)
    report = {}
    if not ii_weights:
        raise ValueError('ii_weights is required — call load_ii_benchmarks() first')
    cost_benchmarks = {k: v for k, v in ii_weights.items() if k in II_COST_SLUGS}
    cost_total_tasks = sum(b['tasks'] for b in cost_benchmarks.values())
    for slug, (field, label) in PAGES.items():
        try:
            raw = fetch(BASE + slug, DATA / f'{slug}.html', max_age_h)
            payload = flight(raw)
            records = extract_records(payload)

            vals = {}
            for s, rec in records.items():
                v = rec.get(field)
                if isinstance(v, (int, float)):
                    # Prefer the full AA name: it distinguishes variants
                    # (Reasoning / Non-reasoning, effort levels) that share a
                    # short_name, so table labels stay unambiguous.
                    vals[s] = (float(v), rec.get('name') or rec.get('short_name') or s)

            truth = jsonld_scores(raw, label)
            checked = bad = 0
            for s, exp in truth.items():
                got = vals.get(s, (None,))[0]
                if got is None:
                    continue
                checked += 1
                if abs(got - exp) > 1e-6:
                    bad += 1
            if checked and bad:
                report[slug] = f'REJECTED ({bad}/{checked} mismatched vs JSON-LD)'
                continue
            for s, (v, nm) in vals.items():
                models[s][field] = v
                models[s].setdefault('name', nm)
            report[slug] = f'{len(vals)} models (validated {checked})'

            # extras from the omniscience page: hallucination + prices
            if slug == 'omniscience':
                n = 0
                for s, rec in records.items():
                    ob = rec.get('omniscience_breakdown')
                    if isinstance(ob, dict):
                        nhr = (ob.get('total') or {}).get('non_hallucination_rate')
                        if isinstance(nhr, (int, float)):
                            models[s].setdefault('non_hallucination_rate', float(nhr))
                            n += 1
                report['non-hallucination rate'] = f'{n} models'

            # per-benchmark weighted cost breakdown (Intelligence Index page)
            if slug == 'artificial-analysis-intelligence-index':
                n = 0
                for s, rec in records.items():
                    iic = rec.get('intelligenceIndexCostPerTask')
                    if not isinstance(iic, dict):
                        continue
                    evals = iic.get('evaluations')
                    if not (isinstance(evals, list) and evals):
                        continue
                    weighted = {item['slug']: item['weightedCostPerTask']
                                for item in evals
                                if isinstance(item, dict) and 'slug' in item}
                    total = 0.0
                    for bslug, wc in weighted.items():
                        info = cost_benchmarks.get(bslug)
                        if info:
                            total += (wc / info['weight']) * info['tasks']
                    if total > 0:
                        models[s].setdefault('cost_task', total / cost_total_tasks)
                        n += 1
                report['agentic cost per task'] = f'{n} models'
        except Exception as e:
            report[slug] = f'FAILED: {e}'
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
        m = re.search(r'^(\d{1,3}(?:,\d{3})*|\d+)', texts[eval_idx + 1])
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
    missing = set(II_COST_SLUGS) - set(parsed)
    if missing or not parsed or any(v['weight'] <= 0 for v in parsed.values()):
        print(f'FATAL: AA methodology table unparseable or incomplete '
              f'(missing: {sorted(missing) or "none"}; parsed {len(parsed)} rows). '
              f'Refusing to publish costs from stale weights.', file=sys.stderr)
        sys.exit(1)
    return parsed, 'live (AA methodology page, parsed this run)'


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def zscore_battery(models):
    """z-score every battery benchmark across all models measured on it,
    apply the coverage/mandatory gates, compute SoftMinZ. Returns rows."""
    rows = []
    for slug, d in models.items():
        r = {'slug': slug, 'name': d.get('name', slug)}
        for f in BATTERY:
            r[f] = d.get(f)
        r['cost_task'] = d.get('cost_task')
        r['ii'] = d.get('intelligence_index_v4_1')
        rows.append(r)

    zstats = {}
    for f in BATTERY:
        vals = [r[f] for r in rows if r.get(f) is not None]
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
            if r.get(f) is not None and f in zstats:
                r['zscores'][f] = (r[f] - zstats[f][0]) / zstats[f][1]
        r['battery_ok'] = (all(r.get(m) is not None for m in MANDATORY)
                           and len(r['zscores']) >= COVERAGE_FLOOR)
        if r['battery_ok']:
            zs = list(r['zscores'].values())
            r['softminz'] = round(-math.log(sum(math.exp(-z) for z in zs) / len(zs)), 2)
        else:
            r['softminz'] = None

    ranked = sorted([r for r in rows if r['battery_ok']],
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
    ax.set_ylabel('SoftMinZ = −ln⟨e$^{−z}$⟩ (soft-min of battery z-scores)')
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

    # Dynamic GPT-5.6 hallucination paragraph, from this run's numbers.
    nhr_all = [v['non_hallucination_rate'] for v in models.values()
               if isinstance(v.get('non_hallucination_rate'), (int, float))]
    mu = statistics.mean(nhr_all)
    sd = statistics.pstdev(nhr_all)
    gpt = [r for r in ranked if 'gpt-5-6' in r['slug']]
    gpt_nhr = [r['non_hallucination_rate'] for r in gpt]
    gpt_best = max(gpt, key=lambda r: r['softminz']) if gpt else None
    gpt_nhr_med = statistics.median(gpt_nhr) if gpt_nhr else None
    gpt_z = (gpt_nhr_med - mu) / sd if gpt_nhr_med is not None else None
    best_rank = gpt_best['rank'] if gpt_best else None
    # Top-of-table NHR range, computed fresh each run. Ranked models are all
    # mandated to carry a non-hallucination measurement, so the top 5 always
    # have one.
    top5_nhr = [r['non_hallucination_rate'] * 100 for r in ranked[:5]]
    top_lo, top_hi = round(min(top5_nhr)), round(max(top5_nhr))
    gpt_par = (
        f'Across the {len(gpt)} GPT-5.6 variants scored today, the median non-hallucination '
        f'rate is {(gpt_nhr_med * 100):.1f}% against a field mean of {(mu * 100):.1f}% '
        f'(population σ = {(sd * 100):.1f} points) — a z-score of roughly {gpt_z:.2f} on the '
        f'trust benchmark alone. Top-ranked models sit far higher: the five best in the '
        f'table carry non-hallucination rates of {top_lo}–{top_hi}%. Because SoftMinZ is a '
        f'soft-<em>minimum</em>, that weak trust score receives the largest Boltzmann '
        f'weight in the average and drags every GPT-5.6 variant down even where GPQA, HLE '
        f'and SciCode are strong — the best-placed variant ranks #{best_rank} of '
        f'{n_scored}.'
    ) if gpt_best else ''
    gpt_section = (
        f'<h3>Why the GPT-5.6 lineup scores below its reputation</h3>\n<p>{gpt_par}</p>'
        if gpt_par else ''
    )

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
<p>Nine public benchmarks are scored per model. Each benchmark score is first converted to a
z-score across every model measured on that benchmark, so all benchmarks
contribute in comparable units regardless of their raw scale:</p>
<div class="math">z<sub>b</sub> = (x<sub>b</sub> − μ<sub>b</sub>) / σ<sub>b</sub>
&nbsp;&nbsp;(μ<sub>b</sub>, σ<sub>b</sub> are the mean and sample standard deviation
across all measured models)</div>
<p>The index is then the negative natural logarithm of the mean of e<sup>−z</sup> over the
model's benchmarks:</p>
<div class="math">SoftMinZ = −ln [ (1/n) · Σ<sub>b</sub> exp(−z<sub>b</sub>) ]</div>
<p>This is a smooth <strong>soft-minimum</strong> of the z-scores: it always sits between
the model's worst z-score and its mean z-score, and it slides toward the worst end as
the profile becomes more uneven. The practical consequences:</p>
<ul>
<li><strong>A weak benchmark cannot be averaged away.</strong> The exponential weights
e<sup>−z</sup> concentrate on the model's <em>worst</em> results. The discount is not
cosmetic: a model with eight benchmarks at z&nbsp;=&nbsp;+1.5 and one at z&nbsp;=&nbsp;−0.8
scores 0.81 — below a model that is merely even at z&nbsp;=&nbsp;+1.0 everywhere, despite
the first model's higher mean (1.24 vs 1.0), because the soft-minimum punishes the
imbalance by more than the mean gap.</li>
<li><strong>Balanced excellence is rewarded; lopsided excellence is discounted.</strong></li>
<li><strong>Coverage does not inflate the score.</strong> The 1/n normalisation divides by
the number of benchmarks actually measured: being measured on more benchmarks moves the score
only through the quality of the new result, never through the count itself.</li>
</ul>
<p>A model is excluded from scoring entirely (no index, rather than a low one) if it is
measured on fewer than 7 of the 9 battery benchmarks, or if either of two mandatory
measurements is missing: <strong>CritPt</strong> (physics) and the <strong>non-hallucination
rate</strong>. A model with no physics evaluation or no hallucination measurement is simply
not evaluated here.</p>

<h3>Why these nine benchmarks</h3>
<p>The performance battery is chosen for <strong>relevance to scientific computing</strong>:
science-adjacent reasoning and knowledge (<a href="{BENCH_URL['gpqa']}">GPQA Diamond</a>,
<a href="{BENCH_URL['critpt']}">CritPt</a>,
<a href="{BENCH_URL['hle']}">Humanity's Last Exam</a>,
<a href="{BENCH_URL['omniscience']}">AA-Omniscience</a>), the code-execution skills real
computational work depends on (<a href="{BENCH_URL['scicode']}">SciCode</a>,
<a href="{BENCH_URL['livecodebench']}">LiveCodeBench</a>,
<a href="{BENCH_URL['terminalbench_hard']}">Terminal-Bench Hard</a>), and the trust
dimensions that decide whether a model's output can be believed without full
re-verification (non-hallucination rate,
<a href="{BENCH_URL['lcr']}">AA-LCR</a> long-context reasoning).</p>
<p><strong><a href="https://artificialanalysis.ai/evaluations/tau3-banking">τ³-Banking</a>
is excluded from the performance calculation</strong> because it
simulates fintech customer support — a domain-specific agent task whose skill profile says
nothing about scientific capability. (It does remain in the cost calculation below, where it
represents real agentic workflow spend.)
<strong><a href="https://artificialanalysis.ai/evaluations/gdpval-aa">GDPval-AA v2</a>
is likewise excluded:</strong>
its tasks are real-world professional deliverables (analyst memos, marketing plans and the
like), not scientific computing, so it has no place in a performance battery for science
either — though it too remains in the cost model as agentic workload.</p>

<h2>How the cost is computed</h2>
<p>The cost benchmarks are chosen for <strong>relevance to agentic workflow costs</strong>.
Artificial Analysis publishes, for each benchmark in its
Intelligence Index, a <em>weighted</em> cost per task. Dividing that by the benchmark's
Intelligence Index weight recovers the unweighted per-benchmark cost C<sub>i</sub>; the four
benchmarks that represent agentic workload — GDPval-AA v2, τ³-Banking, Terminal-Bench v2.1
and AA-LCR — are then averaged weighted by task count:</p>
<div class="math">C<sub>task</sub> = Σ<sub>i</sub> C<sub>i</sub> T<sub>i</sub> / Σ<sub>i</sub> T<sub>i</sub></div>
<p>Cheap high-volume knowledge benchmarks (AA-Omniscience, HLE, GPQA Diamond, CritPt,
SciCode) are excluded from the cost average because they would otherwise dominate the task
count while representing almost no real agentic spend. The result is a raw USD figure per
agentic task — list prices only, no discounts. A handful of open-weight models are served
by free hosting endpoints and report a $0 cost to AA; they are excluded from the cost axis
(and the frontier) rather than treated as genuinely free products, but remain scored and
ranked in the table.</p>

<h2>The Artificial Analysis Intelligence Index, and why we don't use it</h2>
<p>Artificial Analysis' own headline metric, the
<a href="{II_METHOD_URL}">Intelligence Index v4.1.1</a>, is a plain weighted average of
normalised benchmark scores:</p>
<div class="math">II = Σ<sub>b</sub> w<sub>b</sub> · s<sub>b</sub></div>
<p>with category weights Agents 34%, Coding 24%, Scientific Reasoning 24%, General 18%,
and per-benchmark weights GDPval-AA v2 20%, τ³-Banking 14%, Terminal-Bench v2.1 16%,
SciCode 8%, HLE 12%, GPQA Diamond 6%, CritPt 6%, AA-Omniscience 12% (itself split: 8%
accuracy + 4% non-hallucination) and AA-LCR 6%. GDPval-AA v2 Elo scores are folded in as
clamp((Elo − 500) / 2000). (Formula per the
<a href="{II_METHOD_URL}">AA methodology page</a>.)</p>
<p>It is a useful headline, but for scientific work it has real flaws:</p>
<ul>
<li><strong>A linear average hides weakness.</strong> A model that is excellent on agentic
benchmarks but hallucinates heavily still posts a high II, because one strong benchmark
linearly cancels one weak one. For science, a hallucinated citation or a confidently wrong
intermediate result can invalidate the whole task — the failure mode a soft-minimum
punishes and an average does not.</li>
<li><strong>Hallucination is nearly an afterthought.</strong> Non-hallucination carries only
4% of the total weight inside AA-Omniscience's 12% share. Here it is a mandatory benchmark
and a dominant term whenever it is bad.</li>
<li><strong>The weighting emphasises generalist agentic work, not science.</strong> 34%
Agents includes τ³-Banking (14%), a fintech customer-support simulation — a large weight on
a skill orthogonal to scientific capability.</li>
<li><strong>Ad hoc normalisations.</strong> The GDPval clamp((Elo − 500)/2000) mapping and
the frozen Elo reference points are parameters AA itself may adjust over time, so index
values are not perfectly comparable across model vintages.</li>
</ul>

{gpt_section}

<h2>Reproducibility</h2>
<p class="note">Every scraped score is cross-validated against the JSON-LD metadata on its
source page; a benchmark whose parsed values disagree is rejected rather than published.
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


def main():
    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)

    ii_weights, ii_source = load_ii_benchmarks(DATA)
    print(f'II weights: {ii_source}', file=sys.stderr)
    for slug in sorted(ii_weights):
        w = ii_weights[slug]
        print(f"  {slug:48s} weight={w['weight']:.2f} tasks={w['tasks']}", file=sys.stderr)

    print('Scraping Artificial Analysis...', file=sys.stderr)
    models, report = scrape(ii_weights=ii_weights)
    print(f'{len(models)} models scraped', file=sys.stderr)
    rejected = [k for k, v in report.items() if 'REJECTED' in str(v) or 'FAILED' in str(v)]
    if rejected:
        print('WARNING: rejected/failed pages:', ', '.join(rejected), file=sys.stderr)

    ranked, all_rows, zstats = zscore_battery(models)
    print(f'scored (battery-passing): {len(ranked)} of {len(all_rows)}', file=sys.stderr)

    front = pareto(ranked, 'cost_task', 'softminz')
    print(f'pareto frontier: {len(front)} models', file=sys.stderr)

    img = DATA / 'softminz_pareto.png'
    make_chart(ranked, front, img)
    img_b64 = base64.b64encode(img.read_bytes()).decode()

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
    main()
