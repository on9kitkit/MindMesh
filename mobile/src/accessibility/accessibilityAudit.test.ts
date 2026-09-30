import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const mobileDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../..",
);

function source(relativePath: string): string {
  return readFileSync(join(mobileDirectory, relativePath), "utf8");
}

test("critical-path text inputs have programmatic labels", () => {
  const studioPrimitives = source("src/components/studio/StudioPrimitives.tsx");
  assert.match(studioPrimitives, /accessibilityLabel=\{label\}/);
  for (const route of [
    "app/sign-in.tsx",
    "app/sign-up.tsx",
    "app/index.tsx",
    "app/account.tsx",
  ]) {
    const routeSource = source(route);
    const inputBlocks = routeSource.match(/<TextInput[\s\S]*?\/>/g) ?? [];
    if (inputBlocks.length === 0) {
      assert.match(routeSource, /<StudioTextField/);
      continue;
    }
    for (const input of inputBlocks) {
      assert.match(input, /accessibilityLabel="[^"]+"/);
    }
  }
});

test("shared interactive controls expose labels, roles, states, and touch targets", () => {
  const button = source("src/components/AppButton.tsx");
  assert.match(button, /accessibilityLabel=\{label\}/);
  assert.match(button, /accessibilityRole="button"/);
  assert.match(button, /accessibilityState=\{\{ disabled \}\}/);
  assert.match(button, /minHeight: 50/);

  const option = source("src/components/QuizOption.tsx");
  assert.match(option, /accessibilityLabel=\{option\.label\}/);
  assert.match(option, /accessibilityRole="radio"/);
  assert.match(option, /accessibilityState=\{\{ checked: selected, disabled \}\}/);
  assert.match(option, /minHeight: 52/);
});

test("realtime status and result changes are screen-reader discoverable", () => {
  for (const route of [
    "app/waiting-room.tsx",
    "app/quiz.tsx",
    "app/results.tsx",
  ]) {
    assert.match(source(route), /accessibilityLiveRegion="polite"/);
  }

  const quiz = source("app/quiz.tsx");
  assert.match(quiz, /Answer submitted\./);
  assert.match(quiz, /The answer window has closed\./);
  assert.match(quiz, /"Correct"/);
  assert.match(quiz, /"Incorrect"/);

  const leaderboard = source("src/components/LeaderboardRow.tsx");
  assert.match(leaderboard, /isCurrentUser \? "You · " : ""/);
});

test("room lifecycle controls and confirmations remain accessible", () => {
  const waitingRoom = source("app/waiting-room.tsx");
  assert.match(waitingRoom, /"Leave Room"/);
  assert.match(waitingRoom, /"Close Room"/);
  assert.match(waitingRoom, /Alert\.alert\(\s*"Close room\?"/);
  assert.match(waitingRoom, /Alert\.alert\(\s*"Leave room\?"/);
  assert.match(
    waitingRoom,
    /Closing the room removes every current member\. Completed quiz results will remain saved\./,
  );
  assert.match(waitingRoom, /accessibilityLiveRegion="polite"/);
  assert.match(waitingRoom, /disabled=\{lifecycleControl\.disabled\}/);
});

test("StudyRoom Pro entry and purchase controls are accessible", () => {
  const home = source("app/index.tsx");
  const pro = source("app/pro.tsx");
  assert.match(home, /label="Explore StudyRoom Pro"/);
  assert.match(pro, /label=.*Open RevenueCat Paywall/);
  assert.match(pro, /label=.*Restore Purchases/);
  assert.match(pro, /Refresh Pro Status/);
  assert.match(pro, /disabled=\{!refreshAvailable\}/);
  assert.match(pro, /accessibilityLiveRegion="polite"/);
  assert.match(pro, /disabled=\{!purchaseAvailable\}/);
  assert.match(pro, /disabled=\{!restoreAvailable\}/);
});

test("account deletion controls are discoverable, destructive, and recoverable", () => {
  const home = source("app/index.tsx");
  const account = source("app/account.tsx");
  assert.match(home, /label="Open Account & settings"/);
  assert.match(account, /label="Delete Account"/);
  assert.match(account, /variant="destructive"/);
  assert.match(account, /Type DELETE to confirm account deletion/);
  assert.match(account, /Current password for account deletion/);
  assert.match(account, /accessibilityRole="alert"/);
  assert.match(account, /accessibilityLiveRegion="polite"/);
  assert.match(account, /label="Sign out"/);
});

test("privacy, support, and safety reporting controls are discoverable", () => {
  const privacy = source("app/privacy.tsx");
  const support = source("app/support.tsx");
  const report = source("app/report.tsx");
  assert.match(privacy, /Privacy/);
  assert.match(support, /label="Contact Support"/);
  assert.match(support, /local emergency services/);
  assert.match(report, /accessibilityRole="radio"/);
  assert.match(report, /maxLength=\{500\}/);
  assert.match(report, /accessibilityLabel="Optional report details"/);
  assert.match(report, /accessibilityLiveRegion="polite"/);
});

test("adaptive quiz controls expose labels, states, and live regions", () => {
  const home = source("app/index.tsx");
  assert.match(home, /(?:accessibilityLabel="Total marks"|label="Total marks")/);
  assert.match(home, /keyboardType="number-pad"/);

  const waitingRoom = source("app/waiting-room.tsx");
  assert.match(waitingRoom, /"Generate Quiz"/);
  assert.match(waitingRoom, /"Retry Generation"/);
  assert.match(waitingRoom, /"Generating Quiz\.\.\."/);
  assert.match(waitingRoom, /ADAPTIVE GCSE PRACTICE/);

  const quiz = source("app/quiz.tsx");
  assert.match(quiz, /accessibilityLabel="Numerical answer"/);
  assert.match(quiz, /accessibilityLabel="Written answer"/);
  assert.match(quiz, /maxLength=\{MAX_WRITTEN_ANSWER_LENGTH\}/);
  assert.match(quiz, /"Retry Marking"/);
  assert.match(quiz, /Marking answers/);
  assert.match(quiz, /WHY THIS ANSWER/);

  const results = source("app/results.tsx");
  assert.match(results, /label="Review My Answers"/);
  assert.match(results, /Loading your review\.\.\./);
  assert.match(results, /accessibilityLiveRegion="polite"/);
  assert.match(results, /Awarded: /);
  assert.match(results, /Missing: /);
  assert.match(results, /full-mark answers/);
  assert.match(
    results,
    /formatCorrectAnswersLabel\(\s*row\.entry\.correct_answers,\s*"ADAPTIVE",?\s*\)/,
  );

  const reveal = source("app/quiz.tsx");
  assert.match(
    reveal,
    /formatCorrectAnswersLabel\(\s*entry\.correct_answers,\s*"ADAPTIVE",?\s*\)/,
  );

  const grading = source("app/quiz.tsx");
  assert.match(grading, /Marking in progress/);
  assert.match(grading, /The host can retry marking\./);
  assert.match(grading, /MARKING POINTS AWARDED/);
  assert.match(grading, /STILL MISSING/);
});

test("privacy notice discloses adaptive AI data use without absolute promises", () => {
  const privacy = source("app/privacy.tsx");
  assert.match(privacy, /Adaptive quizzes and AI marking/);
  assert.match(privacy, /bounded list of recent question prompts/);
  assert.match(privacy, /hidden marking rubric/);
  assert.match(privacy, /no account, profile,\s*room, or provider identifiers/);
  assert.match(privacy, /ask OpenAI not to store them/);
});

test("Standard and Large room controls expose selection and Pro requirements", () => {
  const home = source("app/index.tsx");
  const capacityOption = source("src/components/studio/StudioPrimitives.tsx");
  const capacityPresentation = source("src/appearance/studioPresentation.ts");
  assert.match(home, /title="Standard Room"/);
  assert.match(home, /up to 8 members/);
  assert.match(home, /title="Large Room"/);
  assert.match(home, /up to 20 members/);
  assert.match(home, /StudyRoom Pro required/);
  assert.match(
    home,
    /description=\{isPro \? "StudyRoom Pro · up to 20 members" : "StudyRoom Pro required · up to 20 members"\}/,
  );
  assert.match(
    home,
    /if \(!roomCapacityIsAvailable\(preset, isPro\)\) \{[\s\S]*router\.push\("\/pro"\)/,
  );
  assert.match(capacityOption, /accessibilityRole="radio"/);
  assert.match(
    capacityOption,
    /accessibilityState=\{\{ checked: selected, disabled \}\}/,
  );
  assert.match(
    capacityOption,
    /accessibilityLabel=\{\s*accessibilityLabel \?\?\s*\(trimmedDescription \? `\$\{title\}, \$\{trimmedDescription\}` : title\)\s*\}/,
  );
  assert.match(capacityPresentation, /minHeight: 64/);
});
