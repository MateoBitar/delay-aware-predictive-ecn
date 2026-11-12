# Run from clean ns-3.47 source (code-first pathway)

This is the conventional, **code-first** entry point for the published research.
It does **not** require the 1.22 GB reference ZIP or the 541 MB 7z archive
to build and execute one of the **recorded original or external experiments**.

**Scope and evidence (2026-11-12):** This path uses the exact research
C++ source, frozen predictor models and recorded `command.json` settings
published in GitHub. The automated offline contract checks pass. On the authors'
local Ubuntu/WSL2 host, both original and external ns-3.47 variants were built
from clean upstream source and executed successfully:

- **Original:** seed 224, `baseline`, 24 completed-flow records and 19 output
  files. This is a successful smoke run; no separate raw-hash comparison has
  yet been reported for this source-based case.
- **External:** WebSearch CDF-derived workload, nominal 60% offered load,
  seed 230, `baseline`, 240 completed-flow records and 19 output files.
  A separate read-only comparison against the archived accepted reference
  showed **19/19 exact raw-trace SHA-256 matches** and **12/12 accepted
  metric-field matches**, using the archived external scientific validator.
- **External predictive ML:** WebSearch CDF-derived workload, nominal 60%
  offered load, seed 230, `ml_5ms`, 240 completed-flow records and 19 output
  files. The **original frozen 5 ms predictor** passed its pinned SHA-256
  check (`30372baf1843d5b9aec84bf95644a731637f5d3bcb5e8bcbd4fcd9e7555a7146`).
  A separate read-only archival comparison showed **19/19 exact raw-trace
  SHA-256 matches** and **12/12 scientific metric-field matches**, using the
  same archived external scientific validator.

These are **author-run local tests**, not independent-host reproduction or
verification of every controller and condition. The previous **360/360**
exact-reproduction result refers to the original ZIP-based workflow, not
360 code-first executions.

## 1. Install dependencies (Ubuntu / WSL2)

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build python3 curl bzip2
```

An optimized ns-3.47 build needs a C++ compiler, CMake, Ninja, and Python.
This one-case source-first smoke test requires only Python's standard library;
the scientific analysis scripts may additionally require NumPy and other
study-specific dependencies. Ubuntu/WSL2 was the host of the original
360-case reproduction.

## 2. Obtain a clean upstream ns-3.47 source tree

The reference version is **exactly ns-3.47**, not ns-3-dev, a later release,
or an Ubuntu-provided binary package.

The ns-3 project's
[release notes](https://gitlab.com/nsnam/ns-3-dev/-/blob/master/RELEASE_NOTES.md)
point to the upstream release archive:

```bash
mkdir -p "$HOME/ecn-upstream"
cd "$HOME/ecn-upstream"
curl -fL --retry 3 \
  https://www.nsnam.org/release/ns-3.47.tar.bz2 \
  -o ns-3.47.tar.bz2
tar -xjf ns-3.47.tar.bz2
test -f "$HOME/ecn-upstream/ns-3.47/ns3"
```

For supply-chain assurance, authenticate the upstream release against an
independent upstream-published digest or signed provenance if available.
Our full research ZIP, by contrast, is pinned to an exact SHA-256.
Do not download a different ns-3 release merely because it is newer.

## 3. Prepare the original source-based study

Clone or update this repository, then run the new setup tool:

```bash
git clone https://github.com/MateoBitar/delay-aware-predictive-ecn.git \
  "$HOME/delay-aware-predictive-ecn"
cd "$HOME/delay-aware-predictive-ecn"

python3 -m unittest discover -s tests -p 'test_*.py' -v

python3 run_from_source.py setup \
  --ns3-source "$HOME/ecn-upstream/ns-3.47" \
  --workspace "$HOME/ecn-source-original" \
  --variant original
```

If the repository is already cloned, run `git pull --ff-only origin main`
instead of `git clone`.

The setup tool:

- Requires a clean upstream `ns-3.47` tree with **no existing research
  example**, and refuses to overwrite an existing workspace.
- Copies upstream ns-3 into `~/ecn-source-original/ns-3.47` so it cannot
  mutate the original source tree.
- Installs the published, research-modified `red-queue-disc.cc`,
  `red-queue-disc.h`, `examples/tcp/CMakeLists.txt`, and original
  `bursty-dctcp-baseline.cc` at their original paths.
- Copies frozen `predictor_2ms.model`, `predictor_5ms.model`, and
  `predictor_20ms.model` to
  `research_horizon_study/horizon_models/`.
- Authenticates the example source and frozen models against the exact
  SHA-256 values in the successful archival reproduction orchestrator.
- Runs `./ns3 configure --enable-examples --build-profile=optimized -G Ninja`
  and then `./ns3 build`. The logs are saved in the new workspace.

No archived raw traces are copied into the new source workspace.
The build step may take several minutes. The `setup` command does not run
any scientific simulations.

## 4. Execute an actual recorded case

Run the reference baseline configuration for seed 224:

```bash
cd "$HOME/delay-aware-predictive-ecn"
python3 run_from_source.py run \
  --workspace "$HOME/ecn-source-original" \
  --controller baseline --seed 224
```

This reads the **actual recorded** command at
[`experiments/configurations/original/v2_full_evaluation/seed_224/baseline/command.json`](../experiments/configurations/original/v2_full_evaluation/seed_224/baseline/command.json).
The program executes with the original scientific flags, including
`--workloadMode=intermittent`, `--burstSchedule=aligned`,
`--workloadVariation=controlled`, `--RngSeed=1` and `--RngRun=101`.

The smoke test refuses an existing output directory or stale `bursty-*`
files in the new simulator root; it checks the expected core trace inventory
and exactly 24 short-flow completion records.

Its output directory is under
`~/ecn-source-original/runs/original/v2_full_evaluation/seed_224/baseline/`
and contains the original/local command record, simulation log, and generated
traces. **It does not compare the new traces to the archived reference
SHA-256 values.** Other frozen-model controllers can be selected using
`--controller ml_2ms`, `--controller ml_5ms`, or
`--controller ml_20ms`; trend and lower_fixed are also supported.

Each case can only run **once per workspace**: use a fresh workspace for
repeating a case rather than overwriting its scientific evidence.

## 5. Optional: separate source-based external workload variant

The external variant has a different, verified experiment C++ implementation.
It must have a **separate simulator build**, as in the accepted full-artifact
reproduction. Prepare it independently from the SAME clean upstream tree:

```bash
cd "$HOME/delay-aware-predictive-ecn"
python3 run_from_source.py setup \
  --ns3-source "$HOME/ecn-upstream/ns-3.47" \
  --workspace "$HOME/ecn-source-external" \
  --variant external

python3 run_from_source.py run \
  --workspace "$HOME/ecn-source-external" \
  --controller baseline --seed 230 \
  --dataset WebSearch --load 60
```

This reads the archived external command and its accepted
`input_manifest.csv` file directly from the repository, copies that
manifest into the fresh run folder, and remaps its historical absolute
`--externalManifestPath` to the local copy. It checks 240 FCT records.
Synthetic WebSearch and FB_Hadoop workload inputs derive from published
flow-size CDFs; these are **not** original production packet traces.

## Exact comparison of the external baseline against archived evidence

The source-based external WebSearch seed-230 baseline was independently
executed from the rebuilt variant and then compared to the preserved reference
under `external_validation/external_evaluation_180/WebSearch/load_60/seed_230/baseline/`.
The separate validation compared the complete `bursty-*` filename inventory,
each trace's byte count and SHA-256 digest, and recomputed all 12 accepted
metrics using the original `run_external_180.py` validation functions.
The reported results were:

```text
PASS: 19/19 raw traces match
PASS: ALL ARCHIVED TRACES MATCH EXACTLY
PASS: ALL 12 SCIENTIFIC METRIC FIELDS MATCH
PASS: SOURCE-BASED EXTERNAL BASELINE REPRODUCED
```

The archive was **not required to run** the rebuilt simulation; it was used
only as the reference for this subsequent validation. This establishes exact
**local one-case** agreement for the external baseline, rather than
independent third-party replication or complete source-first study reproduction.
No accepted archive files or scientific measurements were altered.

## Exact comparison of the predictive ML controller

After setting up the source-based external variant, the authors ran the
accepted `ml_5ms` WebSearch 60% / seed-230 configuration:

```bash
python3 run_from_source.py run \
  --workspace "$HOME/ecn-source-external" \
  --controller ml_5ms --seed 230 --dataset WebSearch --load 60
```

The reported execution completed **240 flow records** and generated **19
research output files**. A separate local read-only check against the
corresponding archived case in
`external_validation/external_evaluation_180/WebSearch/load_60/seed_230/ml_5ms/`
found:

```text
PASS: 19/19 raw traces match
PASS: Frozen 5 ms ML model SHA-256
PASS: ALL ML 5ms RAW TRACES MATCH EXACTLY
PASS: ALL 12 SCIENTIFIC METRIC FIELDS MATCH
PASS: SOURCE-BASED ML 5ms REPRODUCTION
```

The comparison also authenticated the local frozen model, validated the
input manifest's SHA-256, and recomputed the 12 accepted fields with the
archived `run_external_180.py` validator. The analysis uses the same
scientific tolerances as the archived full reproducer (absolute difference
no greater than `1e-9` for floating-point metric fields). The data were
not retrained or modified; no source archive or release asset was changed.

This result demonstrates exact **local single-case source-based** agreement
for an actual ML predictor, in addition to the previously verified baseline.
It does not prove all remaining ML settings or all 360 archived cases would
match when reconstructed independently.

## What this does not claim

- This is **not** an independent recreation of the ML training procedure:
  frozen archived predictors are reused.
- Running one case does **not** revalidate 360/360 experiments, all 5,148
  archived trace matches, or all 4,320 archived metric matches.
- Source-based builds may differ across compilers, platforms, and dependency
  versions. Record your compiler, Ubuntu, Python, CMake and ns-3 versions.
- The original and external C++ programs and their study parameters are
  not interchangeable. Two builds remain necessary.
- No upstream release SHA-256 is asserted here because the repository does
  not yet pin an independently verified upstream tarball digest.

## Full archival exact verification

If your goal is **exact byte-for-byte verification of all 360 previously
accepted simulations**, use the original ZIP with
[`reproduce_full_research_FIXED.py`](../reproduce_full_research_FIXED.py)
and follow [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md). The original ZIP
still includes the complete ns-3 source, reference raw traces, and accepted
analysis. The 7z release alternative contains the same file contents
but is not directly accepted by the ZIP-based orchestrator.
