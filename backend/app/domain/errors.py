class RoomApplicationError(Exception):
    """Base class for expected room application failures."""


class AuthenticationConfigurationError(RuntimeError):
    """Raised when backend Supabase verification configuration is unusable."""


class AuthenticationRequiredError(RoomApplicationError):
    """Raised when a protected request has no bearer token."""


class InvalidAuthTokenError(RoomApplicationError):
    """Raised when a bearer token cannot be verified as a Supabase identity."""


class UserProfileRequiredError(RoomApplicationError):
    """Raised when an authenticated identity has no MindMesh profile."""


class AccountDeletedError(RoomApplicationError):
    """Raised when a verified identity belongs to a deleted local account."""

    code = "account_deleted"
    message = "This MindMesh account has been deleted."


class AccountSuspendedError(RoomApplicationError):
    """Raised when a verified identity is temporarily restricted."""

    code = "account_suspended"
    message = "Your MindMesh account is currently unavailable."


class InvalidDisplayNameError(RoomApplicationError):
    """Raised when a profile name violates the shared display-name policy."""

    code = "invalid_display_name"
    message = "Choose a different display name."


class RecentAuthenticationRequiredError(RoomApplicationError):
    """Raised when a destructive action lacks recent-authentication proof."""

    code = "recent_authentication_required"
    message = "Sign in again before deleting your MindMesh account."


class AccountDeletionBlockedActiveQuizError(RoomApplicationError):
    """Raised when deletion would remove a participant from a live quiz."""

    code = "account_deletion_blocked_active_quiz"
    message = "Account deletion is unavailable while you are in an active quiz."


class AccountDeletionUnavailableError(RoomApplicationError):
    """Raised when the account-deletion service is not configured."""

    code = "account_deletion_unavailable"
    message = "Account deletion is temporarily unavailable."


class SafetyReportNotAllowedError(RoomApplicationError):
    """Raised when a report lacks a verified shared-room context."""

    code = "safety_report_not_allowed"
    message = "This safety report could not be submitted."


class SafetyReportUnavailableError(RoomApplicationError):
    """Raised when the safety-report service is not configured."""

    code = "safety_report_unavailable"
    message = "Safety reporting is temporarily unavailable."


class UserNotFoundError(RoomApplicationError):
    """Raised when a referenced MindMesh user does not exist."""


class RoomOwnerRequiredError(RoomApplicationError):
    """Raised when an authenticated user is not the room owner."""

    code = "room_owner_required"
    message = "Only the room host can perform this action."


class RoomOwnerMustCloseError(RoomApplicationError):
    """Raised when a room owner attempts the ordinary member-leave path."""

    code = "room_owner_must_close"
    message = "The room host must close the room instead of leaving it."


class RoomClosedError(RoomApplicationError):
    """Raised when an operation requires a room that is still open."""

    code = "room_closed"
    message = "This room is closed."


class RoomCreationError(RoomApplicationError):
    """Base class for failures while creating a room."""


class ProRequiredError(RoomApplicationError):
    """Raised when a server-owned operation requires active Pro access."""

    code = "pro_required"
    message = "MindMesh Pro is required for rooms larger than 8 members."


class PremiumVerificationUnavailableError(RoomApplicationError):
    """Raised when premium access cannot be verified safely."""

    code = "premium_verification_unavailable"
    message = "We couldn't verify MindMesh Pro right now. Try again shortly."


class InvalidRoomDataError(RoomApplicationError):
    """Raised when service-level room invariants are violated."""


class RoomNotFoundError(RoomApplicationError):
    """Raised when a requested room does not exist."""


class RoomJoinUnavailableError(RoomApplicationError):
    """Safe public failure for a room-code join that cannot proceed."""

    code = "room_join_unavailable"
    message = "This room is not available to join."


class RoomJoinRateLimitedError(RoomApplicationError):
    """Raised when one identity has exhausted failed join attempts."""

    code = "room_join_rate_limited"
    message = "Too many join attempts. Try again shortly."

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(self.message)


class DuplicateRoomIdError(RoomCreationError):
    """Raised when a room ID collides with an existing room."""


class DuplicateJoinCodeError(RoomCreationError):
    """Raised when a join code collides with an existing room."""


class JoinCodeGenerationError(RoomCreationError):
    """Raised when a unique join code cannot be generated."""


class DuplicateMembershipError(RoomApplicationError):
    """Raised when a room/user membership pair already exists."""


class RoomMembershipError(RoomApplicationError):
    """Base class for safe membership conflict responses."""

    code = "membership_conflict"
    message = "The membership request could not be completed."


class AlreadyRoomMemberError(RoomMembershipError):
    """Raised when a user tries to join the same room twice."""

    code = "already_room_member"
    message = "User is already a member of this room."


class UserAlreadyInAnotherRoomError(RoomMembershipError):
    """Raised when a user already belongs to another active room."""

    code = "user_already_in_another_room"
    message = "User is already in another room."


class RoomFullError(RoomMembershipError):
    """Raised when a room has reached its configured capacity."""

    code = "room_full"
    message = "Room is full."


class NotRoomMemberError(RoomApplicationError):
    """Raised when a user accesses private state without active membership."""

    code = "not_room_member"
    message = "You are not an active member of this room."


class QuizSessionError(RoomApplicationError):
    """Base class for expected authoritative quiz-session failures."""

    code = "quiz_session_error"
    message = "The quiz session request could not be completed."


class SessionAlreadyActiveError(QuizSessionError):
    """Raised when a room already has a non-finished quiz session."""

    code = "session_already_active"
    message = "This room already has an active quiz session."


class SessionStartConflictError(QuizSessionError):
    """Raised when a concurrent identity change prevents a safe session start."""

    code = "session_start_conflict"
    message = "The quiz could not start while room membership was changing."


class ParticipantsNotReadyError(QuizSessionError):
    """Raised when a non-host active member has not confirmed readiness."""

    code = "participants_not_ready"
    message = "All non-host room members must be ready before starting."


class InsufficientParticipantsError(QuizSessionError):
    """Raised when a room has fewer than the minimum session participants."""

    code = "insufficient_participants"
    message = "At least two active room members are required to start."


class SessionNotActiveError(QuizSessionError):
    """Raised when an operation requires a current non-finished session."""

    code = "session_not_active"
    message = "There is no active quiz session for this room."


class InvalidSessionTransitionError(QuizSessionError):
    """Raised when a persisted session state cannot legally transition."""

    code = "invalid_session_transition"
    message = "The quiz session cannot make that state transition."


class NotSessionParticipantError(QuizSessionError):
    """Raised when a user is not part of the session snapshot."""

    code = "not_session_participant"
    message = "You are not a participant in this quiz session."


class QuestionNotOpenError(QuizSessionError):
    """Raised when an answer is submitted outside QUESTION_OPEN."""

    code = "question_not_open"
    message = "The current question is not accepting answers."


class StaleSessionQuestionError(QuizSessionError):
    """Raised when an answer targets a question other than the current one."""

    code = "stale_session_question"
    message = "That question is no longer the current session question."


class AnswerTooLateError(QuizSessionError):
    """Raised when the database deadline has passed."""

    code = "answer_too_late"
    message = "The answer deadline has passed."


class AnswerAlreadySubmittedError(QuizSessionError):
    """Raised when a participant submits a different second answer."""

    code = "answer_already_submitted"
    message = "An answer has already been submitted for this question."


class InvalidOptionError(QuizSessionError):
    """Raised when a selected option is not part of the question snapshot."""

    code = "invalid_option"
    message = "That option is not valid for the current question."


class InvalidAnswerTextError(QuizSessionError):
    """Raised when a typed answer is blank or exceeds the response bound."""

    code = "invalid_answer_text"
    message = "The answer text must be nonblank and at most 1000 characters."


class QuestionBankUnavailableError(QuizSessionError):
    """Raised when the canonical session question bank is unusable."""

    code = "question_bank_unavailable"
    message = "The configured quiz question bank is unavailable."


class PreparationConflictError(RoomApplicationError):
    """Raised when a concurrent preparation request conflicts in the same room."""

    code = "preparation_conflict"
    message = "Another quiz preparation is already in progress for this room."


class QuizNotReadyError(QuizSessionError):
    """Raised when starting an adaptive room whose quiz is not in READY state."""

    code = "quiz_not_ready"
    message = "Quiz content is still preparing or generation failed."


class PreparationFailedError(RoomApplicationError):
    """Raised when quiz content generation fails."""

    code = "preparation_failed"
    message = "Failed to generate quiz content."


class AiGenerationUnavailableError(RoomApplicationError):
    """Raised when OpenAI generation is not configured."""

    code = "ai_generation_unavailable"
    message = "AI quiz generation is currently unavailable."
