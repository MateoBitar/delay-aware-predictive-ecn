# Artifact guide

## Research question

Does queue prediction provide useful ECN/DCTCP advance warning under bursty datacenter traffic, *above and beyond* any benefit obtainable through lower thresholds or a deterministic queue-trend rule? Under which traffic and propagation-delay conditions does the relationship change?

## Experimental matrix

| Campaign | Conditions | Runs |
| --- | --- | ---: |
| Original reference | Six controllers × six paired seeds (224–229) | 36 |
| Original burst-size sensitivity | 50, 100, 150 KB nominal short flows; paired controls/seeds | 72 |
| Original propagation-delay sensitivity | 10, 250, 1,000 µs per link; paired controls/seeds | 72 |
| External CDF-derived workloads | WebSearch: nominal 60%, 80%, 95%; FB_Hadoop: nominal 60%, 95%; six controllers × six seeds (230–235) | 180 |
| **Total** | | **360** |

**Important:** The three original campaign row totals refer to the accepted experimental design, which may include reference/overlapping settings. The external offered-load percentages are **nominal generated payload rates**, not measured link utilization. The external distributions are derived from published workload CDFs, while arrival times are synthetic; do not describe these runs as production traffic replays.

## Software and data inside the release ZIP

The archive includes:

- `simulator/ns-3.47/`: ns-3.47 source, modified ECN/RED controller code and original experimental studies.
- `simulator/external_override/`: external-workload simulator override used for the 180 CDF-derived runs.
- `external_validation/`: external manifests, frozen-run outputs, and scientific analysis.
- `reproduction/`: the portable external-analysis verifier.
- `MANIFEST_SHA256.json`: independent content integrity inventory for 11,010 payload files.
- `README_FIRST.md` and `REPRODUCE.md`: in-archive supporting instructions.

See `ARCHIVE_INVENTORY.md` for a file inventory derived from the specific release ZIP. The inventory's classifications are descriptive, not grounds for deleting scientific outputs or third-party source files.

## Traces and measurements

Primary metrics: mean, P95 and P99 short-flow completion time. Additional measurements include queue occupancy, queueing delay, ECN marking activity, application goodput, and a background-sender fairness proxy. The external analysis uses six paired workload seeds per condition, with exploratory paired 95% bootstrap intervals, **without multiplicity adjustment**. Reported P95/P99 values summarize per-run quantiles; they are not quantiles of pooled raw flows.

## What is verified, and what is not

Verified: archive SHA-256, 360/360 accepted simulator run configurations, 5,148 raw trace file matches, 4,320 validated run-level metric matches and four external scientific CSVs reproduced exactly. Both original and external simulator variants were built from archive sources in an isolated workspace.

Not verified by this campaign: retraining the frozen ML models; a fresh third-party independent-host replication; compatibility with every current compiler or OS; that the predictive ML controller consistently dominates the simpler fixed-threshold or trend baselines. Any publication must interpret findings and uncertainty from the accepted scientific tables, not from the reproducibility count alone.

## Archive preservation

The v1.0.0 ZIP is the immutable reference for the verified experiment set. Documentation improvements in the Git repository do not change any file inside the ZIP or the original SHA-256. If future experiments or fixes change scientific outputs, issue a **new** separately verified version and document the differences instead of silently replacing the existing release.
