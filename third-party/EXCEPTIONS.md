# Dependency notice exceptions and review boundaries

This file records gaps in the exact artefacts audited for the frozen MindMesh local source candidate. It is **not** a legal opinion and does not assert that an absent text makes the source-only repository unlawful. The 14 rows below have a declared npm licence expression and an integrity-verified published tarball, but no full licence/notice text was obtained from that tarball, its installed copy, or an exact commit-pinned upstream source. Do not insert a generic SPDX template and call it the package's original notice.

| npm package | Declared expression | Authoritative sources attempted / remaining gap |
| --- | --- | --- |
| `@expo/devcert@1.2.1` | MIT | Verified tarball has no full licence file. README gives a short MIT attribution; npm `gitHead` points to `expo/devcert`, whose exact-commit tree has no licence/notice file. |
| `@expo/sdk-runtime-versions@1.0.0` | MIT | Verified tarball has no legal text and versioned npm metadata supplies no source repository. |
| `@expo/xcpretty@4.4.5` | BSD-3-Clause | Verified tarball has no legal text. Metadata points to `expo/expo-cli` but supplies no `gitHead` to pin the corresponding source. |
| `boolbase@1.0.0` | ISC | Verified tarball has no legal text. Metadata names `fb55/boolbase` but has no `gitHead`; available repository tags did not identify this exact 1.0.0 source. |
| `bser@2.1.1` | Apache-2.0 | Verified tarball has no legal text. Metadata names `facebook/watchman` but lacks an exact source commit. |
| `client-only@0.0.1` | MIT | Verified tarball has no legal text and versioned npm metadata has no source repository. |
| `@expo/ws-tunnel@2.0.0` | MIT | Verified tarball has no legal text. A `gitHead` is present, but no source repository is identified in versioned npm metadata. |
| `fb-watchman@2.0.2` | Apache-2.0 | Verified tarball has no legal text. Metadata names `facebook/watchman` but lacks a commit for this npm version. |
| `jimp-compact@0.16.1` | MIT | Verified tarball and named exact `nuxt-community/jimp-compact` Git commit lack full legal text. README says it is based on Jimp; any embedded Jimp-derived source attribution must be checked before binary redistribution. |
| `react-remove-scroll-bar@2.3.8` | MIT | Verified tarball has only a short README licence label. The named exact upstream commit yielded no raw licence file; the GitHub tree request was unavailable. |
| `server-only@0.0.1` | MIT | Verified tarball has no legal text and versioned npm metadata has no source repository. |
| `standard-navigation@0.0.5` | MIT | Verified tarball and named exact `react-navigation/standard-navigation` Git commit have no legal text. |
| `structured-headers@0.4.1` | MIT | Verified tarball and named exact `evert/structured-header` Git commit have no legal text. |
| `tr46@0.0.3` | MIT | Verified tarball and named exact `Sebmaster/tr46.js` Git commit have no legal text. |

`bplist-parser@0.3.1` initially had no standalone LICENSE, but the integrity-verified tarball's README includes its full MIT grant and copyright statement; that exact section is in the notice corpus and is **not** in the unresolved table. `fb-dotslash@0.5.8` has both MIT and Apache-2.0 full texts at its npm-declared exact upstream commit; `stream-buffers@2.2.0` has its UNLICENSE text there. Upstream-only evidence remains visibly labelled in the inventory.

## Licence expressions requiring deliberate review

- npm: `lightningcss` and 11 platform packages declare MPL-2.0; `caniuse-lite@1.0.30001806` declares CC-BY-4.0; `node-forge@1.4.0` declares BSD-3-Clause **OR** GPL-2.0; `fb-dotslash@0.5.8` declares MIT **OR** Apache-2.0; `@expo-google-fonts/material-symbols@0.4.48` declares MIT **AND** Apache-2.0 and ships a separate font licence file. BlueOak-1.0.0, Python-2.0, Unlicense, 0BSD, CC0 and other alternative expressions also appear; the inventory identifies every entry. No licence alternative was silently chosen for the owner.
- Python runtime: `psycopg` and `psycopg-binary` declare LGPL-3.0-only; `certifi` declares MPL-2.0; `cryptography` declares Apache-2.0 **OR** BSD-3-Clause; `greenlet` declares MIT **AND** PSF-2.0. `colorama@0.4.6` has **no PyPI licence expression**, though its selected wheel includes a copyright-bearing BSD-style full text and a generic BSD classifier. Keep the metadata gap visible rather than asserting an exact SPDX expression from that classifier.
- `backend/pyproject.toml` declares `setuptools>=69` for build and `pytest>=8.3,<9.0` for dev. Neither is locked to an exact version or integrity in `requirements.lock`; this audit cannot attach an exact selected archive/notice to those ranges. Pin or separately record the concrete build/dev environment before claiming complete notices for redistributed build/test tooling.

## Embedded code and future binaries

The selected `psycopg-binary==3.3.4` CPython 3.11 Linux x86_64 wheel contains **15** bundled `.so` libraries, including `libpq`, OpenSSL, Kerberos, LDAP and SASL components; its wheel exposes only `psycopg_binary-3.3.4.dist-info/licenses/LICENSE.txt` (LGPL-3.0). Separate component notices/source-offer obligations for a binary distribution were **not** established. `embedded-binary-wheels.json` lists exact names and the verified wheel digest. Other compiled wheels (`cryptography`, `cffi`, `greenlet`, `markupsafe`, `pydantic-core`) have their package-level texts, but statically linked or Rust/C dependencies are not certified by this filename-level check.

The public source candidate does not include npm `node_modules`, PyPI wheels, regenerated iOS/Android native outputs, CocoaPods, Gradle artefacts or the four omitted music tracks. A future device binary pulls platform-specific native dependencies not fully represented by the npm/Python lockfiles; this corpus cannot clear those. The package's own contributor rights, crow artwork/media provenance, complete guardian-form evidence and publication authority remain separate from dependency notices.
