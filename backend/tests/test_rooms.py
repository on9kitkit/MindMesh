import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import FakeAuthVerifier
from app.domain.errors import RoomFullError, RoomOwnerRequiredError
from app.main import create_app
from app.repositories.members import InMemoryMembershipRepository
from app.repositories.rooms import InMemoryRoomRepository
from app.repositories.users import InMemoryUserRepository
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


def create_room(
    client: TestClient,
    *,
    token: str = OWNER_TOKEN,
    **overrides: object,
):
    payload: dict[str, object] = {
        "name": "Physics Sprint",
        "maximum_members": 8,
    }
    payload.update(overrides)
    return client.post("/rooms", json=payload, headers=auth_headers(token))


def join_room(
    client: TestClient,
    path_room_id: str,
    *,
    token: str = OWNER_TOKEN,
    body: object | None = None,
):
    request = {"headers": auth_headers(token)}
    if body is not None:
        request["json"] = body
    return client.post(f"/rooms/{path_room_id}/members", **request)


def register_user(
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
    *,
    token: str,
    user_id: UUID,
    display_name: str,
) -> None:
    auth_verifier.register(token, user_id)
    user_repository.upsert_profile(user_id, display_name)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_expo_web_origin_is_allowed_by_development_cors(client: TestClient) -> None:
    response = client.options(
        "/rooms",
        headers={
            "Origin": "http://localhost:8082",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8082"


def test_unlisted_origin_is_not_allowed_by_development_cors(
    client: TestClient,
) -> None:
    response = client.options(
        "/rooms",
        headers={
            "Origin": "http://example.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_protected_room_creation_without_authorization_returns_401(
    client: TestClient,
) -> None:
    response = client.post(
        "/rooms",
        json={"name": "Physics Sprint", "maximum_members": 8},
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "authentication_required",
            "message": "Authentication is required.",
        }
    }


def test_malformed_bearer_header_returns_401(client: TestClient) -> None:
    response = create_room(client, token="malformed")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_auth_token"


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/rooms",
        json={"name": "Physics Sprint", "maximum_members": 8},
        headers={"Authorization": "Bearer unknown-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_auth_token"


def test_create_room_generates_server_values(client: TestClient) -> None:
    response = create_room(client)

    assert response.status_code == 201
    body = response.json()
    room_id = UUID(body["id"])

    assert room_id.version == 4
    assert re.fullmatch(r"[A-Z2-9]{6}", body["join_code"])
    assert body["member_count"] == 1
    assert body["name"] == "Physics Sprint"
    assert body["maximum_members"] == 8


def test_room_creation_atomically_creates_owner_membership(
    client: TestClient,
) -> None:
    room = create_room(client).json()

    members = client.get(
        f"/rooms/{room['id']}/members",
        headers=auth_headers(),
    )

    assert members.status_code == 200
    assert members.json()["members"] == [
        {"user_id": str(OWNER_ID), "display_name": "Room Owner"}
    ]
    assert members.json()["member_count"] == 1


def test_get_room_requires_authentication(client: TestClient) -> None:
    room = create_room(client).json()

    response = client.get(f"/rooms/{room['id']}")

    assert response.status_code == 401


def test_get_room_returns_created_room(client: TestClient) -> None:
    created = create_room(client).json()

    response = client.get(
        f"/rooms/{created['id']}",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == created


def test_join_room_derives_identity_and_profile_from_auth(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    user_id = UUID("22222222-2222-4222-8222-222222222222")
    register_user(
        auth_verifier,
        user_repository,
        token="student-two-token",
        user_id=user_id,
        display_name="Student Two",
    )
    room = create_room(client).json()

    response = join_room(client, room["id"], token="student-two-token")

    assert response.status_code == 201
    assert response.json() == {
        "user_id": str(user_id),
        "display_name": "Student Two",
        "room_id": room["id"],
    }


def test_membership_body_cannot_override_identity(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    register_user(
        auth_verifier,
        user_repository,
        token="student-two-token",
        user_id=UUID("22222222-2222-4222-8222-222222222222"),
        display_name="Student Two",
    )
    room = create_room(client).json()

    response = join_room(
        client,
        room["id"],
        token="student-two-token",
        body={"user_id": str(OWNER_ID), "display_name": "Imposter"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_join_body_can_be_empty_but_cannot_contain_display_name(
    client: TestClient,
) -> None:
    room = create_room(client).json()

    response = join_room(
        client,
        room["id"],
        body={"display_name": "Imposter"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_profile_creation_uses_token_derived_uuid(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    user_id = UUID("33333333-3333-4333-8333-333333333333")
    register_user(
        auth_verifier,
        user_repository,
        token="profile-token",
        user_id=user_id,
        display_name="Old Name",
    )

    response = client.put(
        "/me/profile",
        json={"display_name": "Updated Name"},
        headers=auth_headers("profile-token"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "display_name": "Updated Name",
    }
    assert user_repository.get_by_id(user_id).display_name == "Updated Name"


def test_profile_can_be_provisioned_for_a_new_authenticated_identity(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    user_id = UUID("44444444-4444-4444-8444-444444444444")
    auth_verifier.register("new-profile-token", user_id)

    response = client.put(
        "/me/profile",
        json={"display_name": "New Student"},
        headers=auth_headers("new-profile-token"),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user_id)
    assert user_repository.get_by_id(user_id) is not None


def test_get_me_returns_safe_application_profile(client: TestClient) -> None:
    response = client.get("/me", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {
        "id": str(OWNER_ID),
        "display_name": "Room Owner",
    }


def test_duplicate_membership_returns_conflict_without_incrementing_count(
    client: TestClient,
) -> None:
    room = create_room(client).json()

    duplicate = join_room(client, room["id"])

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error": {
            "code": "already_room_member",
            "message": "User is already a member of this room.",
        }
    }
    assert client.get(
        f"/rooms/{room['id']}", headers=auth_headers()
    ).json()["member_count"] == 1


def test_room_capacity_is_enforced_without_partial_membership(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    first_id = UUID("55555555-5555-4555-8555-555555555555")
    second_id = UUID("66666666-6666-4666-8666-666666666666")
    register_user(
        auth_verifier,
        user_repository,
        token="first-capacity-token",
        user_id=first_id,
        display_name="First Student",
    )
    register_user(
        auth_verifier,
        user_repository,
        token="second-capacity-token",
        user_id=second_id,
        display_name="Second Student",
    )
    room = create_room(client, maximum_members=2).json()

    first = join_room(client, room["id"], token="first-capacity-token")
    second = join_room(client, room["id"], token="second-capacity-token")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "room_full"
    assert client.get(
        f"/rooms/{room['id']}/members", headers=auth_headers()
    ).json()["member_count"] == 2


def test_user_cannot_join_another_room(
    client: TestClient,
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    student_id = UUID("77777777-7777-4777-8777-777777777777")
    register_user(
        auth_verifier,
        user_repository,
        token="cross-room-token",
        user_id=student_id,
        display_name="Cross Room Student",
    )
    second_owner_id = UUID("99999999-9999-4999-8999-999999999999")
    register_user(
        auth_verifier,
        user_repository,
        token="second-owner-token",
        user_id=second_owner_id,
        display_name="Second Owner",
    )
    first_room = create_room(client, name="First Room").json()
    second_room = create_room(
        client,
        name="Second Room",
        token="second-owner-token",
    ).json()

    first = join_room(client, first_room["id"], token="cross-room-token")
    second = join_room(client, second_room["id"], token="cross-room-token")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "user_already_in_another_room"


def test_missing_room_returns_stable_404(client: TestClient) -> None:
    response = client.get(f"/rooms/{uuid4()}", headers=auth_headers())

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "room_not_found",
            "message": "Room was not found.",
        }
    }


def test_missing_room_membership_returns_stable_404(client: TestClient) -> None:
    response = join_room(client, str(uuid4()))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "room_not_found"


def test_malformed_room_id_returns_validation_error(client: TestClient) -> None:
    response = client.get("/rooms/not-a-uuid", headers=auth_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("name", ["   ", "ab", "a" * 61])
def test_invalid_room_name_returns_422(client: TestClient, name: str) -> None:
    response = create_room(client, name=name)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("maximum_members", [1, 51, True, False])
def test_invalid_maximum_members_returns_422(
    client: TestClient,
    maximum_members: object,
) -> None:
    response = create_room(client, maximum_members=maximum_members)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_client_cannot_provide_owner_id(client: TestClient) -> None:
    response = create_room(client, owner_id=str(OWNER_ID))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_authentication_failure_does_not_create_room(client: TestClient) -> None:
    response = client.post(
        "/rooms",
        json={"name": "Unauthenticated Room", "maximum_members": 8},
        headers={"Authorization": "Bearer unknown-token"},
    )

    assert response.status_code == 401
    assert client.get(
        "/rooms/not-created", headers=auth_headers()
    ).status_code == 422


def test_valid_name_is_trimmed(client: TestClient) -> None:
    response = create_room(client, name="  Physics Sprint  ")

    assert response.status_code == 201
    assert response.json()["name"] == "Physics Sprint"


def test_application_instances_do_not_share_repository_state(
    auth_verifier: FakeAuthVerifier,
    user_repository: InMemoryUserRepository,
) -> None:
    first_app = create_app(
        repository=InMemoryRoomRepository(),
        membership_repository=InMemoryMembershipRepository(),
        user_repository=user_repository,
        auth_verifier=auth_verifier,
    )
    second_app = create_app(
        repository=InMemoryRoomRepository(),
        membership_repository=InMemoryMembershipRepository(),
        user_repository=user_repository,
        auth_verifier=auth_verifier,
    )

    with TestClient(first_app) as first_client:
        created = create_room(first_client).json()

    with TestClient(second_app) as second_client:
        response = second_client.get(
            f"/rooms/{created['id']}", headers=auth_headers()
        )

    assert response.status_code == 404


def test_owner_authorization_passes_for_owner() -> None:
    room_repository = InMemoryRoomRepository()
    membership_repository = InMemoryMembershipRepository()
    service = RoomService(
        room_repository,
        membership_repository=membership_repository,
    )
    room = service.create_room(
        name="Owner Room",
        maximum_members=2,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )

    assert service.require_room_owner(room_id=room.id, user_id=OWNER_ID) == room


def test_owner_authorization_rejects_non_owner() -> None:
    room_repository = InMemoryRoomRepository()
    membership_repository = InMemoryMembershipRepository()
    service = RoomService(
        room_repository,
        membership_repository=membership_repository,
    )
    room = service.create_room(
        name="Owner Room",
        maximum_members=2,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )

    with pytest.raises(RoomOwnerRequiredError):
        service.require_room_owner(
            room_id=room.id,
            user_id=UUID("88888888-8888-4888-8888-888888888888"),
        )


def test_in_memory_atomic_creation_rolls_back_room_on_membership_failure() -> None:
    class FailingMembershipRepository(InMemoryMembershipRepository):
        def join(self, member, maximum_members: int) -> None:
            raise RoomFullError

    room_repository = InMemoryRoomRepository()
    membership_repository = FailingMembershipRepository()
    service = RoomService(
        room_repository,
        membership_repository=membership_repository,
    )

    with pytest.raises(RoomFullError):
        service.create_room(
            name="Rollback Room",
            maximum_members=2,
            owner_id=OWNER_ID,
            owner_display_name="Room Owner",
        )

    assert room_repository.get_by_join_code("AAAAAA") is None
    assert room_repository.get_by_id(next(iter(room_repository._rooms_by_id), uuid4())) is None
