# LLM Index for Scientific Computing

Softminz ranks models by **SoftMinZ**, a soft-minimum of standardized benchmark
scores, against **cost per expensive agentic task**. This version follows the
Artificial Analysis Intelligence Index **v5.0** transition (2026-10-28).

## Performance: seven z-components from six benchmarks

1. [Terminal-Bench 4.0](https://artificialanalysis.ai/evaluations/terminalbench-v4-0)
2. [FrontierCode 2.0](https://artificialanalysis.ai/evaluations/frontiercode-2-0)
3. [AA-Omniscience v1.1](https://artificialanalysis.ai/evaluations/omniscience):
   **accuracy** and **non-hallucination rate**, two separate components
4. [HLE-Diamond](https://artificialanalysis.ai/evaluations/hle-diamond)
5. [CritPt v2 (Hard Subset)](https://artificialanalysis.ai/evaluations/critpt)
6. [Terminal-Bench-Science 0.1](https://artificialanalysis.ai/evaluations/terminal-bench-science)

AA-Omniscience v1.1 contributes its measured **accuracy** and
**non-hallucination rate** (1 minus AA’s hallucination rate). Each has its own mean,
sample standard deviation and z-score. The combined Omniscience Index is **not**
an additional input. Five other benchmarks plus these two rates give **seven
components**, all required for a model to score.

A model must have a finite score on **all seven** components to be ranked or contribute
to **any** normalization pool. Every component is z-scored across the same complete
cohort, using the sample standard deviation (n − 1). Then:

```text
z_b = (score_b − cohort_mean_b) / cohort_sample_SD_b
Z = Σ_(i=1…7) exp(−z_i)
SoftMinZ = −ln(Z / 7)
```

Each component contributes one Boltzmann factor to the partition sum; dividing
by seven takes their **mean** before the negative logarithm. This is **not a
linear weighted average of z-scores**. Its local influence is
∂SoftMinZ/∂z_i = exp(−z_i)/Z, so weak dimensions exert more influence.
AA’s 10% accuracy / 5% non-hallucination weighting is not copied into performance.
SoftMinZ lies between a model’s worst and mean z-score; it rewards balanced
performance and discounts weakness. Partial profiles are excluded, never imputed.
Tiny cohorts or zero-variance required dimensions abort before output replacement.

This replaces the previous battery: original HLE, original CritPt, SciCode, AA-LCR
are no longer used. The current v1.1 non-hallucination rate is explicitly included. Older versions
(FrontierCode 1.x, AA-Omniscience v1, original HLE/CritPt) and full CritPt v2 cannot
fill missing measurements for the named versions or hard subset. **The new scores and ranks are not directly comparable with the old battery
or the initial six-component v5 version that used the combined Omniscience Index.** AnalystAgent remains
watch-only, never silently added to the seven-component score.

## Cost: expensive workloads, same formula

Cost is a separate subset, fixed across models:

| Workload | v5 II weight* | Tasks* |
|---|---:|---:|
| AA-Briefcase v1.1 | 15% | 91 |
| Terminal-Bench 4.0 | 10% | 66 |
| FrontierCode 2.0 | 15% | 132 |
| Terminal-Bench-Science 0.1 | 15% | 70 |

*Current values from the [AA methodology table](https://artificialanalysis.ai/methodology/intelligence-benchmarking),
not runtime fallbacks. The generator parses weights and task counts for each run.
Today the four workloads total **359 tasks**.

These are the clear high-cost, long-running agentic workloads in the published v5
data. AA-Omniscience and HLE-Diamond have large numbers of cheap questions and are
excluded from this cost average. GDP.pdf, AutomationBench-AA and CritPt v2 (Hard
Subset) also have substantially lower typical per-task costs and are excluded.
Performance membership and cost membership are intentionally independent.
GDPval-AA and AA-LCR have left the v5 Intelligence Index, so their old weights are
not reused.

Retain the original cost calculation, using only AA’s published per-benchmark data:

```text
C_b = weightedCostPerTask_b / live_II_weight_b
C_task = Σ_b(C_b × task_count_b) / Σ_b(task_count_b)
         b ranges over the same four expensive workloads for every model
```

Task counts, **not II weights**, weight the final workload average. Repeats are not
multiplied into task counts: the inputs are already AA’s reported per-task costs.
No costs are inferred from token prices, another model, another reasoning level,
free tiers or added vendor discounts. AA’s published cache-hit and pricing
assumptions are retained; these are not cache-free estimates.

All **nine current v5 cost components**, including excluded cheap evaluations, must
be present and sum to the model’s published aggregate cost before its four-workload
price is accepted. A missing/invalid/nonpositive complete price is shown as **—**,
not zero. This positivity check applies to the complete four-workload average;
a literal zero in an individual published component is retained if that average
is positive. Unpriced models can still be performance-ranked but do not enter the
log-cost plot or Pareto frontier. The generated page reports actual priced coverage.

## Sources, checks and output

- Primary score data: [AA model leaderboard](https://artificialanalysis.ai/leaderboards/models)
  (nested slug-keyed scores; exact version-specific flat fields on evaluation pages).
- Each battery field and the headline Intelligence Index are checked against
  overlapping evaluation-page values, using JSON-LD or the page’s own payload.
  Mismatches, failed checks and unavailable required comparisons abort generation.
- Weights/task counts must match the current v5 methodology schema, be positive,
  and have weights summing to one. No stale-weight fallback.
- Preserve `docs/CNAME` (`softminz.org`). Publish one self-contained HTML page with
  embedded chart and two ranking views, plus an identical PNG for social previews.

## Run and test

Requires Python 3.10+ and matplotlib. No AA API key.

```bash
TZ=UTC python3 public_watch.py --fresh
python3 -m unittest -v test_public_watch
```

`--fresh` bypasses every source cache. Without it, the scrape cache in `data/` has
a maximum age of 12 hours. Outputs are `docs/index.html`,
`docs/softminz_pareto.png` and `data/softminz_pareto.png`.

## Publishing

The existing [brendangerardlucas/softminz](https://github.com/brendangerardlucas/softminz)
repository publishes GitHub Pages from `main:/docs` at <https://softminz.org/>.
Review only intended changes, pass tests/source/cost/artifact checks, push normally,
and verify the deployment at the exact pushed SHA plus the live page/chart/toggles.
A successful push alone is not deployment verification.

## License

MIT. Benchmark data © Artificial Analysis.
