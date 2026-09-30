# MindMesh dependency notice evidence — local, not legal clearance

This directory is a **copyable draft notice corpus**, generated for the frozen local source handoff with `SHA256SUMS` SHA-256 `aa63dbdf0fcd5557a86cbd719761ae9e157e4ff6cf7bfe01a803c268f00d0b9c`. It does not certify that every licence obligation, artwork right, native dependency, provider SDK, or future binary distribution is cleared. Do not silently treat an SPDX metadata field as a substitute for missing actual text.

## Copyable files

- `dependency-inventory.json`: one record for every one of the **671** mobile lockfile package paths (including dev and optional) and **30** pinned backend runtime distributions; exact version, declared licence expression, npm resolved URL/SRI or chosen PyPI wheel URL/SHA-256, evidence tier and text-file SHA-256. It separately lists the unpinned `setuptools>=69` build requirement and `pytest>=8.3,<9.0` development requirement; no exact notice/version is asserted for those ranges.
- `THIRD_PARTY_NOTICES.generated.txt`: full original licence/notice texts found in package artifacts or, where explicitly labelled, at the npm-declared upstream Git commit. Duplicate identical texts are grouped by SHA-256 and mapped to package/file names. This file is a draft and **does not cover the 14 exact-text exceptions** in `EXCEPTIONS.md`.
- `license-texts/`: **288** SHA-256-named original text files, allowing each package-to-file mapping in the inventory to be checked independently.
- `text-index.json`: reverse mapping from text digest to every package/file using it.
- `embedded-binary-wheels.json`: exact shared-library names in six verified CPython 3.11 Linux x86_64/universal wheel artifacts. In particular, `psycopg-binary` contains 15 bundled shared libraries while its wheel supplies only the package LGPL-3.0 text.
- `missing-readme-evidence.json`: integrity-verified npm README licence declarations for missing-text packages. Only `bplist-parser@0.3.1` contains a full MIT text in its published README; short labels such as “MIT” alone were **not** turned into fabricated full notices.
- `EXCEPTIONS.md`: precise unresolved texts, special licences, native/binary boundaries and owner/legal review questions.
- `summary.json`: mechanically counted coverage and the SHA-256 of the draft concatenated notices.

## Inputs and evidence tiers

| Input | SHA-256 / method |
| --- | --- |
| Frozen `mobile/package-lock.json` | `ff3fc17174a357548d15c69436819eb2d00a2b813d5c60f29d39274fd2a0beff` |
| Frozen `backend/requirements.lock` | `4705a3736548344a8930e8f16af61093375287ac2939d34efbccab6072e35401` |
| Frozen `backend/pyproject.toml` | `2bc943f519d97242aec72d690fa86bb67a4f73baadba19e66ad1a0c23bdd7d47` |
| npm installed text | Read from the separate validation clone created by `npm ci --offline --ignore-scripts`; no package lifecycle script ran in this audit. **636** lock entries were installed there; all **35** absent entries are platform-optional. |
| npm official registry text | **104** tarballs were fetched from lockfile `registry.npmjs.org` URLs and their SRI values independently checked; these cover absent optionals and packages with no installed licence-like file. |
| npm upstream-only text | **79** entries' published tarballs lacked legal files, but their versioned npm metadata named an upstream GitHub repository and exact `gitHead`. Licence files were fetched at that commit, with URLs and hashes recorded. These are **not** claimed to be files shipped in the npm tarball. |
| PyPI wheel text | **30/30** chosen files from official PyPI metadata were fetched and SHA-256 verified. Universal wheels were preferred; compiled wheels were selected for CPython 3.11 Linux x86_64. Other OS/ABI variants are not covered by this exact wheel-text audit. |

All nine declared backend runtime dependencies appear by name in `requirements.lock`; the build and dev ranges remain unlocked. The lockfiles list **671 + 30 = 701 pinned entries**, of which **657 npm + 30 Python** have actual text evidence in this corpus, and **14 npm** still lack full text. Among the 657 npm entries, 79 rely on commit-pinned upstream text rather than text in the published tarball. The source-only public candidate is not distributing `node_modules` or wheel binaries; licence duties for a future native/mobile/backend binary distribution require a separate platform-specific audit. The 15 bundled libraries in the selected `psycopg-binary` wheel are a concrete unresolved binary-notice case, not a claim that source-only publication itself is blocked solely by that wheel.

Method references: [npm lockfile fields](https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json) and [Python core metadata licence-file scope](https://packaging.python.org/en/latest/specifications/core-metadata/). The actual distribution archives and versioned metadata, not those explanatory pages, supplied the per-package evidence.
