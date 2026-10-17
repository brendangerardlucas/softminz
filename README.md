# LLM Index for Scientific Computing

A daily, fully automated watch that ranks frontier LLMs by **SoftMinZ** — a
soft-minimum performance index over a seven-benchmark battery chosen for
relevance to **scientific computing** — against **raw cost per agentic task**.

The output is a single self-contained webpage, published via GitHub Pages:
one Pareto chart and one ranked table. Everything else on the page is
methodology.

## What it does

1. **Scrapes [Artificial Analysis](https://artificialanalysis.ai)** — free, no
   API key. Overlapping scores are cross-checked against each evaluation
   page's JSON-LD score rows, or its model payload when those rows are absent.
   Mismatched benchmarks are rejected; unavailable checks are reported.
   Intelligence Index weights used by the cost model are verified
   against AA's methodology page on every run.
2. **Z-scores** each battery benchmark across the same strictly complete cohort.
   Models missing any battery benchmark neither receive a score nor affect the z-score pools.
3. **SoftMinZ**:

   ```
   SoftMinZ = −ln [ (1/n) · Σ_b exp(−z_b) ]
   ```

   A coverage-normalised soft-minimum of the z-scores. It always lies between
   the model's worst and mean z-score, and ≈ mean z − ½Var(z) to leading
   order: balanced excellence is rewarded, lopsided excellence is discounted,
   and a weak trust measurement cannot be bought off by strong quiz scores.
4. **Cost per agentic task** from raw AA cost data only (no discounts, no
   free tiers, no portal pricing): the Intelligence Index weighted costs are
   de-weighted and averaged over five agentic-workload benchmarks
   (GDPval-AA, AutomationBench-AA, Terminal-Bench v4.0, AA-LCR, AA-Briefcase),
   weighted by task count using the live AA methodology table.
5. **Emits `docs/index.html`** — chart, the full ranking in two toggleable
   views (by SoftMinZ and by cost), and the methodology — as one file with
   no external assets.

## Battery

Scored (7): CritPt, Humanity's Last Exam, AA-Omniscience, SciCode,
Terminal-Bench v4.0, non-hallucination rate, and AA-LCR.

A model must be measured on **every** battery benchmark to be scored or
contribute to the z-score pools. Z-scores use sample standard deviations.
AutomationBench-AA and AA-Briefcase are cost-only; AnalystAgent is watch-only.
GPQA Diamond, LiveCodeBench, τ³-Banking and Terminal-Bench v2.1 are no longer
part of either axis.

## Run it

```bash
python3 public_watch.py
```

Dependencies: Python 3.10+, matplotlib. Output: `docs/index.html`.
A scrape cache (`data/`) makes reruns within 12 hours instant.

## Publishing to GitHub Pages

Push the repo to GitHub, then in repo Settings → Pages choose "Deploy from a
branch", branch `main`, folder `/docs`. The page updates on every push.

## License

MIT. Benchmark data © Artificial Analysis.
