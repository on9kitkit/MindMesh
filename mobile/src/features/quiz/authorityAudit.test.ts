import assert from "node:assert/strict";
import {
  existsSync,
  readFileSync,
  readdirSync,
  statSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const mobileDirectory = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../..",
);

function productionTypeScriptFiles(directory: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(directory)) {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) {
      files.push(...productionTypeScriptFiles(path));
    } else if (
      (name.endsWith(".ts") || name.endsWith(".tsx")) &&
      !name.endsWith(".test.ts")
    ) {
      files.push(path);
    }
  }
  return files;
}

test("production contains no competing local quiz engine", () => {
  const productionSource = [
    ...productionTypeScriptFiles(join(mobileDirectory, "app")),
    ...productionTypeScriptFiles(join(mobileDirectory, "src")),
  ]
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  for (const forbidden of [
    "QuizFlowProvider",
    "useQuizFlow",
    "mockData",
    "mockQuestions",
    "mockOpponent",
    "Mock opponent",
    "calculateQuizResult",
    "currentQuestionIndex",
    "START_QUIZ",
    "RESTART_QUIZ",
  ]) {
    assert.equal(
      productionSource.includes(forbidden),
      false,
      `production must not contain ${forbidden}`,
    );
  }
});

test("legacy local quiz authority files were removed", () => {
  for (const relativePath of [
    "src/data/mockData.ts",
    "src/features/quiz/QuizFlowContext.tsx",
    "src/features/quiz/quizFlow.ts",
    "src/utils/scoring.ts",
    "src/types/index.ts",
  ]) {
    assert.equal(existsSync(join(mobileDirectory, relativePath)), false);
  }
});

test("Quiz and Results consume SessionProvider without local navigation authority", () => {
  const quizSource = readFileSync(join(mobileDirectory, "app/quiz.tsx"), "utf8");
  const resultsSource = readFileSync(
    join(mobileDirectory, "app/results.tsx"),
    "utf8",
  );
  assert.equal(quizSource.includes("useSession"), true);
  assert.equal(resultsSource.includes("useSession"), true);
  assert.equal(quizSource.includes("router.replace"), false);
  assert.equal(resultsSource.includes("router.replace"), false);
  assert.equal(resultsSource.includes(".sort("), false);
});
