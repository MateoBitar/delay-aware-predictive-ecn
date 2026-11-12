# Software licensing and third-party provenance

## Purpose and scope

This repository publishes research-specific source files and a complete
ns-3.47 research release. The repository is publicly accessible, but public
availability alone **does not constitute a universal license to reuse or
redistribute every file**. The authors' original software contributions are now offered under
**GPL-2.0-only**, with the unmodified license text in [LICENSE](../LICENSE).
The exact project-code scope and exclusions are documented in
[LICENSE_SCOPE.md](../LICENSE_SCOPE.md). This document identifies
third-party provenance and remaining permissions without claiming
ownership of upstream software or blanket relicensing of datasets.

## ns-3.47 and modified upstream source

The official [ns-3.47 contributing documentation](https://www.nsnam.org/docs/release/3.47/contributing/ns-3-contributing.pdf)
states that ns-3 as an aggregate is **GNU GPL version 2 only
(`GPL-2.0-only`)**; individual components can include additional
compatible notices. Follow the licenses and attribution notices that
accompany the precise upstream release and individual source files.

These tracked copies originate from and modify or register files in
ns-3.47:

- `src/ns3/src/traffic-control/model/red-queue-disc.cc`
- `src/ns3/src/traffic-control/model/red-queue-disc.h`
- `src/ns3/examples/tcp/CMakeLists.txt`

The two RED queue-disc files retain an
`SPDX-License-Identifier: GPL-2.0-only` notice, original
copyright/attribution information, and the embedded University of
California redistribution notices. **Do not remove, replace, or
relicense these notices** merely because the files also contain
research-specific modifications. The complete published ZIP/7z contains
upstream ns-3 source that is governed by the individual licenses shipped
with that upstream distribution.

For distribution of GPL-licensed modified files, retain relevant
license text, copyright and modification notices and the corresponding
source code, and satisfy the applicable GPL terms. The full artifact
includes source, but a file-level and component-level license inventory
of the complete third-party tree has not yet been certified.

## Research-specific additions

The following paths contain project-specific research code and artifacts
as they appear in the browsable Git repository:

- `src/ns3/examples/tcp/bursty-dctcp-baseline.cc` and
  `src/external_override/bursty-dctcp-baseline.cc`: research
  ns-3 experiment implementations.
- `models/`: frozen predictor model data and horizon summaries.
- `experiments/`: recorded commands, original/external study scripts,
  manifests, and accepted validations.
- `analysis/`: analysis and verification code/results.
- `reproduce_full_research_FIXED.py`, `run_from_source.py`, and
  `audit_release_archive.py`: research and artifact tooling.
- `docs/`, `README.md`, and `CITATION.cff`: research documentation.

These paths may contain ns-3-derived code, external data descriptions,
or other dependencies. **Listing a path as research-specific is not a
legal conclusion that all its code is solely owned by the named authors.**

The two experiment C++ files currently have no explicit top-of-file
license declaration. The repository-level
[LICENSE_SCOPE.md](../LICENSE_SCOPE.md) now explicitly offers **the
authors' original contributions** to these files under GPL-2.0-only
without changing the archived or Git-tracked C++ source bytes. Any
ns-3-derived code in these files and any other copied third-party
material retains its existing licensing and attribution obligations.
A separate file-level third-party provenance audit is still advised
before upstream contribution or redistribution outside this package.

## External workload datasets

The study describes WebSearch- and FB_Hadoop-shaped **synthetic
CDF-derived** workloads with generated arrival schedules. These are not
copies of production packet traces. The underlying published CDF
sources, their specific terms and proper scholarly attribution should
be confirmed before separately licensing any redistributed dataset.

Experiment outputs are not automatically subject to the same license
as simulator source code, and no data-wide Creative Commons license
is asserted here.

## What users can and cannot infer

- The existence of a public GitHub repository and downloadable
  research artifacts does not confer unrestricted reuse rights.
- The root `LICENSE` grants GPL-2.0-only terms for **the authors' original
  software contributions only**; it does not override license conditions
  already present in third-party files, nor automatically license
  dataset/model assets.
- ns-3 source retains its upstream terms and component-specific
  notices.
- `CITATION.cff` asks for scholarly attribution; a request to cite is
  **not itself a software or dataset license**.
- Full scientific reproduction can be performed under applicable
  third-party licenses, but any further redistribution or modification
  should comply with all relevant rights and notices.

## Remaining provenance and rights checks

The code license has been selected, but this is **not** a completed
component-by-component rights audit of every file in the 11,011-file
research artifact.

1. Preserve upstream attribution and GPL-2.0-only / compatible component
   terms in the copied ns-3.47 files.
2. Review whether external CDF sources or derived model/data products carry
   independent redistribution requirements.
3. Confirm any additional institutional or contributor rights if the
   original contributions have more copyright holders than the two
   identified authors.
4. Decide separately whether to grant an explicit license for generated
   datasets, frozen model files, or figures. No such license is asserted
   here.

This page documents software licensing scope and third-party provenance.
It is **not legal advice or a substitute for individual license notices
included with corresponding upstream source distributions**.
