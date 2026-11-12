# Archive size and lossless preservation

## What is known and verified

The complete, authoritative v1.0.0 asset is
[`Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip`](https://github.com/MateoBitar/delay-aware-predictive-ecn/releases/tag/v1.0.0).

- ZIP size: **1,218,601,406 bytes** (approximately **1.135 GiB**).
- Published SHA-256: `b26bfb7bcb26702ef88a6d29e3515e48d188988e31db7ad8edd243712304194c`.
- Archive manifest: **11,010 payload files**, plus `MANIFEST_SHA256.json`.
- Prior filesystem inventory of extracted package: `external_validation/` approximately **7,112.11 MiB**; `simulator/` approximately **304.48 MiB**; `reproduction/` approximately **9.81 MiB**. These are **expanded filesystem sizes**, not contributions to compressed ZIP bytes.
- The external-validation tree is by far the largest expanded component (about **96%** of these measured folder sizes). This suggests raw experimental outputs are a size driver but does **not** establish their compressed-byte contribution.

**Important:** The current archive is independently reproduced and its exact SHA-256 is referenced in the published verification report. Do not change, recompress, rename, or replace that original release asset. GitHub reports the release as editable; the published SHA-256, not GitHub immutability, is the integrity check.

## Diagnose compressed size accurately

A directory's uncompressed filesystem size cannot answer how much it contributes inside a ZIP: already-compressed images, PCAPs, numeric traces, and text can compress very differently. Inspect the ZIP central directory to attribute **compressed and expanded bytes by directory, file extension, and member**.

Use the read-only script `audit_release_archive.py` (published alongside this guide) on the original downloaded ZIP:

```bash
sha256sum /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip
python3 audit_release_archive.py /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip \
  --json archive_size_audit.json
```

The script requires Python 3 and standard-library modules only. It will **stop** on an unexpected archive hash and will not extract, delete, or edit any file. Its output will identify the actual compressed-byte hotspots. It lists same-length/CRC-32 candidates **for investigation only**; a matching CRC is *not* proof of identical content.

## Lossless size-reduction options

1. **Keep v1.0.0 as the reference** and test a *second archive* with identical member paths and member bytes. A higher-compression ZIP (DEFLATE level 9) may save space depending on how the current file was built; results must be measured.
2. **Test a more efficient lossless codec** (e.g., `7z` using LZMA2, or `tar.zst` using a high compression level) on a copy of the release's extracted contents. Solid compression may reduce repeated data across many small traces. This is a hypothesis until benchmarked. These formats may require additional tools and are not interchangeable with the current ZIP-based reproduction command.
3. **Consider a separately labeled distribution** of an alternative smaller archive only after verifying *all paths and file bytes* against `MANIFEST_SHA256.json`. The manifest itself must also be preserved. Prefer including a deterministic, documented extraction procedure.
4. **Keep the Git repository small.** The browsable Git tree intentionally excludes bulk raw traces and upstream ns-3 source. The verified full archive is available through Releases.

Neither an alternate codec nor deduplication guarantees meaningful savings. Do not omit historical files, round numeric data, prune logs, or remove repeated raw traces merely to reduce bytes: that changes archive membership or content and breaks the verified artifact contract.

## Required acceptance checks for any alternate archive

An alternate archive is **not a replacement for v1.0.0**. Before distributing one, verify all of the following on a clean extraction:

- The **same 11,010 payload member paths**, with exact byte-for-byte SHA-256 matches to the embedded manifest; retain the original `MANIFEST_SHA256.json` and top-level research documentation.
- No duplicate paths, unexpected files, missing files, unsafe path traversal, symlinks or permissions that change interpreted content.
- Required modified ns-3 sources, frozen predictors, configurations, manifests, analysis scripts, and accepted traces are all present.
- Extraction and full **360-case reproduction** still work (or a documented lossless conversion back to the original ZIP is explicitly required before running the pinned reproducer).
- A **new distinct version and new archive checksum** are published; the original v1.0.0 remains untouched.

## Reproducibility boundaries

The `src/`, `experiments/`, `models/`, and `analysis/` Git directories are selected, separately browsable copies of verified archive members. They are not a second buildable ns-3 distribution. Their purpose is transparent review, not an alternate entry point for running archived experiments.

This document deliberately does **not** claim a measured compressed-byte contribution by file class or a tested smaller archive; those conclusions require the audit and benchmark on the actual 1.22 GB binary.
