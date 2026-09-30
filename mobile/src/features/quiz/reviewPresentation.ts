import {
  parseEnrichedWrittenFeedback,
  type EnrichedWrittenFeedback,
} from "../../feedback/gradingFeedback";
import { parseViewerFeedbackSummary } from "../../realtime/protocol";
import type {
  ReviewQuestionItem,
  SessionReviewResponse,
} from "../../api/schemas";
import { getSubjectLabel, getTopicLabel } from "./adaptiveQuiz";

export type ReviewItemPresentation = {
  sessionQuestionId: string;
  position: number;
  questionNumber: number;
  questionType: string;
  questionTypeLabel: string;
  prompt: string;
  maxMarks: number;
  options: Array<{ id: string; label: string }>;
  correctOptionLabel: string | null;
  workedExplanation: string;
  originalExtract: string | null;
  ownResponseLabel: string | null;
  earnedMarks: number;
  marksLabel: string;
  feedbackSummary: string | null;
  enrichedFeedback: EnrichedWrittenFeedback | null;
  awardedCriterionCount: number;
};

export type ReviewPresentation = {
  sessionId: string;
  roomId: string;
  totalEarnedMarks: number;
  totalAvailableMarks: number;
  totalsLabel: string;
  questions: ReviewItemPresentation[];
};

function questionTypeLabel(questionType: string): string {
  switch (questionType) {
    case "MULTIPLE_CHOICE":
      return "Multiple choice";
    case "NUMERICAL":
      return "Numerical";
    case "WRITTEN":
      return "Written";
    default:
      return questionType;
  }
}

function ownResponseLabel(item: ReviewQuestionItem): string | null {
  if (item.selected_option_id !== null) {
    const option = item.options.find(
      (entry) => entry.id === item.selected_option_id,
    );
    return option?.label ?? "Unavailable";
  }
  return item.answer_text;
}

export function presentReviewItem(item: ReviewQuestionItem): ReviewItemPresentation {
  const correctOption =
    item.correct_option_id === null
      ? null
      : (item.options.find((entry) => entry.id === item.correct_option_id)
          ?.label ?? null);
  let enrichedFeedback: EnrichedWrittenFeedback | null = null;
  if (Object.keys(item.feedback).length > 0) {
    try {
      enrichedFeedback = parseEnrichedWrittenFeedback(item.feedback);
    } catch {
      enrichedFeedback = null;
    }
  }
  return {
    sessionQuestionId: item.session_question_id,
    position: item.position,
    questionNumber: item.position + 1,
    questionType: item.question_type,
    questionTypeLabel: questionTypeLabel(item.question_type),
    prompt: item.prompt,
    maxMarks: item.max_marks,
    options: item.options.map((option) => ({ ...option })),
    correctOptionLabel: correctOption,
    workedExplanation: item.worked_explanation,
    originalExtract: item.original_extract,
    ownResponseLabel: ownResponseLabel(item),
    earnedMarks: item.earned_marks,
    marksLabel: `${item.earned_marks}/${item.max_marks} marks`,
    feedbackSummary: parseViewerFeedbackSummary(item.feedback),
    enrichedFeedback,
    awardedCriterionCount: item.awarded_criterion_ids.length,
  };
}

export function buildReviewPresentation(
  review: SessionReviewResponse,
): ReviewPresentation {
  return {
    sessionId: review.session_id,
    roomId: review.room_id,
    totalEarnedMarks: review.total_earned_marks,
    totalAvailableMarks: review.total_available_marks,
    totalsLabel: `${review.total_earned_marks}/${review.total_available_marks} marks`,
    questions: review.questions.map(presentReviewItem),
  };
}

export function describeRoomSelection(
  quizSubject: string | null,
  quizTopic: string | null,
): string | null {
  if (quizSubject === null || quizTopic === null) {
    return null;
  }
  const subjectLabel = getSubjectLabel(quizSubject) ?? quizSubject;
  const topicLabel = getTopicLabel(quizTopic) ?? quizTopic;
  return `${subjectLabel} · ${topicLabel}`;
}
