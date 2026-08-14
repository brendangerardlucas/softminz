# LLM Index for Scientific Computing

A daily, fully automated watch that ranks frontier LLMs by **SoftMinZ** — a
soft-minimum performance index over a nine-benchmark battery chosen for
relevance to **scientific computing** — against **raw cost per agentic task**.

The output is a single self-contained webpage, published via GitHub Pages:
one Pareto chart and one ranked table. Everything else on the page is
methodology.

## What it does

1. **Scrapes [Artificial Analysis](https://artificialanalysis.ai)** — free, no
   API key. Every score is cross-validated against the page's JSON-LD
   metadata; benchmarks whose parsed values disagree are rejected, not
   published. Intelligence Index weights used by the cost model are verified
   against AA's methodology page on every run.
2. **Z-scores** each battery benchmark across all measured models.
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
   de-weighted and averaged over the four agentic-workload benchmarks
   (GDPval-AA v2, τ³-Banking, Terminal-Bench v2.1, AA-LCR), weighted by task
   count.
5. **Emits `docs/index.html`** — chart, the full ranking in two toggleable
   views (by SoftMinZ and by cost), and the methodology — as one file with
   no external assets.

## Battery

Scored (9): GPQA Diamond, CritPt, Humanity's Last Exam, AA-Omniscience,
SciCode, LiveCodeBench, Terminal-Bench Hard, non-hallucination rate, AA-LCR.

Excluded from scoring: **τ³-Banking** (fintech customer support is not
scientific capability), though it remains in the cost model as an agentic
workload.

Exclusion gates: a model must be measured on ≥ 7 of 9 benchmarks and must
have both CritPt and non-hallucination rate, or it is not scored at all.

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
