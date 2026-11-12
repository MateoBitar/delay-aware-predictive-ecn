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

## Measured compressed-byte breakdown (2026-11-12)

The read-only `audit_release_archive.py` check succeeded against the exact
published ZIP (SHA-256 verified). This section records measured ZIP **member
payload** sizes; ZIP headers and central-directory overhead are additional.

| Archive component | File members | Expanded MiB | Compressed ZIP data MiB |
| --- | ---: | ---: | ---: |
| `external_validation/` | 4,253 | 7,112.11 | **1,067.45** |
| `simulator/` | 6,539 | 304.48 | 89.63 |
| `reproduction/` | 216 | 9.81 | 1.81 |
| Root manifest and documents | 3 | ~2.39 | ~0.44 |
| **Total** | **11,011** | **7,428.79** | **1,159.33** |

The **single largest subtree**, `external_validation/external_evaluation_180/`,
contains 4,143 members, **7,101.57 MiB expanded** and **1,059.19 MiB of
compressed member data**. The `.dat` files across the archive contain 4,617
members and account for **1,085.59 MiB of compressed member data** (about
94% of all member data). The largest individual entries are
`bursty-short-flow-state.dat` traces at roughly **3.7–4.0 MiB
compressed each** (roughly 28–30 MiB expanded).

All 11,011 ZIP file members use DEFLATE (ZIP method 8); zero are encrypted.
The 11,011 count includes the single `MANIFEST_SHA256.json`, while the
previously published **11,010 payload files** count excludes this manifest.
Total archive bytes are **1,218,601,406**, versus **1,215,641,940**
compressed member bytes; the difference includes ZIP structural overhead.

The metadata check identified **362 same-length/CRC-32 candidate groups**.
These do *not* prove byte-level duplicates: CRC-32 can collide and repeated
files may be scientifically required in multiple experiment directories.
Do not delete or hard-link files on this basis. An independent solid-compression
benchmark is the preferred first experiment, not file removal.

## Diagnose compressed size accurately

A directory's uncompressed filesystem size cannot answer how much it contributes inside a ZIP: already-compressed images, PCAPs, numeric traces, and text can compress very differently. Inspect the ZIP central directory to attribute **compressed and expanded bytes by directory, file extension, and member**.

Use the read-only script `audit_release_archive.py` (published alongside this guide) on the original downloaded ZIP:

```bash
sha256sum /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip
python3 audit_release_archive.py /path/to/Delay_Aware_Predictive_ECN_RESEARCHER_READY.zip \
  --json archive_size_audit.json
```

The script requires Python 3 and standard-library modules only. It will **stop** on an unexpected archive hash and will not extract, delete, or edit any file. Its output will identify the actual compressed-byte hotspots. It lists same-length/CRC-32 candidates **for investigation only**; a matching CRC is *not* proof of identical content.

## Measured 7z/LZMA2 benchmark (2026-11-12)

A separate archive was created from the previously verified extracted package
using Ubuntu 7-Zip 26.00, LZMA2, solid mode, compression level 7 and two
threads:

```bash
7z a -t7z -m0=lzma2 -mx=7 -ms=on -mmt=2 \
  ~/Delay_Aware_Predictive_ECN_LOSSLESS_TEST.7z .
7z t ~/Delay_Aware_Predictive_ECN_LOSSLESS_TEST.7z
```

| Measurement | Original ZIP | Experimental 7z |
| --- | ---: | ---: |
| Archive bytes | 1,218,601,406 | **541,038,363** |
| File members | 11,011 | 11,011 |
| Uncompressed member bytes | 7,789,654,244 | 7,789,654,244 |
| Integrity check | Original ZIP SHA-256 confirmed | `7z t`: Everything is Ok |

The measured reduction is **677,563,043 bytes**, or **55.6% smaller**.
The 7z uses one solid LZMA2 block, explaining why similar traces can compress
better than independent ZIP entries.

**Status:** This is a preliminary lossless compression result, not yet a
published equivalent artifact. Counts, expanded-byte totals, and `7z t`
are insufficient on their own to prove identical names and content for each
file. An independent fresh extraction and SHA-256 comparison against every
member of the original ZIP is still required before publishing. The ZIP-based
reproducer does not accept a 7z file directly; continue using v1.0.0 ZIP for
the 360-run verification unless explicitly restoring the identical ZIP.

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
