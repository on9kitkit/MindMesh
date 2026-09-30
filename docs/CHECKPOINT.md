# MindMesh public-source checkpoint — 29 September 2026

This directory is a sanitized, no-music source candidate, not a production release. Visible app branding is MindMesh / MindMesh Pro; technical StudyRoom auth/native/storage identities are intentionally retained. The crow icon and final video are not included.

Application source inherits the reviewed source handoff plus the 30 September visible-branding update. Lockfiles and migrations are unchanged. See [validation](../VALIDATION.md) for attributed checks and native/runtime limits, [asset rights](../ASSET_RIGHTS.md), and [publication actions](../PUBLICATION_CHECKLIST.md).

## 30 September: visible-branding update

Owner authorized changing visible StudyRoom branding to MindMesh, including Pro, then committing/pushing. Static app copy and backend user messages are renamed; dynamic subscription title/description presentation is normalized locally. MindMesh service names are reserved on both client/server alongside legacy aliases. Generic study-room copy, identifiers, support mailbox, licence attribution, auth links and saved data keys remain unchanged. Matching line-level source changes were made in Preview and accepted UI without resetting their unrelated work.

Strict TypeScript and the full default mobile suite pass: 606 tests, zero failures/skips. No services, provider/account changes, native build, installation or device validation were performed. RevenueCat-managed paywall/store metadata remains outside the source-only rename.

On 30 September 2026 the owner authorized a fresh PUBLIC `on9kitkit/MindMesh` repository, initial commit and push with a GitHub noreply identity, and confirmed contributor permission for the included project source/code-drawn visuals under the existing MIT licence. This changes publication status only, not application code or validation claims. Do not import private history, populated environment files, data, installed dependencies or native outputs. Devpost submission is still separate; absent media rights and documented dependency exceptions remain open.
