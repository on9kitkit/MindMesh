"""Inert solo-route checks for authentication, owner scope and answer-key projection."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from app.api.solo import get_solo_service, router
from app.auth import FakeAuthVerifier
from app.domain.errors import AuthenticationRequiredError
from app.learning_companions.contracts import (
    LockedSelfCheck, MarkProvenance, SelfCheckCriterion, SoloAttemptStatus,
)
from app.learning_companions.solo_domain import (
    NOT_FOUND, PublicSoloQuestion, SoloAnswerState, SoloAttemptState, SoloOption,
)
from app.repositories.users import InMemoryUserRepository


OWNER = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")


class _InertSoloService:
    def __init__(self) -> None:
        self.attempt_id = uuid4()
        self.question_id = uuid4()
        self.answer: SoloAnswerState | None = None
        self.calls: list[UUID] = []

    def get_state(self, owner_id: UUID, attempt_id: UUID) -> SoloAttemptState:
        self.calls.append(owner_id)
        if owner_id != OWNER or attempt_id != self.attempt_id:
            raise NOT_FOUND
        question = PublicSoloQuestion(
            id=self.question_id, position=0, question_type="WRITTEN", max_marks=3,
            prompt="Explain the change.", options=(), original_extract=None,
        )
        return SoloAttemptState(
            id=self.attempt_id, request_id=uuid4(),
            status=SoloAttemptStatus.IN_PROGRESS, state_version=2,
            subject="physics", topic="forces", total_marks=5,
            current_question_position=0,
            created_at=datetime.now(timezone.utc), started_at=datetime.now(timezone.utc),
            terminal_at=None, questions=(question,),
            answers=(self.answer,) if self.answer is not None else (),
        )

    def get_self_check(self, owner_id: UUID, attempt_id: UUID, question_id: UUID) -> LockedSelfCheck:
        self.get_state(owner_id, attempt_id)
        if self.answer is None or question_id != self.question_id:
            raise NOT_FOUND
        return LockedSelfCheck(
            question_id=question_id, locked_answer=self.answer.answer_text or "",
            intended_answer="Reference answer after lock.", max_marks=3,
            criteria=(SelfCheckCriterion("c1", 3, "Marking point", "Explanation"),),
        )

    def submit_answer(self, owner_id, attempt_id, question_id, selected_option_id, answer_text):
        self.get_state(owner_id, attempt_id)
        if question_id != self.question_id or selected_option_id is not None:
            raise NOT_FOUND
        if self.answer is None:
            self.answer = SoloAnswerState(
                question_id=question_id, selected_option_id=None,
                answer_text=answer_text, accepted_at=datetime.now(timezone.utc),
                grading_status="SELF_CHECK_PENDING",
                mark_provenance=MarkProvenance.SELF_ASSESSED,
                earned_marks=None,
            )
        return self.answer


def _client(service: _InertSoloService) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(
        AuthenticationRequiredError,
        lambda _request, _error: JSONResponse(status_code=401, content={"error": {"code": "authentication_required"}}),
    )
    app.state.auth_verifier = FakeAuthVerifier({"owner": OWNER, "other": OTHER})
    users = InMemoryUserRepository()
    users.upsert_profile(OWNER, "Owner")
    users.upsert_profile(OTHER, "Other")
    app.state.user_repository = users
    app.dependency_overrides[get_solo_service] = lambda: service
    app.include_router(router)
    return TestClient(app)


def test_progress_never_exposes_keys_and_self_check_requires_locked_answer() -> None:
    service = _InertSoloService()
    with _client(service) as client:
        path = f"/me/solo-attempts/{service.attempt_id}"
        headers = {"Authorization": "Bearer owner"}
        snapshot = client.get(path, headers=headers)
        assert snapshot.status_code == 200
        assert snapshot.headers["cache-control"] == "no-store"
        body = snapshot.json()
        assert len(body["questions"]) == 1
        assert "correct_option_id" not in str(body)
        assert "grading_rubric" not in str(body)
        assert "Reference answer" not in str(body)
        check_path = f"{path}/questions/{service.question_id}/self-check"
        early = client.get(check_path, headers=headers)
        assert early.status_code == 404
        assert "Reference answer" not in early.text
        accepted = client.post(f"{path}/answers", headers=headers, json={
            "question_id": str(service.question_id), "text": "My locked answer",
        })
        assert accepted.status_code == 201
        assert accepted.json()["grading_status"] == "SELF_CHECK_PENDING"
        unlocked = client.get(check_path, headers=headers)
        assert unlocked.status_code == 200
        assert unlocked.json()["intended_answer"] == "Reference answer after lock."


def test_every_attempt_lookup_uses_authenticated_owner() -> None:
    service = _InertSoloService()
    with _client(service) as client:
        path = f"/me/solo-attempts/{service.attempt_id}"
        assert client.get(path).status_code == 401
        denied = client.get(path, headers={"Authorization": "Bearer other"})
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "solo_not_found"
        assert service.calls == [OTHER]
