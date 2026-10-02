# MindMesh source-candidate validation — 29 September 2026

## Evidence attribution

### 30 September visible-branding update

The later owner-authorized branding delta changes app display/copy, backend user-facing messages, subscription display normalization, and service-name reservations/tests only. Dependency locks, migrations and technical auth/native/storage identities remain unchanged. On the actual publication source, using installed dependencies from the validation clone with the byte-identical mobile lockfile, strict TypeScript passed and all 606 default mobile tests passed with zero skips. This is source validation, not a native/device/provider/paywall test. The historical checks below remain attributed to their original snapshots.

The directly affected backend identity/premium tests also passed: 42 passed, one PostgreSQL-dependent test skipped. They used the existing local Python 3.11 environment with database/provider environment variables removed; no database/service/provider was started. The skip is not a pass.

The 30 September publication delta updates owner-confirmed contributor permission and repository authorization in six documentation files only. No application functionality, dependency pins or migrations changed. The earlier candidate manifest remains historical evidence; the publication directory has a regenerated root manifest covering its exact documentation delta.

The installation, test and export results below were executed on the reviewed no-music handoff from which this candidate was copied. Its manifest digest is `aa63dbdf0fcd5557a86cbd719761ae9e157e4ff6cf7bfe01a803c268f00d0b9c`. Preparing the MindMesh public candidate changes documentation, licence notices and `.gitignore`, not application code, dependency pins or migrations. These historical checks are not represented as reruns or as device validation of the final documentation package. The final candidate has its own `SHA256SUMS`.

## Frozen inputs and adaptation

The selected Preview mobile file set (app, src excluding music, plugin, manifest, lock, configuration and unpublished support-page source) was hashed before copy, copied to a new absent-checked directory, and hashed again in both source and copy. All three aggregate digests matched: `e0a7a25011e6248aa8f3e0b6294e33e66c5ddd6c57c443a228683e2323f47355`.

The accepted UI backend app, Alembic migrations, tests and manifests were separately hashed before/copy/after with the same result: `fd6a3f40ee8381610bb61573836b7371414c2a35355dcfb17bd1cce5c0c25248`. These are pre-adaptation source-set digests, not a full source-owner release signature.

Only the **copy** was adapted: remove `RouteMusic` from the root layout; omit `mobile/src/music/**` and the four MP3s; remove the obsolete music test script entry, `expo-audio` dependency and app plugin; regenerate the mobile lockfile offline with lifecycle scripts disabled. The original Preview, backend worktree and four MP3s were unchanged. Static searches found no remaining music imports, playback control or MP3 references in the copy.

## Executed, isolated checks

| Check | Actual outcome |
| --- | --- |
| Mobile lock install | `npm ci --offline --ignore-scripts --no-audit --no-fund` in a separate validation copy: exit 0; 636 packages installed from local cache. |
| Strict TypeScript | `npm run typecheck` in validation copy: exit 0. |
| Mobile tests | `npm test` in validation copy: **605 passed, 0 failed, 0 skipped**. The original five music-policy tests were intentionally removed with the music feature, and a no-music handoff invariant test was added. |
| JS export | `EXPO_OFFLINE=1 … expo export --platform ios --output-dir dist-check` with clearly synthetic public configuration in validation copy: exit 0; 1,396 modules, one 5.2 MB iOS Hermes bundle; no MP3 assets. This does not build a native iOS app. |
| Backend focused offline contracts | Five selected pure modules (contracts, schema, reward policy, solo retention, shared grading admission): **31 passed**. |
| Backend broader offline fake/protocol set | Selected realtime protocol, generation/grading and solo/reward/pet fake modules: **366 passed, 27 skipped** without test DB/provider variables. The skips are not passes. |

Backend tests used locally installed Python 3.14 packages; no isolated Python dependency installation, database, service or provider call was made. The package's `pyproject.toml` requires Python 3.11+, but a clean Python 3.11 setup was not demonstrated here. The standard networked npm install was not tested; the validated JavaScript install disabled lifecycle scripts. No native SDK 57 regeneration/build, Simulator or physical-device action was performed.

## Compatibility and remaining gates

For this documentation-only public-candidate preparation, the exact dependency audit maps all 671 npm lock paths and 30 pinned Python distributions. The collected notices preserve 288 distinct original text blobs; 14 npm exact-text exceptions, 79 upstream-only entries and binary/tooling limits are disclosed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Audit completion is not a statement that all legal obligations are cleared. No application suites were rerun merely for notice/copy changes.

Static source inspection matched the Preview mobile's realtime protocol v2 and solo/reward/pet HTTP paths to the copied backend's protocol-v2 parser/routes. That backend's startup requires migration `0012_learning_companions`. This is evidence for the pairing, not proof of a live end-to-end session or every schema detail. Previous Expo-Go preview and older RN0.79.6 Simulator/test results belong to different historical states and do not upgrade this package's validation.

Rights and dependency evidence remain in [ASSET_RIGHTS.md](ASSET_RIGHTS.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A clean Python install, authorized isolated database/runtime exercise and SDK 57 native build remain validation limits; source publication does not itself establish those results. Do not claim them until they have been performed. Do not infer AI accuracy, payment readiness, data preservation or production deployment from this source-only run.
