# License scope and third-party notices

**License selected for the authors' original software contributions:**
[GNU General Public License version 2 only](LICENSE)
(`GPL-2.0-only`).

The authors have indicated that other researchers may use, modify, and
redistribute their original research code under the applicable notices.
This repository includes the complete, unmodified GPL version 2 license
text in `LICENSE` for clarity. This declaration applies **only to
rights the project authors can license**; it does not relicense material
belonging to ns-3 or other third parties.

## Software scope

Subject to any embedded notices and third-party rights, the authors'
original contributions to the following research code are made available
under `GPL-2.0-only`:

- The project's own implementation and modifications in
  `src/ns3/examples/tcp/bursty-dctcp-baseline.cc` and
  `src/external_override/bursty-dctcp-baseline.cc`.
- The project-authored modifications to the upstream
  `src/ns3/src/traffic-control/model/red-queue-disc.cc` and
  `red-queue-disc.h`, and the research example registration added
  to `src/ns3/examples/tcp/CMakeLists.txt`.
- Project-authored Python experiment, analysis, orchestration and
  verification code under `experiments/scripts/`,
  `analysis/scripts/`, `analysis/verification/`, and the root
  `reproduce_full_research_FIXED.py`, `run_from_source.py`,
  `audit_release_archive.py` and `tests/`.

Upstream ns-3 files, including the modified RED implementation,
continue to be governed by **their own existing** copyright and
license notices, including `GPL-2.0-only` and the embedded University
of California conditions. Keep those notices intact and consult the
original upstream distribution for the applicable component license
inventory. The research contribution license does not erase or
supersede upstream rights.

If any of the project-authored paths above contain material obtained
from third parties, that third-party material remains subject to its
original license, and the authors' GPL grant applies only to their
own copyrightable contributions.

## Exclusions from this software license

This GPL declaration does **not** automatically apply to:

- Generated scientific datasets, simulation outputs and traces
  (`.dat`, `.csv`, `.pcap`, `.log`, figures and other raw results).
- Frozen predictor model weights and associated recorded outcomes.
- External published flow-size CDF reference data or other
  externally sourced material.
- Research manuscript content and separately authored documentation
  whose rights are not established.
- Bundled third-party dependencies and software under their own licenses.

Those materials remain available for reproducibility and scientific
inspection in the existing artifacts, but this file **does not create
a new blanket license** for them. Their independent redistribution
or reuse may require a separate rights review or permission.

## Original reference archives

The complete `v1.0.0` ZIP and lossless 7z contain **identical scientific
file contents** and remain unchanged. The license documentation added
to GitHub after publication does not modify or repack either archive,
does not assert ownership of their bundled third-party materials,
and does not affect the accepted reproduction checksums.

For provenance and the unresolved data/model permissions, see
[docs/LICENSING_AND_PROVENANCE.md](docs/LICENSING_AND_PROVENANCE.md).

For the authoritative license wording, read [LICENSE](LICENSE). This
scope summary is informational and does not override original
copyright notices or the full license terms.
