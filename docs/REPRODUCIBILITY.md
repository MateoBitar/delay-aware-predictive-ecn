# Reproducing the experiments

## Tested environment and requirements

The successful independent-workspace verification used Ubuntu under WSL2 (`x86_64`, Linux 6.18.33.2-microsoft-standard-WSL2) with Python 3.14.4 and NumPy 2.3.5. The simulator requires CMake, Ninja and a C++ compiler. At least **30 GiB available disk space** is checked by the orchestrator; more may be prudent. A recorded run took about **1,452 seconds (~24 minutes)** on the authors' system; performance and cross-host hash identity are not guaranteed.

On Ubuntu, a starting point for dependencies is:

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build python3 python3-numpy
```

If your Python environment does not expose NumPy, use a compatible environment containing NumPy and launch the script using that interpreter. Avoid modifying the accepted archive to install dependencies.

## Obtain and authenticate the archive

1. Clone this repository.
2. Download the `.zip` from [release v1.0.0](https://github.com/MateoBitar/delay-aware-predictive-ecn/releases/tag/v1.0.0).
3. Store the ZIP **outside** the Git working tree.
4. Verify:

```bash
sha256sum /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip
```

Expected SHA-256:

```text
b26bfb7bcb26702ef88a6d29e3515e48d188988e31db7ad8edd243712304194c
```

## Full verified replay

```bash
python3 reproduce_full_research_FIXED.py \
  --zip /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip \
  --workspace "$HOME/ecn-independent-reproduction" \
  --jobs 1
```

The script validates its working area, ZIP digest, and embedded SHA-256 manifest; prevalidates recorded configurations, model digests, and external input manifests; compiles **two** optimized simulator implementations (original and external); runs **360** paired configurations; compares every archived raw trace and twelve accepted scientific metric fields per run; and independently regenerates four external-analysis CSVs.

It writes a final JSON report to the workspace only when every check passes. A valid completion includes:

```text
SUCCESS: FULL 360-EXPERIMENT REPRODUCTION PASSED
Original accepted runs reproduced: 180/180
External accepted runs reproduced: 180/180
Preserved raw traces matched: 5148
Accepted per-run metric fields matched: 4320
Regenerated external scientific CSVs: 4/4 exact SHA-256
```

Do not equate a partial or interrupted run with full success. The orchestrator can resume a **marked and validated** existing workspace, and refuses to overwrite an incomplete individual run silently. `--max-cases 1` performs a diagnostic one-case test and deliberately does not claim full completion.

## Validation report and published study

The archived `FINAL_REPRODUCTION_REPORT.json` describes one successful local reproduction with the expected exact counts. Its record is evidence for those checks, not a full substitute for independently interpreting the controller comparison tables and confidence intervals. Historical experiment design, raw results, and analysis programs are in the ZIP. The package's `README_FIRST.md` and `REPRODUCE.md` provide additional study-specific instructions.

## Limitations and scope

- Model **training is not rerun**; accepted pretrained models are held fixed.
- External workloads are **CDF-derived synthetic traffic**, not packet-level replay of real production traces.
- Original delay sensitivity changes physical propagation delay, **not a separately controlled ECN reaction-time delay**.
- Exact trace and metric equality was established locally on the tested WSL2 host, not yet on a second researcher's computer.
- Six paired seeds per external condition yield limited uncertainty precision; exploratory intervals are not multiple-comparison adjusted.
- Application goodput and fairness definitions are workload- and measurement-window-dependent. Do not equate nominal offered load with observed bottleneck utilization.
- The ZIP may include third-party software with its own licenses. No blanket license is asserted for redistributed components.

## Troubleshooting

- **`NumPy not installed`:** use a Python interpreter with NumPy installed.
- **`Missing required tool`:** install `cmake`, `ninja`, or `g++` as directed.
- **`ZIP checksum mismatch`:** confirm the exact v1.0.0 asset, not an older ZIP.
- **`Existing workspace ... refused`:** choose a new empty workspace path rather than overwriting a scientific workspace.
- **OOM / WSL session exit:** use `--jobs 1` and inspect your OS/WSL memory limits. The `--jobs` setting only controls Ninja compilation parallelism.
- **Trace mismatch:** preserve the failure logs; do not alter archived traces or bypass validation to obtain a PASS.
