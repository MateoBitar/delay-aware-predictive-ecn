# Delay-Aware Predictive ECN for Bursty Datacenter Traffic

**Research artifact | ns-3.47 | TCP/DCTCP | Explicit Congestion Notification (ECN)**

**Authors:** Marco Bitar and Matéo Bitar
**Project:** CMPS 342, Advanced Computer Networks, American University of Beirut (Fall 2026)

This repository accompanies a simulation study asking **when, and whether, lightweight queue prediction improves congestion control beyond conventional DCTCP/ECN and simpler early-marking mechanisms**. We compare six controllers under paired traffic configurations rather than attributing every benefit from earlier marking to machine learning.

> **Artifact status:** Public research artifact; not a claim of IEEE acceptance or an official reproducibility badge. The 360 archived experiments were rerun and verified in an isolated workspace on the authors' WSL2 host. Independent cross-host reproduction has not yet been established.

## Research design

Six controller settings are compared:

| Setting | Description |
| --- | --- |
| `baseline` | Standard reactive ECN thresholds |
| `lower_fixed` | Lower fixed early-marking thresholds, without prediction |
| `trend` | Non-ML queue-trend predictor |
| `ml_2ms` | Frozen ML predictor, 2 ms horizon |
| `ml_5ms` | Frozen ML predictor, 5 ms horizon |
| `ml_20ms` | Frozen ML predictor, 20 ms horizon |

The accepted campaign comprises **360 simulations**:

- **180 original runs:** reference comparison (36), burst-size sensitivity (72), and per-link propagation-delay sensitivity (72), across paired seeds 224–229.
- **180 external-workload runs:** WebSearch- and FB_Hadoop-shaped traffic at selected nominal offered loads, across paired seeds 230–235.

External traffic uses **flow-size CDF-derived synthetic workloads** with generated arrival schedules; it is **not** a replay of original production packet traces. The propagation-delay study changes physical-link delay, not an independently injected ECN processing delay. Models were frozen during evaluation; model training is **not** included in the independent replay.

The main outcomes are mean, P95, and P99 short-flow completion time (FCT), supplemented by queue occupancy/delay, ECN marking, application goodput, and sender fairness. The analysis evaluates both latency benefit and throughput/fairness trade-offs. Paired uncertainty estimates should be read as exploratory, particularly with only six seeds per condition and no multiple-comparison correction.

## Get the complete artifact

The complete verified scientific package is published as a **versioned GitHub Release asset**, not committed into Git history. GitHub currently permits changes to this release, so the SHA-256 below is the integrity reference; do not replace the asset:

**[Download release v1.0.0](https://github.com/MateoBitar/delay-aware-predictive-ecn/releases/tag/v1.0.0)** — `Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip` (1,218,601,406 bytes).

SHA-256 of the original published archive:

```text
b26bfb7bcb26702ef88a6d29e3515e48d188988e31db7ad8edd243712304194c
```

### Smaller lossless download (same scientific contents)

**[Download the verified 7z archive (541 MB)](https://github.com/MateoBitar/delay-aware-predictive-ecn/releases/download/v1.0.0/Delay_Aware_Predictive_ECN_LOSSLESS_TEST.7z)** — `Delay_Aware_Predictive_ECN_LOSSLESS_TEST.7z` (541,038,363 bytes; **55.6% smaller** than the original ZIP).

7z SHA-256:

```text
fbc1080954c951b14047140585912b3fc4b8369620d2ed8be0b7cb30759afcc4
```

A fresh extraction of this 7z was compared with the original ZIP: **all 11,011 file paths, uncompressed sizes and SHA-256 file digests matched exactly**, including `MANIFEST_SHA256.json`. No study outputs were discarded. Requires a 7-Zip-compatible extractor (e.g., `7z x archive.7z`). The root reproduction orchestrator takes the original **ZIP**, not the 7z; download the ZIP for the documented one-command 360-run replay. If using the smaller download, extract it for inspection; the ZIP-based full replay still requires the original published ZIP. The 7z file-equivalence check is not a separate 360-run reproduction.

The alternate asset retains its originally uploaded `LOSSLESS_TEST` filename; despite that provisional name, its contents passed the documented full-file equivalence check. Details: [archive size and preservation](docs/ARCHIVE_SIZE_AND_PRESERVATION.md).

The release contains the modified ns-3.47 simulator, both experiment variants, frozen predictor models, recorded configurations and input manifests, 360 accepted runs and raw traces, analysis tools, and research documentation. See [artifact guide](docs/ARTIFACT_GUIDE.md) and [archive inventory](docs/ARCHIVE_INVENTORY.md).

## Browse the research code and accepted results

You can inspect the **research-specific ns-3 modifications**, frozen model
files, all **360 recorded run configurations and accepted validations**, and
accepted analysis tables directly in this Git repository:

- [Implementation source](src/) — RED/ECN modifications and original/external TCP variants.
- [Frozen prediction models](models/) — evaluation models and historical horizon summaries.
- [Experiment drivers and 360 configurations](experiments/) — command records, metrics and external manifests.
- [Analysis scripts and accepted external results](analysis/) — scientific tables, plots and verification utilities.
- [Browsable files guide](docs/BROWSABLE_FILES.md) — relationship between these subsets and the exact release archive.

These are **selected copies from the verified ZIP**, not a second separately
executable ns-3 tree. For complete reproducibility, download v1.0.0 and use
the full replay procedure below. The release ZIP is still the authoritative
complete scientific artifact.

## Getting started: build and run from upstream ns-3.47 source

For researchers who want to **run the implementation without downloading the
large reference dataset**, use the separate
**[code-first ns-3.47 setup and one-run guide](docs/RUN_FROM_SOURCE.md)**.
It installs the exact research-specific C++ modifications and frozen models
from this Git repository into a new copy of clean upstream ns-3.47, builds
with CMake/Ninja, and executes a selected **recorded seed/controller case**.

Both original (seed 224) and external synthetic workload (seed 230) examples
are documented. No archived raw output traces need to be downloaded to run a
case from source.

**Validation boundary (2026-11-12):** The code-first setup passed
automated contract checks and local Ubuntu/WSL2 builds of **both** ns-3.47
variants. The original seed-224 baseline completed **24 flow records and 19
output files**. The external WebSearch 60%/seed-230 baseline completed
**240 flow records and 19 output files**, followed by **19/19 exact archived
trace SHA-256 matches and 12/12 accepted scientific metric matches**.
The same external WebSearch 60%/seed-230 case with the actual
**`ml_5ms` predictive controller** also executed from clean source and
passed **19/19 exact raw-trace SHA-256 comparisons**, **12/12 accepted
scientific metric checks**, and authentication of the frozen 5 ms model
(SHA-256 `30372baf1843d5b9aec84bf95644a731637f5d3bcb5e8bcbd4fcd9e7555a7146`).

These are author-run local results for selected cases, **not**
independent-host verification or complete source-first reproduction of all
360 cases. The separate full archival ZIP pathway remains the documented
360/360 verified workflow. See the [source verification scope](docs/RUN_FROM_SOURCE.md).

## Quick start: reproduce all 360 accepted simulations

Tested environment: Linux under Ubuntu/WSL2 on x86_64; Python 3.14.4 and NumPy 2.3.5 were reported by the successful reproduction. The verifier also needs a C++ toolchain, CMake, and Ninja. Budget **at least 30 GiB free disk space** for extraction, two simulator builds, and fresh results. The successful local run reported approximately 24 minutes elapsed; other systems may differ significantly.

```bash
# Install system build tools on Ubuntu (package availability depends on release).
sudo apt update
sudo apt install -y build-essential cmake ninja-build python3 python3-numpy

# In a clone of this repository, obtain the v1.0.0 ZIP from the Releases page,
# and save it outside the Git repository, e.g. $HOME/Downloads/.
sha256sum "$HOME/Downloads/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip"

# Compare its digest to the pinned SHA-256 above, then run:
python3 reproduce_full_research_FIXED.py \
  --zip "$HOME/Downloads/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip" \
  --workspace "$HOME/ecn-independent-reproduction" \
  --jobs 1
```

A successful complete run reports `SUCCESS: FULL 360-EXPERIMENT REPRODUCTION PASSED` and writes `FINAL_REPRODUCTION_REPORT.json` to the requested workspace. The verifier authenticates the ZIP contents, rebuilds the original and external ns-3.47 variants, reruns all recorded configurations, checks preserved traces and run-level metrics, and regenerates four external scientific analysis CSVs. It does **not** retrain the ML models. See [detailed reproduction instructions](docs/REPRODUCIBILITY.md).

## Verified evidence

The [final verification report](FINAL_REPRODUCTION_REPORT.json) records the following results from one local independent-workspace verification:

| Verification | Recorded result |
| --- | ---: |
| Accepted configurations rerun and verified | **360 / 360** |
| Original / external configurations | **180 / 180** each |
| Raw trace file comparisons | **5,148 matched** |
| Per-run scientific metric fields | **4,320 matched** |
| Regenerated external scientific CSVs | **4 / 4 SHA-256 matched** |

These results substantiate local reproducibility **under the tested environment**. They are not an external third-party evaluation, peer-review acceptance, or proof of identical behavior on every operating system or compiler.

## Repository organization

```text
README.md                          Project landing page and quick start
CITATION.cff                       Citation metadata for the v1.0.0 artifact
reproduce_full_research_FIXED.py   Full 360-experiment verification orchestrator
FINAL_REPRODUCTION_REPORT.json     Recorded independent-workspace verification
src/                               Selected research-specific ns-3 source changes
models/                            Frozen predictors and horizon summaries
experiments/                       Original/external drivers and 360 run records
analysis/                          Analysis scripts, accepted tables, verifiers
docs/
  ARTIFACT_GUIDE.md               Experiment design, metrics, interpretation
  REPRODUCIBILITY.md              System requirements and exact replay procedure
  BROWSABLE_FILES.md              Provenance and limitations of Git-tracked subset
  ARCHIVE_INVENTORY.md            Integrity and 11,010-file package inventory
  ARCHIVE_SIZE_AND_PRESERVATION.md ZIP size, lossless options, audit procedure
  RUN_FROM_SOURCE.md              Clean ns-3.47 code-first setup and smoke run
  LICENSING_AND_PROVENANCE.md    Third-party and research-specific licensing scope
run_from_source.py                 Builds isolated original/external source workspaces
tests/                             Offline research SHA-256 and command checks
.github/workflows/                 Automated source-contract checks
.gitattributes                     Preserve archived CSV line endings
.gitignore                         Avoid large generated outputs in Git history
```

The **browsable Git tree is a selected research-specific subset**, not a
standalone build of ns-3.47. Its original and external experiment scripts
expect the directory layout of the complete release package. For exact
reproduction use the versioned ZIP and the root verification orchestrator.

See [archive size and preservation](docs/ARCHIVE_SIZE_AND_PRESERVATION.md)
before attempting compression or publication of an alternate archive.
The release ZIP is the authoritative source for the 360-run verified dataset.

## Citation and reuse

Please cite the project as an **unpublished research artifact** until a paper or DOI becomes available. Citation metadata are provided in [CITATION.cff](CITATION.cff); an IEEE journal/conference citation will be added only after publication. See [reproducibility limitations](docs/REPRODUCIBILITY.md#limitations-and-scope).

**Licensing note:** The simulator contains upstream ns-3.47 code, including GPL-2.0-only components and other file-specific notices. We retain those notices and do not impose a new blanket license over them. Rights holders must confirm licensing of research-original material separately. Read [licensing and third-party provenance](docs/LICENSING_AND_PROVENANCE.md) for the specific source-file boundaries and outstanding decisions. Absence of a project-wide `LICENSE` does not remove third-party license obligations or grant unrestricted reuse rights.
