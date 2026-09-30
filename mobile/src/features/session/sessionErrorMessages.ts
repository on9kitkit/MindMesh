import type { StudyRoomRealtimeError } from "../../realtime/errors";

function commandErrorMessage(code: string | undefined): string {
  switch (code) {
    case "session_already_active":
      return "This quiz has already started.";
    case "room_owner_required":
      return "Only the room host can start the quiz.";
    case "participants_not_ready":
      return "Every non-host member must be ready before the quiz starts.";
    case "insufficient_participants":
      return "At least two participants are required to start the quiz.";
    case "answer_too_late":
      return "The answer window has closed.";
    case "answer_already_submitted":
      return "Your answer is already recorded.";
    case "stale_session_question":
      return "The quiz has moved to another question.";
    case "question_not_open":
      return "This question is not open for answers.";
    case "invalid_option":
      return "That answer option is no longer available.";
    case "session_not_active":
      return "The quiz session is no longer active.";
    case "quiz_not_ready":
      return "Quiz content is not ready yet. Generate the quiz and wait for it to be ready.";
    case "preparation_conflict":
      return "Quiz preparation is already in progress for this room.";
    case "preparation_failed":
      return "Quiz generation failed. Please try generating again.";
    case "ai_generation_unavailable":
      return "AI quiz generation is currently unavailable. Please try again later.";
    case "not_room_member":
      return "You are no longer a member of this room.";
    case "room_not_found":
      return "This room is no longer available.";
    case "room_closed":
      return "This room is closed.";
    case "room_left":
      return "You left this room.";
    case "room_owner_must_close":
      return "The room host must close the room instead of leaving it.";
    case "account_deleted":
      return "Your StudyRoom account has been deleted. Please sign in again.";
    case "account_suspended":
      return "Your StudyRoom account is currently unavailable. Open Support & Safety for help.";
    case "rate_limited":
      return "Too many requests. Please wait a moment and try again.";
    case "connection_limit_reached":
      return "The realtime connection limit has been reached.";
    case "internal_error":
      return "The StudyRoom server could not complete that request.";
    default:
      return "The room update was rejected. Please try again.";
  }
}

export function getSessionErrorMessage(
  error: StudyRoomRealtimeError | null,
): string {
  if (error === null) {
    return "Something went wrong. Please try again.";
  }

  switch (error.kind) {
    case "authentication":
      return "Your session has expired. Please sign in again.";
    case "membership-or-room":
      if (error.code === "not_room_member") {
        return "You are no longer a member of this room.";
      }
      if (error.code === "room_left") {
        return "You left this room.";
      }
      return error.code === "room_closed"
        ? "This room is closed."
        : "This room is no longer available.";
    case "connection-limit":
      return "The realtime connection limit has been reached.";
    case "network":
      return "Could not reach the StudyRoom server.";
    case "reconnect-exhausted":
      return "The room connection could not be restored automatically.";
    case "command-rejected":
      return commandErrorMessage(error.code);
    case "configuration":
      return "StudyRoom server configuration is invalid.";
    case "protocol-incompatibility":
      return "This app is not compatible with the server's realtime protocol.";
    case "malformed-server-message":
      return "The StudyRoom server returned an invalid realtime update.";
    case "command-unavailable":
      return "That room action is not available right now.";
  }
}
