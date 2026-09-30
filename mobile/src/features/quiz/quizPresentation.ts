import { MAX_WRITTEN_ANSWER_LENGTH } from "./adaptiveQuiz";
import type {
  AdaptiveQuestionType,
  CanonicalUuid,
  GradingStatus,
  LeaderboardEntryPayload,
  QuestionOptionPayload,
  QuizMode,
  RevealedViewerSubmissionPayload,
  ZonedIsoTimestamp,
} from "../../realtime/protocol";
import type { SessionState } from "../session/sessionState";

export type QuizSelectionState = {
  sessionQuestionId: CanonicalUuid | null;
  selectedOptionId: string | null;
  answerText: string;
};

export type QuizSelectionAction =
  | { type: "QUESTION_CHANGED"; sessionQuestionId: CanonicalUuid }
  | {
      type: "OPTION_SELECTED";
      sessionQuestionId: CanonicalUuid;
      selectedOptionId: string;
    }
  | {
      type: "TEXT_CHANGED";
      sessionQuestionId: CanonicalUuid;
      text: string;
    }
  | { type: "SELECTION_CLEARED" };

export const initialQuizSelectionState: QuizSelectionState = {
  sessionQuestionId: null,
  selectedOptionId: null,
  answerText: "",
};

export function quizSelectionReducer(
  state: QuizSelectionState,
  action: QuizSelectionAction,
): QuizSelectionState {
  switch (action.type) {
    case "QUESTION_CHANGED":
      if (state.sessionQuestionId === action.sessionQuestionId) {
        return state;
      }
      return {
        sessionQuestionId: action.sessionQuestionId,
        selectedOptionId: null,
        answerText: "",
      };
    case "OPTION_SELECTED":
      return {
        sessionQuestionId: action.sessionQuestionId,
        selectedOptionId: action.selectedOptionId,
        answerText: "",
      };
    case "TEXT_CHANGED":
      return {
        sessionQuestionId: action.sessionQuestionId,
        selectedOptionId: null,
        answerText: action.text,
      };
    case "SELECTION_CLEARED":
      return initialQuizSelectionState;
  }
}

export type QuizCountdownInput = {
  serverTime: ZonedIsoTimestamp;
  deadline: ZonedIsoTimestamp;
};

export function getQuizCountdownInput(
  state: SessionState,
): QuizCountdownInput | null {
  const snapshot = state.snapshot;
  if (snapshot?.status === "QUESTION_OPEN") {
    return {
      serverTime: snapshot.server_time,
      deadline: snapshot.closes_at,
    };
  }
  if (snapshot?.status === "QUESTION_REVEAL") {
    return {
      serverTime: snapshot.server_time,
      deadline: snapshot.reveal_ends_at,
    };
  }
  return null;
}

type QuizQuestionPresentationBase = {
  sessionId: CanonicalUuid;
  sessionQuestionId: CanonicalUuid;
  prompt: string;
  options: QuestionOptionPayload[];
  questionNumber: number;
  totalQuestions: number;
  questionType: AdaptiveQuestionType;
  maxMarks: number;
  originalExtract: string | null;
  quizMode: QuizMode;
  connected: boolean;
};

export type OpenQuizSubmissionStatus = "draft" | "submitting" | "submitted";

export type OpenQuizPresentation = QuizQuestionPresentationBase & {
  status: "question-open";
  selectedOptionId: string | null;
  draftText: string;
  submissionStatus: OpenQuizSubmissionStatus;
  ownGradingStatus: GradingStatus | null;
  canInteract: boolean;
  canSubmit: boolean;
};

export type GradingQuizPresentation = QuizQuestionPresentationBase & {
  status: "question-grading";
  ownSelectedOptionId: string | null;
  ownAnswerText: string | null;
  ownGradingStatus: GradingStatus | null;
  gradingRetryNeeded: boolean;
  canRetryGrading: boolean;
};

export type RevealQuizPresentation = QuizQuestionPresentationBase & {
  status: "question-reveal";
  correctOptionId: string | null;
  workedExplanation: string;
  viewerSubmission: RevealedViewerSubmissionPayload | null;
  leaderboard: LeaderboardEntryPayload[];
};

export type QuizPresentation =
  | OpenQuizPresentation
  | GradingQuizPresentation
  | RevealQuizPresentation;

function selectedLocalOption(
  selection: QuizSelectionState,
  sessionQuestionId: CanonicalUuid,
  options: QuestionOptionPayload[],
): string | null {
  if (
    selection.sessionQuestionId !== sessionQuestionId ||
    selection.selectedOptionId === null ||
    !options.some((option) => option.id === selection.selectedOptionId)
  ) {
    return null;
  }
  return selection.selectedOptionId;
}

function localDraftText(
  selection: QuizSelectionState,
  sessionQuestionId: CanonicalUuid,
): string {
  if (selection.sessionQuestionId !== sessionQuestionId) {
    return "";
  }
  return selection.answerText;
}

function buildBase(
  state: SessionState,
  snapshot: Extract<
    NonNullable<SessionState["snapshot"]>,
    { status: "QUESTION_OPEN" | "QUESTION_GRADING" | "QUESTION_REVEAL" }
  >,
): QuizQuestionPresentationBase {
  const question = snapshot.question;
  return {
    sessionId: snapshot.session_id,
    sessionQuestionId: question.session_question_id,
    prompt: question.prompt,
    options: question.options,
    questionNumber: snapshot.current_question_number,
    totalQuestions: snapshot.total_question_count,
    questionType: question.question_type,
    maxMarks: question.max_marks,
    originalExtract: question.original_extract,
    quizMode: snapshot.quiz_mode,
    connected: state.connectionStage === "established",
  };
}

function acceptedChoiceFor(
  state: SessionState,
  sessionId: CanonicalUuid,
  sessionQuestionId: CanonicalUuid,
): { selectedOptionId: string | null; answerText: string | null } | null {
  const snapshot = state.snapshot;
  if (
    snapshot === null ||
    snapshot.session_id !== sessionId ||
    (snapshot.status !== "QUESTION_OPEN" &&
      snapshot.status !== "QUESTION_GRADING")
  ) {
    return null;
  }
  const submission = snapshot.viewer_submission;
  if (
    submission !== null &&
    submission.session_question_id === sessionQuestionId
  ) {
    return {
      selectedOptionId: submission.selected_option_id,
      answerText: submission.answer_text,
    };
  }
  const acknowledgement = state.acknowledgedAnswer;
  if (
    acknowledgement !== null &&
    acknowledgement.sessionId === sessionId &&
    acknowledgement.sessionQuestionId === sessionQuestionId
  ) {
    return {
      selectedOptionId: acknowledgement.selectedOptionId,
      answerText: acknowledgement.answerText,
    };
  }
  return null;
}

function acceptedGradingStatusFor(
  state: SessionState,
  sessionId: CanonicalUuid,
  sessionQuestionId: CanonicalUuid,
): GradingStatus | null {
  const snapshot = state.snapshot;
  if (snapshot !== null && snapshot.session_id === sessionId) {
    const submission = snapshot.viewer_submission;
    if (
      submission !== null &&
      submission.session_question_id === sessionQuestionId
    ) {
      return submission.grading_status;
    }
  }
  const acknowledgement = state.acknowledgedAnswer;
  if (
    acknowledgement !== null &&
    acknowledgement.sessionId === sessionId &&
    acknowledgement.sessionQuestionId === sessionQuestionId
  ) {
    return acknowledgement.gradingStatus;
  }
  return null;
}

function buildOpenPresentation(
  state: SessionState,
  selection: QuizSelectionState,
  countdownExpired: boolean,
): OpenQuizPresentation | null {
  const snapshot = state.snapshot;
  if (
    snapshot === null ||
    state.roomId === null ||
    snapshot.room_state.room_id !== state.roomId ||
    snapshot.status !== "QUESTION_OPEN"
  ) {
    return null;
  }
  const base = buildBase(state, snapshot);
  const question = snapshot.question;

  const pendingAnswer =
    state.pendingCommand?.kind === "answer" &&
    state.pendingCommand.sessionId === snapshot.session_id &&
    state.pendingCommand.sessionQuestionId === question.session_question_id
      ? state.pendingCommand
      : null;
  const accepted = acceptedChoiceFor(
    state,
    snapshot.session_id,
    question.session_question_id,
  );
  const acceptedOptionId = accepted?.selectedOptionId ?? null;
  const acceptedText = accepted?.answerText ?? null;
  const selectedOptionId =
    acceptedOptionId ??
    pendingAnswer?.selectedOptionId ??
    (question.question_type === "MULTIPLE_CHOICE"
      ? selectedLocalOption(
          selection,
          question.session_question_id,
          question.options,
        )
      : null);
  const draftText =
    acceptedText ??
    pendingAnswer?.answerText ??
    (question.question_type === "MULTIPLE_CHOICE"
      ? ""
      : localDraftText(selection, question.session_question_id));
  const submissionStatus: OpenQuizSubmissionStatus =
    accepted !== null
      ? "submitted"
      : pendingAnswer !== null
        ? "submitting"
        : "draft";
  const canInteract =
    state.connectionStage === "established" &&
    state.pendingSnapshotRequest === null &&
    !countdownExpired &&
    submissionStatus === "draft";
  const textValid =
    draftText.trim().length > 0 &&
    draftText.length <= MAX_WRITTEN_ANSWER_LENGTH;
  return {
    ...base,
    status: "question-open",
    selectedOptionId,
    draftText,
    submissionStatus,
    ownGradingStatus:
      accepted !== null
        ? acceptedGradingStatusFor(
            state,
            snapshot.session_id,
            question.session_question_id,
          )
        : null,
    canInteract,
    canSubmit:
      canInteract &&
      (question.question_type === "MULTIPLE_CHOICE"
        ? selectedOptionId !== null
        : textValid),
  };
}

function buildGradingPresentation(
  state: SessionState,
): GradingQuizPresentation | null {
  const snapshot = state.snapshot;
  if (
    snapshot === null ||
    state.roomId === null ||
    snapshot.room_state.room_id !== state.roomId ||
    snapshot.status !== "QUESTION_GRADING"
  ) {
    return null;
  }
  const base = buildBase(state, snapshot);
  const question = snapshot.question;
  const accepted = acceptedChoiceFor(
    state,
    snapshot.session_id,
    question.session_question_id,
  );
  // The retry signal is an aggregate over every accepted answer on the
  // current question: another participant's UNAVAILABLE answer makes the
  // host control appear even when the viewer's own answer is final.
  // Members never receive the control; the server enforces host-only retry.
  const gradingRetryNeeded = snapshot.grading_retry_needed;
  return {
    ...base,
    status: "question-grading",
    ownSelectedOptionId: accepted?.selectedOptionId ?? null,
    ownAnswerText: accepted?.answerText ?? null,
    ownGradingStatus: acceptedGradingStatusFor(
      state,
      snapshot.session_id,
      question.session_question_id,
    ),
    gradingRetryNeeded,
    canRetryGrading:
      gradingRetryNeeded &&
      state.connectionStage === "established" &&
      state.roomState?.viewer_role === "host" &&
      state.pendingCommand === null &&
      state.pendingRoomExit === null,
  };
}

function buildRevealPresentation(
  state: SessionState,
): RevealQuizPresentation | null {
  const snapshot = state.snapshot;
  if (
    snapshot === null ||
    state.roomId === null ||
    snapshot.room_state.room_id !== state.roomId ||
    snapshot.status !== "QUESTION_REVEAL"
  ) {
    return null;
  }
  const base = buildBase(state, snapshot);
  return {
    ...base,
    status: "question-reveal",
    correctOptionId: snapshot.question.correct_option_id,
    workedExplanation: snapshot.question.worked_explanation,
    viewerSubmission: snapshot.viewer_submission,
    leaderboard: snapshot.leaderboard,
  };
}

export function buildQuizPresentation(
  state: SessionState,
  selection: QuizSelectionState,
  countdownExpired: boolean,
): QuizPresentation | null {
  const snapshot = state.snapshot;
  if (snapshot === null || state.roomId === null) {
    return null;
  }
  switch (snapshot.status) {
    case "QUESTION_OPEN":
      return buildOpenPresentation(state, selection, countdownExpired);
    case "QUESTION_GRADING":
      return buildGradingPresentation(state);
    case "QUESTION_REVEAL":
      return buildRevealPresentation(state);
    default:
      return null;
  }
}

export type QuizOptionAppearance =
  | "default"
  | "selected"
  | "correct"
  | "incorrect-selected";

export function getQuizOptionAppearance(
  presentation: QuizPresentation,
  optionId: string,
): QuizOptionAppearance {
  if (presentation.status === "question-open") {
    return presentation.selectedOptionId === optionId ? "selected" : "default";
  }
  if (presentation.status === "question-grading") {
    return presentation.ownSelectedOptionId === optionId
      ? "selected"
      : "default";
  }
  if (
    presentation.correctOptionId !== null &&
    presentation.correctOptionId === optionId
  ) {
    return "correct";
  }
  if (presentation.viewerSubmission?.selected_option_id === optionId) {
    return "incorrect-selected";
  }
  return "default";
}

export function getSubmissionStatusLabel(
  status: OpenQuizSubmissionStatus,
): string {
  switch (status) {
    case "draft":
      return "Submit Answer";
    case "submitting":
      return "Submitting...";
    case "submitted":
      return "Answer submitted";
  }
}
