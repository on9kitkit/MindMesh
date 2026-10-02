# MindMesh

**GCSE practice together or independently, with private answer feedback and space to work things out.**

MindMesh is an ongoing, development-stage study app built with Expo/React Native and a FastAPI/PostgreSQL backend. Submission preparation is complete; development now follows learner needs, safety and product quality rather than contest requirements. This repository is not a production release. It contains the selected Expo SDK 57 client, its matching backend, and migrations through `0012_learning_companions`.

The project was developed under the working name **StudyRoom**. The app's own visible branding now uses **MindMesh** and **MindMesh Pro**; its Preview display name is **MindMesh Preview**. Technical package names, URL schemes, bundle identifiers and saved-data keys retain the old identity for compatibility. Generic “study room” terminology still describes quiz rooms. Provider-managed paywall/store metadata is separate and has not been renamed or inspected by this source update. The cartoony-crow icon is the owner's intended identity; final artwork is not included in this source snapshot.

See [validation and limitations](VALIDATION.md), [asset rights](ASSET_RIGHTS.md), [dependency notices](THIRD_PARTY_NOTICES.md), and [licensing history](docs/LICENSING_HISTORY.md).

The package-only variant has **no music**. Four externally sourced MP3s lacked verified redistribution rights, so they were not copied. The route-mounted playback UI, static asset imports, audio plugin and unused audio dependency were removed from this copy. The original Preview source and audio remain unchanged. Do not describe this candidate as having playable theme music.

## What the source implements

The client contains authenticated study rooms, server-owned timed quiz state and results, private answer review, adaptive preparation, self-paced solo practice, a temporary local drawing workspace, Studio/Wood/Glass/Paper themes, and cosmetic companion/reward views. The backend owns membership, scoring, grading, reward state and authorization. Realtime uses protocol v2. This inventory is not a claim that every feature was exercised end-to-end in this package. Adaptive generation and eligible written grading need a separately configured paid AI provider; RevenueCat purchases need a separately configured Test Store integration. Neither was enabled for this handoff.

## Local prerequisites and setup

- Node.js/npm compatible with Expo SDK 57. The offline validation here used Node 22.22.2 and npm 10.9.7.
- Python 3.11 or newer, PostgreSQL, and a Supabase Auth project/public client configuration to sign in. No account, hosted backend, judge credentials or database is included.
- A **new database you control** if you choose to run the backend. It must be migrated to revision `0012_learning_companions`; server startup checks this and does not migrate automatically. Do not point migration or test commands at an existing shared database without separate approval.

First change to the package root (the directory containing this README, `mobile/` and `backend/`). Run these snippets in the same POSIX shell; if you open another terminal, set `STUDYROOM_PACKAGE_ROOT` there again. This variable contains only the local directory path, not a credential. Install dependencies and run the source-only checks:

```sh
STUDYROOM_PACKAGE_ROOT="$(pwd -P)"
cd "$STUDYROOM_PACKAGE_ROOT/mobile"
npm ci --ignore-scripts
npm run typecheck
npm test
```

The locked mobile dependency install was actually checked with `npm ci --offline --ignore-scripts --no-audit --no-fund` using a local cache, then the TypeScript, test and offline iOS JavaScript-export checks in [VALIDATION.md](VALIDATION.md) passed. The standard networked `npm ci` path and a native iOS build were not checked here.

For a backend development environment:

```sh
cd "$STUDYROOM_PACKAGE_ROOT/backend"
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Those backend install commands describe the source manifest; a clean isolated Python install was **not** executed in this handoff. Selected backend tests ran using installed local Python packages with database/provider variables removed. See [backend/README.md](backend/README.md) for configuration and test boundaries.

The `mobile/.env.example` describes **public Expo client** `EXPO_PUBLIC_*` values. Supply your own permitted public values through an untracked `mobile/.env` or the Expo process environment before bundling; never put secrets there, because public client values can be included in the app bundle. The example includes a public support contact but no working Supabase key. The backend is different: copying `backend/.env.example` to `backend/.env` does **not** configure Alembic or the server, which read their process environment. Follow the explicit, owner-reviewed private environment-loading steps in [backend/README.md](backend/README.md), and never commit populated files. The API URL defaults to loopback: a remote phone cannot use that loopback address as a Mac-hosted backend. Local Expo Go use requires a reachable backend and valid Supabase Auth setup. No such runtime was started for this package.

## Validation and limitations

- The old `ios/` project was intentionally excluded: its saved Pods were from Expo 53/React Native 0.79.6 while this source declares Expo 57/React Native 0.86.3. Native regeneration, signing, installation and device behavior have not been validated for this source.
- Offline export proves the JavaScript/assets bundle resolves, not that sign-in, rooms, AI, pets, native drawing, purchasing, or account deletion works on a device.
- The selected Preview source was copied without its Git history; the backend came from the accepted StudyRoom UI worktree after static API/protocol/revision checks. There was no end-to-end test of this precise combined snapshot.
- The current [first-party policy](LICENSE) is **All rights reserved** for new material not already licensed, effective 2 October 2026. Earlier MIT grants remain valid, including for unchanged material carried forward. See [licensing history](docs/LICENSING_HISTORY.md). Third-party licences and notices are unchanged.
- This public repository retains its sanitized source history without importing private development records. Contest-only copy and checklists have been retired; technical validation and rights limitations remain applicable.
