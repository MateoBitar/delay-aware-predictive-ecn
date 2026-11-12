# Browsable implementation, models, inputs and results

This directory tree exposes the research-specific files inside the **exact,
checksum-verified v1.0.0 release archive**. It is provided for browsing, code
review, and locating results. **It is not a standalone replacement for ns-3.47.**

## Layout and provenance

- [`src/ns3/`](../src/ns3/): research simulator implementation and the
  ns-3 TCP example build registration. Files mirror their relative ns-3 paths.
- [`src/external_override/`](../src/external_override/): original external
  workload variant of the TCP experiment source.
- [`models/`](../models/): frozen predictor models and their archived
  horizon summaries (including historical horizons not in the six-controller
  final evaluation).
- [`experiments/scripts/original/`](../experiments/scripts/original/):
  original study execution and model-training/validation scripts.
- [`experiments/scripts/external/`](../experiments/scripts/external/):
  external CDF-derived study execution scripts.
- [`experiments/configurations/`](../experiments/configurations/):
  all 360 archived `command.json` + `validated_result.json` pairs and, for
  external runs, their corresponding `input_manifest.csv` files.
- [`analysis/scripts/`](../analysis/scripts/): original/external scientific
  analysis and plot-generation programs.
- [`analysis/results/external/`](../analysis/results/external/): accepted
  external analysis tables and provenance; **not** intermediate partial tables.
- [`analysis/verification/`](../analysis/verification/): archive integrity
  and external-analysis verification helpers.

The `command.json` files were recorded in the authors' original WSL
environment and may contain machine-specific absolute paths. For an
independently portable replay, use the [full reproduction orchestrator](../reproduce_full_research_FIXED.py), which remaps frozen models and
external manifests to paths within the downloaded release. The accepted
`validated_result.json` files are reference outputs, not new experiments.

## What is intentionally not duplicated in Git

- Complete upstream ns-3.47 source tree, build products and dependencies.
- Bulk raw packet/queue traces, PCAPs, simulation logs and figures.
- Historical source backup snapshots and intermediate/partial result files.

These remain **in the unchanged v1.0.0 release ZIP**, which is authoritative
for complete reproduction and its validated checksum. Code snippets here do
not substitute for the exact source tree and recorded traces in that archive.

## Reproduction and limitations

See the root [README](../README.md), [reproduction guide](REPRODUCIBILITY.md),
and the [full release](https://github.com/MateoBitar/delay-aware-predictive-ecn/releases/tag/v1.0.0).
Frozen models are reused and training is not rerun in the reported 360-run
reproduction. External workloads are CDF-derived synthetic traffic, **not**
production packet-trace replay. Verification is from an isolated local WSL2
workspace; independent cross-host exact reproduction has not been reported.
