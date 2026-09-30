"""Translate authoritative domain snapshots into safe realtime events for v1 and v2 clients."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable, Literal
from uuid import UUID

from app.domain.quiz import (
    AnswerAcknowledgement,
    AuthoritativeSnapshot,
    LeaderboardEntry,
    PublicQuestion,
    QuizSession,
    QuizSessionStatus,
    RevealedQuestion,
    ViewerSubmission,
)
from app.realtime.close_codes import FORBIDDEN, NOT_FOUND
from app.realtime.manager import ConnectionManager
from app.realtime.protocol import (
    AnswerAcceptedEvent,
    AnswerAcceptedPayload,
    ConnectedEvent,
    ConnectedPayload,
    LeaderboardPayload,
    OpenOwnSubmissionPayload,
    OpenQuestionPayload,
    QuestionOpenedEvent,
    QuestionOpenedPayload,
    QuestionOptionPayload,
    QuestionRevealedEvent,
    QuestionRevealedPayload,
    RevealedOwnSubmissionPayload,
    RevealedQuestionPayload,
    RoomStateEvent,
    RoomStateParticipant,
    RoomStatePayload,
    ServerEvent,
    SessionFinishedEvent,
    SessionFinishedPayload,
    SessionReferencePayload,
    SessionStartedEvent,
    StateSnapshotEvent,
    StateSnapshotPayload,
    error_event,
    serialize_event,
)
from app.realtime.protocol_v2 import (
    PROTOCOL_VERSION_V2,
    AnswerAcceptedEventV2,
    AnswerAcceptedPayloadV2,
    ConnectedEventV2,
    ConnectedPayload as ConnectedPayloadV2,
    LeaderboardPayloadV2,
    OpenOwnSubmissionPayloadV2,
    OpenQuestionPayloadV2,
    QuestionOpenedEventV2,
    QuestionOpenedPayloadV2,
    QuestionOptionPayload as QuestionOptionPayloadV2,
    QuestionRevealedEventV2,
    QuestionRevealedPayloadV2,
    RevealedOwnSubmissionPayloadV2,
    RevealedQuestionPayloadV2,
    RoomStateEventV2,
    RoomStateParticipant as RoomStateParticipantV2,
    RoomStatePayloadV2,
    ServerEventV2,
    SessionFinishedEventV2,
    SessionFinishedPayloadV2,
    SessionReferencePayload as SessionReferencePayloadV2,
    SessionStartedEventV2,
    StateSnapshotEventV2,
    StateSnapshotPayloadV2,
    error_event_v2,
    serialize_event_v2,
)
from app.services.sessions import SessionService


# --- V1 Payload Builders ---


V1SnapshotStatus = Literal["QUESTION_OPEN", "QUESTION_REVEAL", "FINISHED"]
V2SnapshotStatus = Literal[
    "QUESTION_OPEN", "QUESTION_GRADING", "QUESTION_REVEAL", "FINISHED"
]
SessionSnapshotStatus = V2SnapshotStatus


def v1_snapshot_status(status: QuizSessionStatus) -> V1SnapshotStatus:
    """Map durable status onto the v1 wire union without type suppression."""
    # V1 clients do not expect QUESTION_GRADING; present as QUESTION_OPEN.
    if status == QuizSessionStatus.QUESTION_OPEN:
        return "QUESTION_OPEN"
    if status == QuizSessionStatus.QUESTION_REVEAL:
        return "QUESTION_REVEAL"
    if status == QuizSessionStatus.FINISHED:
        return "FINISHED"
    return "QUESTION_OPEN"


def v2_snapshot_status(status: QuizSessionStatus) -> V2SnapshotStatus:
    """Map durable status onto the explicit v2 wire union."""
    if status == QuizSessionStatus.QUESTION_OPEN:
        return "QUESTION_OPEN"
    if status == QuizSessionStatus.QUESTION_GRADING:
        return "QUESTION_GRADING"
    if status == QuizSessionStatus.QUESTION_REVEAL:
        return "QUESTION_REVEAL"
    return "FINISHED"


def session_status_value(status: QuizSessionStatus) -> SessionSnapshotStatus:
    """Map durable status onto the HTTP session union (v2-compatible)."""
    return v2_snapshot_status(status)


def room_state_payload(
    snapshot: AuthoritativeSnapshot,
    *,
    online_users: Iterable[UUID],
) -> RoomStatePayload:
    online = frozenset(online_users)
    return RoomStatePayload(
        room_id=snapshot.room.id,
        name=snapshot.room.name,
        join_code=snapshot.room.join_code,
        maximum_members=snapshot.room.maximum_members,
        viewer_role=snapshot.viewer_role.value,
        participants=[
            RoomStateParticipant(
                user_id=participant.user_id,
                display_name=participant.display_name,
                role="host" if participant.user_id == snapshot.room.owner_id else "member",
                ready=participant.ready,
                online=participant.user_id in online,
            )
            for participant in snapshot.participants
        ],
        viewer_ready=snapshot.viewer_ready,
    )


def open_question_payload(
    question: PublicQuestion,
    *,
    server_time: datetime,
) -> OpenQuestionPayload:
    return OpenQuestionPayload(
        session_question_id=question.id,
        prompt=question.prompt,
        options=[
            QuestionOptionPayload(id=option.id, label=option.label)
            for option in question.options
        ],
        question_number=question.question_number,
        total_questions=question.total_questions,
        closes_at=question.closes_at,
        server_time=server_time,
    )


def revealed_question_payload(
    question: RevealedQuestion,
    *,
    server_time: datetime,
) -> RevealedQuestionPayload:
    return RevealedQuestionPayload(
        session_question_id=question.id,
        prompt=question.prompt,
        options=[
            QuestionOptionPayload(id=option.id, label=option.label)
            for option in question.options
        ],
        question_number=question.question_number,
        total_questions=question.total_questions,
        closes_at=question.closes_at,
        server_time=server_time,
        correct_option_id=question.correct_option_id or "",
    )


def own_submission_payload(
    submission: ViewerSubmission | None,
    *,
    revealed: bool,
) -> OpenOwnSubmissionPayload | RevealedOwnSubmissionPayload | None:
    if submission is None:
        return None
    if not revealed:
        return OpenOwnSubmissionPayload(
            session_question_id=submission.session_question_id,
            selected_option_id=submission.selected_option_id or "",
        )
    if submission.is_correct is None or submission.points is None:
        return None
    return RevealedOwnSubmissionPayload(
        session_question_id=submission.session_question_id,
        selected_option_id=submission.selected_option_id or "",
        is_correct=submission.is_correct,
        points=submission.points,
    )


def leaderboard_payloads(
    entries: Iterable[LeaderboardEntry],
) -> list[LeaderboardPayload]:
    return [
        LeaderboardPayload(
            user_id=entry.user_id,
            display_name=entry.display_name_snapshot,
            total_points=entry.total_points,
            correct_answers=entry.correct_answers,
            rank=entry.rank,
        )
        for entry in entries
    ]


def state_snapshot_payload(
    snapshot: AuthoritativeSnapshot,
    *,
    online_users: Iterable[UUID],
) -> StateSnapshotPayload:
    question: OpenQuestionPayload | RevealedQuestionPayload | None
    if isinstance(snapshot.question, RevealedQuestion):
        question = revealed_question_payload(snapshot.question, server_time=snapshot.server_time)
    elif isinstance(snapshot.question, PublicQuestion):
        question = open_question_payload(snapshot.question, server_time=snapshot.server_time)
    else:
        question = None

    status_value: V1SnapshotStatus | None = None
    if snapshot.session is not None:
        status_value = v1_snapshot_status(snapshot.session.status)

    return StateSnapshotPayload(
        server_time=snapshot.server_time,
        room_state=room_state_payload(snapshot, online_users=online_users),
        session_id=None if snapshot.session is None else snapshot.session.id,
        viewer_participated=snapshot.viewer_participated,
        state_version=snapshot.state_version,
        status=status_value,
        current_question_number=snapshot.current_question_number,
        total_question_count=snapshot.total_question_count,
        question=question,
        closes_at=snapshot.closes_at,
        reveal_ends_at=snapshot.reveal_ends_at,
        viewer_submission=own_submission_payload(
            snapshot.viewer_submission,
            revealed=(
                snapshot.session is not None
                and snapshot.session.status not in (QuizSessionStatus.QUESTION_OPEN, QuizSessionStatus.QUESTION_GRADING)
            ),
        ),
        leaderboard=leaderboard_payloads(snapshot.leaderboard),
        finished_at=snapshot.finished_at,
    )


# --- V2 Payload Builders ---


def room_state_payload_v2(
    snapshot: AuthoritativeSnapshot,
    *,
    online_users: Iterable[UUID],
) -> RoomStatePayloadV2:
    online = frozenset(online_users)
    return RoomStatePayloadV2(
        room_id=snapshot.room.id,
        name=snapshot.room.name,
        join_code=snapshot.room.join_code,
        maximum_members=snapshot.room.maximum_members,
        viewer_role=snapshot.viewer_role.value,
        participants=[
            RoomStateParticipantV2(
                user_id=participant.user_id,
                display_name=participant.display_name,
                role="host" if participant.user_id == snapshot.room.owner_id else "member",
                ready=participant.ready,
                online=participant.user_id in online,
            )
            for participant in snapshot.participants
        ],
        viewer_ready=snapshot.viewer_ready,
        quiz_mode=snapshot.room.quiz_mode,
        education_level=snapshot.room.education_level,
        quiz_subject=snapshot.room.quiz_subject,
        quiz_topic=snapshot.room.quiz_topic,
        target_total_marks=snapshot.room.target_total_marks,
        active_preparation_status=snapshot.active_preparation_status,
        active_preparation_version=snapshot.active_preparation_version,
        active_preparation_error_category=snapshot.active_preparation_error_category,
    )


def open_question_payload_v2(
    question: PublicQuestion,
    *,
    server_time: datetime,
) -> OpenQuestionPayloadV2:
    return OpenQuestionPayloadV2(
        session_question_id=question.id,
        prompt=question.prompt,
        options=[
            QuestionOptionPayloadV2(id=opt.id, label=opt.label)
            for opt in question.options
        ],
        question_number=question.question_number,
        total_questions=question.total_questions,
        closes_at=question.closes_at,
        server_time=server_time,
        question_type=question.question_type,
        max_marks=question.max_marks,
        original_extract=question.original_extract,
    )


def revealed_question_payload_v2(
    question: RevealedQuestion,
    *,
    server_time: datetime,
) -> RevealedQuestionPayloadV2:
    return RevealedQuestionPayloadV2(
        session_question_id=question.id,
        prompt=question.prompt,
        options=[
            QuestionOptionPayloadV2(id=opt.id, label=opt.label)
            for opt in question.options
        ],
        question_number=question.question_number,
        total_questions=question.total_questions,
        closes_at=question.closes_at,
        server_time=server_time,
        correct_option_id=question.correct_option_id,
        question_type=question.question_type,
        max_marks=question.max_marks,
        worked_explanation=question.worked_explanation,
        original_extract=question.original_extract,
    )


def own_submission_payload_v2(
    submission: ViewerSubmission | None,
    *,
    revealed: bool,
) -> OpenOwnSubmissionPayloadV2 | RevealedOwnSubmissionPayloadV2 | None:
    if submission is None:
        return None
    if not revealed:
        return OpenOwnSubmissionPayloadV2(
            session_question_id=submission.session_question_id,
            selected_option_id=submission.selected_option_id,
            answer_text=submission.answer_text,
            grading_status=submission.grading_status,
        )
    return RevealedOwnSubmissionPayloadV2(
        session_question_id=submission.session_question_id,
        selected_option_id=submission.selected_option_id,
        answer_text=submission.answer_text,
        is_correct=submission.is_correct,
        points=submission.points,
        earned_marks=submission.earned_marks,
        max_marks=submission.max_marks or 1,
        grading_status=submission.grading_status,
        feedback=submission.feedback,
        awarded_criterion_ids=list(submission.awarded_criterion_ids),
    )


def leaderboard_payloads_v2(
    entries: Iterable[LeaderboardEntry],
) -> list[LeaderboardPayloadV2]:
    return [
        LeaderboardPayloadV2(
            user_id=entry.user_id,
            display_name=entry.display_name_snapshot,
            total_points=entry.total_points,
            correct_answers=entry.correct_answers,
            rank=entry.rank,
            earned_marks=entry.earned_marks,
            total_available_marks=entry.total_available_marks,
        )
        for entry in entries
    ]


def state_snapshot_payload_v2(
    snapshot: AuthoritativeSnapshot,
    *,
    online_users: Iterable[UUID],
) -> StateSnapshotPayloadV2:
    question: OpenQuestionPayloadV2 | RevealedQuestionPayloadV2 | None
    if isinstance(snapshot.question, RevealedQuestion):
        question = revealed_question_payload_v2(snapshot.question, server_time=snapshot.server_time)
    elif isinstance(snapshot.question, PublicQuestion):
        question = open_question_payload_v2(snapshot.question, server_time=snapshot.server_time)
    else:
        question = None

    status_v2_value: V2SnapshotStatus | None = None
    if snapshot.session is not None:
        status_v2_value = v2_snapshot_status(snapshot.session.status)

    # Lobby totals: the adaptive room target before a session starts, the
    # immutable session total once started, and 5 for legacy. Never emit a
    # contradictory base payload in an adaptive lobby.
    if snapshot.session is not None:
        lobby_total_marks = snapshot.session.total_available_marks
    elif snapshot.room.quiz_mode == "ADAPTIVE" and snapshot.room.target_total_marks:
        lobby_total_marks = snapshot.room.target_total_marks
    else:
        lobby_total_marks = 5

    return StateSnapshotPayloadV2(
        server_time=snapshot.server_time,
        room_state=room_state_payload_v2(snapshot, online_users=online_users),
        session_id=None if snapshot.session is None else snapshot.session.id,
        viewer_participated=snapshot.viewer_participated,
        state_version=snapshot.state_version,
        status=status_v2_value,
        current_question_number=snapshot.current_question_number,
        total_question_count=snapshot.total_question_count,
        question=question,
        closes_at=snapshot.closes_at,
        reveal_ends_at=snapshot.reveal_ends_at,
        viewer_submission=own_submission_payload_v2(
            snapshot.viewer_submission,
            revealed=(
                snapshot.session is not None
                and snapshot.session.status in (QuizSessionStatus.QUESTION_REVEAL, QuizSessionStatus.FINISHED)
            ),
        ),
        leaderboard=leaderboard_payloads_v2(snapshot.leaderboard),
        finished_at=snapshot.finished_at,
        quiz_mode=snapshot.room.quiz_mode,
        total_available_marks=lobby_total_marks,
        grading_retry_needed=snapshot.grading_retry_needed,
    )


class RealtimePublisher:
    """Publish current durable views to v1 and v2 clients."""

    def __init__(
        self,
        manager: ConnectionManager,
        session_service: SessionService,
    ) -> None:
        self._manager = manager
        self._session_service = session_service
        self._published_versions: dict[UUID, int] = {}
        self._publication_lock = asyncio.Lock()

    async def send_connected(self, connection_id: UUID) -> None:
        version = self._manager.get_protocol_version(connection_id)
        now = datetime.now(timezone.utc)
        if version == 2:
            event = ConnectedEventV2(
                protocol_version=2,
                type="CONNECTED",
                payload=ConnectedPayloadV2(server_time=now),
            )
            await self._manager.send_to_connection(connection_id, serialize_event_v2(event))
        else:
            event_v1 = ConnectedEvent(
                protocol_version=1,
                type="CONNECTED",
                payload=ConnectedPayload(server_time=now),
            )
            await self._manager.send_to_connection(connection_id, serialize_event(event_v1))

    async def send_snapshot(
        self,
        connection_id: UUID,
        room_id: UUID,
        user_id: UUID,
    ) -> None:
        snapshot = await self._load_snapshot(room_id, user_id)
        online_users = await self._manager.online_users(room_id)
        version = self._manager.get_protocol_version(connection_id)

        if version == 2:
            event = StateSnapshotEventV2(
                protocol_version=2,
                type="STATE_SNAPSHOT",
                payload=state_snapshot_payload_v2(snapshot, online_users=online_users),
            )
            await self._manager.send_to_connection(connection_id, serialize_event_v2(event))
        else:
            event_v1 = StateSnapshotEvent(
                protocol_version=1,
                type="STATE_SNAPSHOT",
                payload=state_snapshot_payload(snapshot, online_users=online_users),
            )
            await self._manager.send_to_connection(connection_id, serialize_event(event_v1))

    async def send_room_state_to_all(self, room_id: UUID) -> None:
        online_users = await self._manager.online_users(room_id)
        connections = self._manager.list_room_connections(room_id)
        for conn in connections:
            snapshot = await self._load_snapshot(room_id, conn.user_id)
            if conn.protocol_version == 2:
                event_v2 = RoomStateEventV2(
                    protocol_version=2,
                    type="ROOM_STATE",
                    payload=room_state_payload_v2(snapshot, online_users=online_users),
                )
                await self._manager.send_to_connection(conn.connection_id, serialize_event_v2(event_v2))
            else:
                event_v1 = RoomStateEvent(
                    protocol_version=1,
                    type="ROOM_STATE",
                    payload=room_state_payload(snapshot, online_users=online_users),
                )
                await self._manager.send_to_connection(conn.connection_id, serialize_event(event_v1))

    async def _send_versioned_final(
        self,
        room_id: UUID,
        user_id: UUID | None,
        code: str,
        message: str,
    ) -> None:
        """Deliver a version-matched final ERROR frame to affected sockets."""
        connections = self._manager.list_room_connections(room_id)
        targets = (
            [c for c in connections if user_id is None or c.user_id == user_id]
        )
        for connection in targets:
            if connection.protocol_version == 2:
                payload = error_event_v2(code, message)
            else:
                payload = error_event(code, message)
            await self._manager.send_to_connection(connection.connection_id, payload)

    async def publish_member_left(self, room_id: UUID, user_id: UUID) -> None:
        await self._send_versioned_final(
            room_id, user_id, "room_left", "You left this room."
        )
        await self._manager.close_user_in_room(
            room_id,
            user_id,
            code=FORBIDDEN,
            reason="room_left",
        )
        await self.send_room_state_to_all(room_id)

    async def publish_room_closed(self, room_id: UUID) -> None:
        await self._send_versioned_final(
            room_id, None, "room_closed", "This room is closed."
        )
        await self._manager.close_room(
            room_id,
            code=NOT_FOUND,
            reason="room_closed",
        )

    async def publish_transition(
        self,
        room_id: UUID,
        previous: QuizSession | None,
        current: QuizSession,
    ) -> bool:
        if not await self._claim_version(current):
            return False
        online_users = await self._manager.online_users(room_id)
        connections = self._manager.list_room_connections(room_id)

        for conn in connections:
            snapshot = await self._load_snapshot(room_id, conn.user_id)
            if conn.protocol_version == 2:
                events_v2 = self._transition_events_v2(previous, current, snapshot)
                for ev in events_v2:
                    await self._manager.send_to_connection(conn.connection_id, serialize_event_v2(ev))
                snap_event_v2 = StateSnapshotEventV2(
                    protocol_version=2,
                    type="STATE_SNAPSHOT",
                    payload=state_snapshot_payload_v2(snapshot, online_users=online_users),
                )
                await self._manager.send_to_connection(conn.connection_id, serialize_event_v2(snap_event_v2))
            else:
                events_v1 = self._transition_events(previous, current, snapshot)
                for ev in events_v1:
                    await self._manager.send_to_connection(conn.connection_id, serialize_event(ev))
                snap_event_v1 = StateSnapshotEvent(
                    protocol_version=1,
                    type="STATE_SNAPSHOT",
                    payload=state_snapshot_payload(snapshot, online_users=online_users),
                )
                await self._manager.send_to_connection(conn.connection_id, serialize_event(snap_event_v1))
        return True

    async def send_answer_acknowledgement(
        self,
        connection_id: UUID,
        room_id: UUID,
        user_id: UUID,
        acknowledgement: AnswerAcknowledgement,
    ) -> None:
        snapshot = await self._load_snapshot(room_id, user_id)
        version = self._manager.get_protocol_version(connection_id)
        if version == 2:
            event_v2 = AnswerAcceptedEventV2(
                protocol_version=2,
                type="ANSWER_ACCEPTED",
                payload=AnswerAcceptedPayloadV2(
                    session_id=acknowledgement.session_id,
                    state_version=snapshot.state_version,
                    session_question_id=acknowledgement.session_question_id,
                    selected_option_id=acknowledgement.selected_option_id,
                    answer_text=acknowledgement.answer_text,
                    grading_status=acknowledgement.grading_status,
                    accepted_at=acknowledgement.accepted_at,
                ),
            )
            await self._manager.send_to_connection(connection_id, serialize_event_v2(event_v2))
        else:
            event_v1 = AnswerAcceptedEvent(
                protocol_version=1,
                type="ANSWER_ACCEPTED",
                payload=AnswerAcceptedPayload(
                    session_id=acknowledgement.session_id,
                    state_version=snapshot.state_version,
                    session_question_id=acknowledgement.session_question_id,
                    selected_option_id=acknowledgement.selected_option_id or "",
                    accepted_at=acknowledgement.accepted_at,
                ),
            )
            await self._manager.send_to_connection(connection_id, serialize_event(event_v1))

    async def _load_snapshot(
        self,
        room_id: UUID,
        user_id: UUID,
    ) -> AuthoritativeSnapshot:
        return await asyncio.to_thread(
            self._session_service.load_state_snapshot,
            room_id,
            user_id,
        )

    async def _claim_version(self, session: QuizSession) -> bool:
        async with self._publication_lock:
            previous_version = self._published_versions.get(session.id, 0)
            if session.state_version <= previous_version:
                return False
            self._published_versions[session.id] = session.state_version
            return True

    @staticmethod
    def _transition_events(
        previous: QuizSession | None,
        current: QuizSession,
        snapshot: AuthoritativeSnapshot,
    ) -> list[ServerEvent]:
        events: list[ServerEvent] = []
        if previous is None or current.id != previous.id:
            events.append(
                SessionStartedEvent(
                    protocol_version=1,
                    type="SESSION_STARTED",
                    payload=SessionReferencePayload(
                        session_id=current.id,
                        state_version=current.state_version,
                    ),
                )
            )
        if current.status == QuizSessionStatus.QUESTION_OPEN and isinstance(snapshot.question, PublicQuestion):
            events.append(
                QuestionOpenedEvent(
                    protocol_version=1,
                    type="QUESTION_OPENED",
                    payload=QuestionOpenedPayload(
                        session_id=current.id,
                        state_version=current.state_version,
                        question=open_question_payload(
                            snapshot.question,
                            server_time=snapshot.server_time,
                        ),
                    ),
                )
            )
        elif current.status == QuizSessionStatus.QUESTION_REVEAL and isinstance(snapshot.question, RevealedQuestion):
            revealed_viewer = own_submission_payload(
                snapshot.viewer_submission,
                revealed=True,
            )
            events.append(
                QuestionRevealedEvent(
                    protocol_version=1,
                    type="QUESTION_REVEALED",
                    payload=QuestionRevealedPayload(
                        session_id=current.id,
                        state_version=current.state_version,
                        question=revealed_question_payload(
                            snapshot.question,
                            server_time=snapshot.server_time,
                        ),
                        viewer_submission=(
                            revealed_viewer
                            if isinstance(revealed_viewer, RevealedOwnSubmissionPayload)
                            else None
                        ),
                        leaderboard=leaderboard_payloads(snapshot.leaderboard),
                    ),
                )
            )
        elif current.status == QuizSessionStatus.FINISHED and current.finished_at is not None:
            events.append(
                SessionFinishedEvent(
                    protocol_version=1,
                    type="SESSION_FINISHED",
                    payload=SessionFinishedPayload(
                        session_id=current.id,
                        state_version=current.state_version,
                        leaderboard=leaderboard_payloads(snapshot.leaderboard),
                        finished_at=current.finished_at,
                    ),
                )
            )
        return events

    @staticmethod
    def _transition_events_v2(
        previous: QuizSession | None,
        current: QuizSession,
        snapshot: AuthoritativeSnapshot,
    ) -> list[ServerEventV2]:
        events: list[ServerEventV2] = []
        if previous is None or current.id != previous.id:
            events.append(
                SessionStartedEventV2(
                    protocol_version=2,
                    type="SESSION_STARTED",
                    payload=SessionReferencePayloadV2(
                        session_id=current.id,
                        state_version=current.state_version,
                    ),
                )
            )
        if current.status == QuizSessionStatus.QUESTION_OPEN and isinstance(snapshot.question, PublicQuestion):
            events.append(
                QuestionOpenedEventV2(
                    protocol_version=2,
                    type="QUESTION_OPENED",
                    payload=QuestionOpenedPayloadV2(
                        session_id=current.id,
                        state_version=current.state_version,
                        question=open_question_payload_v2(
                            snapshot.question,
                            server_time=snapshot.server_time,
                        ),
                    ),
                )
            )
        elif current.status == QuizSessionStatus.QUESTION_REVEAL and isinstance(snapshot.question, RevealedQuestion):
            revealed_viewer_v2 = own_submission_payload_v2(
                snapshot.viewer_submission,
                revealed=True,
            )
            events.append(
                QuestionRevealedEventV2(
                    protocol_version=2,
                    type="QUESTION_REVEALED",
                    payload=QuestionRevealedPayloadV2(
                        session_id=current.id,
                        state_version=current.state_version,
                        question=revealed_question_payload_v2(
                            snapshot.question,
                            server_time=snapshot.server_time,
                        ),
                        viewer_submission=(
                            revealed_viewer_v2
                            if isinstance(revealed_viewer_v2, RevealedOwnSubmissionPayloadV2)
                            else None
                        ),
                        leaderboard=leaderboard_payloads_v2(snapshot.leaderboard),
                    ),
                )
            )
        elif current.status == QuizSessionStatus.FINISHED and current.finished_at is not None:
            events.append(
                SessionFinishedEventV2(
                    protocol_version=2,
                    type="SESSION_FINISHED",
                    payload=SessionFinishedPayloadV2(
                        session_id=current.id,
                        state_version=current.state_version,
                        leaderboard=leaderboard_payloads_v2(snapshot.leaderboard),
                        finished_at=current.finished_at,
                    ),
                )
            )
        return events
