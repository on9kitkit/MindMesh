from uuid import UUID

import pytest

from app.domain.display_name import normalize_display_name
from app.domain.errors import AccountSuspendedError, InvalidDisplayNameError
from app.main import create_app
from app.repositories.users import InMemoryUserRepository
from app.services.join_throttle import JoinFailureThrottle
from tests.conftest import OWNER_TOKEN, auth_headers


JOINER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
JOINER_TOKEN = "identity-hardening-joiner-token"
OTHER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OTHER_TOKEN = "identity-hardening-other-token"


def test_display_name_policy_normalizes_unicode_and_whitespace() -> None:
    assert normalize_display_name("  Ｓtudent\u00a0  ") == "Student"
    assert normalize_display_name("Ångström 学生") == "Ångström 学生"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "a" * 41,
        "StudyRoom",
        "studyroom support",
        "Official Tutor",
        "official_staff",
        "Student\u200bName",
        "Student\u202eName",
        "Student\nName",
    ],
)
def test_display_name_policy_rejects_unsafe_or_service_names(value: str) -> None:
    with pytest.raises(InvalidDisplayNameError):
        normalize_display_name(value)


def test_display_name_policy_uses_word_aware_prohibited_terms() -> None:
    assert normalize_display_name("Officially Curious") == "Officially Curious"
    assert normalize_display_name("Stafford Student") == "Stafford Student"


def test_profile_validation_does_not_echo_submitted_name(client) -> None:
    response = client.put(
        "/me/profile",
        headers=auth_headers(),
        json={"display_name": "unsafe\u200bname"},
    )

    assert response.status_code == 422
    assert "unsafe" not in response.text
    assert "input" not in response.text


def test_suspended_identity_is_denied_before_normal_product_actions(
    client,
    auth_verifier,
    user_repository: InMemoryUserRepository,
) -> None:
    auth_verifier.register(JOINER_TOKEN, JOINER_ID)
    user_repository.upsert_profile(JOINER_ID, "Suspended Student")
    user_repository.suspend(JOINER_ID, "safety_review")

    for response in (
        client.post(
            "/rooms",
            headers=auth_headers(JOINER_TOKEN),
            json={"name": "Blocked Room", "maximum_members": 8},
        ),
        client.put(
            "/me/profile",
            headers=auth_headers(JOINER_TOKEN),
            json={"display_name": "New Student"},
        ),
        client.post(
            "/rooms/join",
            headers=auth_headers(JOINER_TOKEN),
            json={"join_code": "AAAAA2"},
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "account_suspended"

    deletion_response = client.request(
        "DELETE",
        "/me",
        headers=auth_headers(JOINER_TOKEN),
        json={"confirmation": "DELETE"},
    )
    assert deletion_response.status_code == 503
    assert deletion_response.json()["error"]["code"] == "account_deletion_unavailable"

    user_repository.unsuspend(JOINER_ID)
    restored = client.post(
        "/rooms",
        headers=auth_headers(JOINER_TOKEN),
        json={"name": "Restored Room", "maximum_members": 8},
    )
    assert restored.status_code == 201


def test_join_code_failures_are_non_enumerating_and_throttled(
    client,
    auth_verifier,
    user_repository: InMemoryUserRepository,
) -> None:
    auth_verifier.register(JOINER_TOKEN, JOINER_ID)
    user_repository.upsert_profile(JOINER_ID, "Joiner Student")
    closed = client.post(
        "/rooms",
        headers=auth_headers(),
        json={"name": "Closed Room", "maximum_members": 8},
    ).json()
    assert client.post(
        f"/rooms/{closed['id']}/close",
        headers=auth_headers(),
    ).status_code == 204

    headers = auth_headers(JOINER_TOKEN)
    closed_failure = client.post(
        "/rooms/join",
        headers=headers,
        json={"join_code": closed["join_code"]},
    )
    unknown_failure = client.post(
        "/rooms/join",
        headers=headers,
        json={"join_code": "AAAAA2"},
    )
    assert closed_failure.status_code == 404
    assert unknown_failure.status_code == 404
    assert closed_failure.json() == unknown_failure.json()
    assert closed_failure.json()["error"]["code"] == "room_join_unavailable"

    for _ in range(6):
        response = client.post(
            "/rooms/join",
            headers=headers,
            json={"join_code": closed["join_code"]},
        )
        assert response.status_code == 404
    limited = client.post(
        "/rooms/join",
        headers=headers,
        json={"join_code": closed["join_code"]},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "room_join_rate_limited"
    assert limited.headers["retry-after"].isdigit()


def test_join_throttle_recovers_and_success_resets_state() -> None:
    now = [0.0]
    throttle = JoinFailureThrottle(
        limit=2,
        window_seconds=10.0,
        cooldown_seconds=1.0,
        clock=lambda: now[0],
    )

    assert throttle.allow(JOINER_ID) == (True, None)
    throttle.record_failure(JOINER_ID)
    throttle.record_failure(JOINER_ID)
    allowed, retry_after = throttle.allow(JOINER_ID)
    assert allowed is False
    assert retry_after is not None
    throttle.record_success(JOINER_ID)
    assert throttle.allow(JOINER_ID) == (True, None)

    throttle.record_failure(JOINER_ID)
    throttle.record_failure(JOINER_ID)
    now[0] = 10.1
    assert throttle.allow(JOINER_ID) == (True, None)
