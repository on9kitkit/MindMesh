# MindMesh — prepared Devpost copy

Prepared locally for the **Next Gen Award**. Nothing in this file has been entered into Devpost. The sections below are candidate narrative text; map them to the actual form and reconcile them with the final video before submission. Publication links and personal/team information are tracked separately in [PUBLICATION_CHECKLIST.md](PUBLICATION_CHECKLIST.md).

## Project name

MindMesh

## Tagline

GCSE practice together or independently, with private feedback and space to work things out.

## Inspiration

Studying can mean working alone, comparing answers with friends, and needing somewhere to sketch an idea before writing an answer. MindMesh brings those activities into one study app: shared quiz rooms, independent practice, private feedback, and a drawing workspace for rough working.

## What it does

MindMesh lets students join a study room, mark themselves ready, answer the same timed questions and compare their results. Each participant can review their own answers, marks and explanations. The backend controls quiz progress and scoring, and reconnecting clients recover the shared state.

The source also includes self-paced solo practice, Studio/Wood/Glass/Paper appearance choices with light and dark modes, private drawing scratchwork with geometry tools, and an earned cosmetic pet system. Companions have simple personalities and reactions; coins reward qualifying participation and buy cosmetic choices rather than better quiz scores.

Adaptive preparation creates a subject/topic-based question set and runs validation and verification before play. Multiple-choice and numerical answers are marked deterministically. Room written answers and eligible longer solo responses use a bounded AI rubric-grading path. Short solo written responses use an explicitly labelled self-assessment step. AI feedback can be wrong, and self-assessed marks are not independent grading.

The starter catalogue covers six GCSE subjects and eighteen topics. It is not a complete syllabus or a claim of exam-board accreditation. Drawing is private rough working, not submitted handwriting. The learning illustrations are curated examples rather than images generated for each question.

## How it is built

MindMesh uses Expo, React Native and strict TypeScript for the client; FastAPI and PostgreSQL for application state; and Supabase Auth for sign-in. Server-side adapters handle adaptive generation and eligible written marking. Provider secrets stay on the backend. The current source targets Expo SDK 57 and includes database migrations through `0012_learning_companions`.

The project began under the working name StudyRoom, which remains in source identifiers and some development UI. MindMesh is the submission name. This repository candidate excludes the earlier music assets and playback controls.

## RevenueCat integration

The source integrates the RevenueCat SDK for a development Pro offering and entitlement, with backend checks for Pro room capacity and client-side cosmetic presentation gates. It supports RevenueCat Test Store configuration; the public candidate contains no configured credentials and does not claim production App Store products, real payments or revenue. The demonstration should identify Test Store explicitly and show the actual offering, purchase result and entitlement-backed behavior.

## Challenges and technical choices

Keeping two clients consistent required server-owned question transitions, answer locking and reconnect recovery. Written grading introduced another failure path: a response could be accepted while marking was unavailable. The implementation exposes that state and supports a controlled marking recovery rather than inventing a score.

The solo and rewards paths required separate ownership and idempotency rules. A drawing workspace also needed to preserve geometry, respect the selected theme and avoid competing with quiz navigation and timers. The submission package separates project source from external media and documents its dependency licences and current validation limits.

## Accomplishments and validation

An earlier native development build completed a two-device multiplayer test through questions, matching results, return to the waiting room and background/reconnect recovery. One adaptive five-mark geometry test reached completion with both participants' private reviews after a marking interruption was recovered. These are observations from earlier builds, not a broad assessment of educational accuracy.

For this no-music source snapshot, strict TypeScript, 605 mobile tests and an offline iOS JavaScript export passed. Selected backend tests also passed; database-dependent skips are documented. The exact upgraded snapshot has not received a full native build or end-to-end device validation. Later solo, drawing, theme and companion features are source implementations and should only be shown as working interactions where the final recording actually demonstrates them.

## What is next

The next priorities are validating the upgraded client and backend together on devices, broadening educational evaluation and curriculum coverage, and completing production deployment and store configuration. This is a development-stage Next Gen entry.

## Built with

TypeScript, React Native, Expo, Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Supabase Auth, RevenueCat, React Native SVG, and server-side AI adapters.

---

## Editor evidence notes — exclude this section from the public description

- The narrative deliberately does not invent a first-person biography, school, contributor name or personal lesson. Add a personal statement only in the owner's own words if the form asks for one.
- Organizer Perttu Lähteenlahti confirmed that Test Store is sufficient for Next Gen in [this official discussion](https://revenuecat-shipaton-2026.devpost.com/forum_topics/44695-next-gen-eligibility-is-a-test-store-only-purchase-sufficient). This establishes the category interpretation, not proof that the latest recorded purchase flow works.
- The same discussion includes an unanswered entrant report of a mandatory store-release checkbox. The current signed-in form has not been inspected here. If that field appears without a Next Gen exception, resolve it with the organizer rather than assert a store release that did not occur.
- Final video, screenshot, icon and public source URLs are not supplied by this file. Do not publish placeholders or claim unpublished links exist.
