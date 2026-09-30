# MindMesh third-party software notices

This source-only handoff does **not** vendor npm packages, Python wheels, CocoaPods or generated native frameworks. Direct JavaScript and Python dependencies and exact available versions are declared in `mobile/package.json`, `mobile/package-lock.json`, `backend/pyproject.toml` and `backend/requirements.lock`. Those libraries retain their respective upstream licence terms; the StudyRoom MIT file does not relicense them.

Among the direct client dependencies are Expo, React, React Native, Supabase JS, RevenueCat SDK packages and React Native SVG. The backend directly depends on FastAPI, SQLAlchemy, Alembic, psycopg, Pydantic, PyJWT, Uvicorn and websockets. `expo-audio` and the four unverified-rights music files are absent from this variant.

## Exact-source audit and reproduced texts

The bounded lockfile audit is complete, with exceptions rather than a blanket legal clearance. The [audit methodology](third-party/README.md), [machine-readable inventory](third-party/dependency-inventory.json), [full collected notices](third-party/THIRD_PARTY_NOTICES.generated.txt) and [individual original text files](third-party/license-texts/) are included. The inventory maps each text to its package/version, source, evidence tier and SHA-256; duplicate text is grouped without removing the package mapping or original copyright lines.

| Scope | Evidence obtained | Remaining limits |
| --- | --- | --- |
| 671 npm lockfile path entries, including dev and optional | 578 have text from an installed package or integrity-verified published artifact; 79 have text only from the exact npm-declared upstream Git commit | 14 entries lack exact full text. All are named in the exceptions register; no generic licence template was substituted. |
| 30 pinned Python runtime distributions | Official selected wheels were SHA-256 verified and all 30 supplied actual legal text | Compiled-wheel evidence covers selected CPython 3.11 Linux x86_64 files, not all platforms or all embedded code. |
| Python build/development requirements | `setuptools>=69` and `pytest>=8.3,<9.0` are recorded | They are unpinned ranges; no exact installed version or full transitive notice coverage is asserted. |

Read the [exceptions and redistribution boundaries](third-party/EXCEPTIONS.md) before redistributing dependencies or native builds. It identifies missing texts, upstream-only evidence, MPL/CC-BY/LGPL and combined/alternative expressions, `colorama` metadata ambiguity, and Jimp-derived provenance. A metadata licence label alone is not treated as a complete copyright notice.

The selected `psycopg-binary` Linux wheel embeds 15 libraries whose separate notices/source obligations were not established. Neither that wheel nor any other dependency binary is included in this repository candidate. These are concrete **future binary-distribution review gates**, not by themselves a finding that a source-only repository is blocked. CocoaPods/Gradle and other platform-native transitive dependencies also require a separate build-specific audit.

`third-party/FILES.SHA256` verifies the copied audit corpus; root `SHA256SUMS` covers the entire candidate. `third-party/initial-summary.json` is retained as historical collection-stage evidence; `third-party/summary.json` and the exceptions register describe final audit coverage. No upstream licence is replaced by the project's MIT licence. Contributor and media authority remain separate in [ASSET_RIGHTS.md](ASSET_RIGHTS.md).
