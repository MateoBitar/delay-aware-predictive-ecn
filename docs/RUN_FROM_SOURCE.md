# Run from clean ns-3.47 source (code-first pathway)

This is the conventional, **code-first** entry point for the published research.
It does **not** require the 1.22 GB reference ZIP or the 541 MB 7z archive
to build and execute one of the **recorded original or external experiments**.

**Scope and evidence (2026-11-12):** This path uses the exact verified
research-specific C++ source and frozen predictor models already browsable in
GitHub, and reads recorded `command.json` files. The code-first setup has
automated offline contract checks. The authors additionally reported a
**successful local Ubuntu/WSL2 clean-upstream source build** for the original
variant and a seed-224 `baseline` smoke run:
`SMOKE TEST PASS: 24 completed-flow records, 19 research output files`.
This confirms execution from source on that host, **not** independent-host
reproduction, exact historical trace equality, the other controllers, or the
external variant. The previously reported **360/360** exact reproduction
applies exclusively to the archived ZIP workflow.

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
