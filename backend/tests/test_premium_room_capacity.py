from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.auth import FakeAuthVerifier
from app.db.models.membership import RoomMembershipModel
from app.db.models.room import RoomModel
from app.db.session import Database
from app.domain.errors import (
    InvalidRoomDataError,
    PremiumVerificationUnavailableError,
    ProRequiredError,
)
from app.main import create_app
from app.repositories.members import InMemoryMembershipRepository
from app.repositories.postgres_members import PostgresMembershipRepository
from app.repositories.postgres_rooms import PostgresRoomRepository
from app.repositories.postgres_users import PostgresUserRepository
from app.repositories.rooms import InMemoryRoomRepository
from app.repositories.users import InMemoryUserRepository
from app.services.rooms import RoomService
from tests.conftest import OWNER_ID, OWNER_TOKEN, auth_headers


FIXED_ROOM_ID = UUID("99999999-9999-4999-8999-999999999999")


class FakeEntitlementVerifier:
    def __init__(self, *, active: bool = False, unavailable: bool = False) -> None:
        self.active = active
        self.unavailable = unavailable
        self.calls: list[tuple[UUID, str]] = []

    def has_entitlement(
        self,
        customer_id: UUID,
        entitlement_lookup_key: str,
    ) -> bool:
        self.calls.append((customer_id, entitlement_lookup_key))
        if self.unavailable:
            raise PremiumVerificationUnavailableError
        return self.active


@contextmanager
def capacity_client(
    verifier: FakeEntitlementVerifier | None,
) -> Iterator[tuple[TestClient, InMemoryRoomRepository, InMemoryMembershipRepository]]:
    room_repository = InMemoryRoomRepository()
    membership_repository = InMemoryMembershipRepository()
    service = RoomService(
        room_repository,
        membership_repository=membership_repository,
        room_id_factory=lambda: FIXED_ROOM_ID,
        join_code_factory=lambda: "PHYS42",
        premium_entitlement_verifier=verifier,
        premium_entitlement_lookup_key="pro" if verifier is not None else None,
    )
    user_repository = InMemoryUserRepository()
    user_repository.upsert_profile(OWNER_ID, "Room Owner")
    app = create_app(
        service=service,
        user_repository=user_repository,
        auth_verifier=FakeAuthVerifier({OWNER_TOKEN: OWNER_ID}),
    )
    with TestClient(app) as client:
        yield client, room_repository, membership_repository


def create_room(client: TestClient, maximum_members: int, **extra: object):
    return client.post(
        "/rooms",
        json={
            "name": "Physics Sprint",
            "maximum_members": maximum_members,
            **extra,
        },
        headers=auth_headers(),
    )


@pytest.mark.parametrize("maximum_members", [2, 8])
def test_free_room_capacity_never_calls_revenuecat(maximum_members: int) -> None:
    verifier = FakeEntitlementVerifier(unavailable=True)
    with capacity_client(verifier) as (client, _, _):
        response = create_room(client, maximum_members)
    assert response.status_code == 201
    assert response.json()["maximum_members"] == maximum_members
    assert verifier.calls == []


@pytest.mark.parametrize("maximum_members", [9, 20])
def test_free_user_cannot_create_large_room(maximum_members: int) -> None:
    verifier = FakeEntitlementVerifier(active=False)
    with capacity_client(verifier) as (client, room_repository, memberships):
        response = create_room(client, maximum_members)
        active_room = client.get("/me/active-room", headers=auth_headers())
        assert room_repository.get_by_id(FIXED_ROOM_ID) is None
        assert memberships.get_active_room_for_user(OWNER_ID) is None
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "pro_required"
    assert active_room.status_code == 200
    assert active_room.json() is None
    assert verifier.calls == [(OWNER_ID, "pro")]


@pytest.mark.parametrize("maximum_members", [9, 20])
def test_pro_user_can_create_large_room(maximum_members: int) -> None:
    verifier = FakeEntitlementVerifier(active=True)
    with capacity_client(verifier) as (client, _, _):
        response = create_room(client, maximum_members)
    assert response.status_code == 201
    assert response.json()["maximum_members"] == maximum_members
    assert verifier.calls == [(OWNER_ID, "pro")]


def test_capacity_above_twenty_is_validation_error_for_pro() -> None:
    verifier = FakeEntitlementVerifier(active=True)
    with capacity_client(verifier) as (client, _, _):
        response = create_room(client, 21)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert verifier.calls == []


def test_unavailable_verification_fails_closed_only_for_large_room() -> None:
    verifier = FakeEntitlementVerifier(unavailable=True)
    with capacity_client(verifier) as (client, _, _):
        response = create_room(client, 20)
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "premium_verification_unavailable",
            "message": "We couldn't verify MindMesh Pro right now. Try again shortly.",
        }
    }


def test_missing_server_configuration_keeps_free_rooms_available() -> None:
    with capacity_client(None) as (client, _, _):
        free = create_room(client, 8)
    assert free.status_code == 201

    with capacity_client(None) as (client, _, _):
        premium = create_room(client, 20)
    assert premium.status_code == 503
    assert premium.json()["error"]["code"] == "premium_verification_unavailable"


@pytest.mark.parametrize(
    "field",
    [
        "is_pro",
        "isPro",
        "hasPremium",
        "entitlementActive",
        "entitlement",
        "entitlement_id",
        "product_id",
        "subscription_status",
        "subscriptionStatus",
        "revenuecat_customer_id",
        "customer_id",
    ],
)
def test_client_premium_authority_fields_are_rejected(field: str) -> None:
    verifier = FakeEntitlementVerifier(active=True)
    with capacity_client(verifier) as (client, _, _):
        response = create_room(client, 20, **{field: True})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert verifier.calls == []


def test_existing_large_room_keeps_capacity_after_entitlement_disappears() -> None:
    verifier = FakeEntitlementVerifier(active=True)
    room_repository = InMemoryRoomRepository()
    service = RoomService(
        room_repository,
        membership_repository=InMemoryMembershipRepository(),
        premium_entitlement_verifier=verifier,
        premium_entitlement_lookup_key="pro",
    )
    room = service.create_room(
        name="Large Room",
        maximum_members=20,
        owner_id=OWNER_ID,
        owner_display_name="Room Owner",
    )

    verifier.active = False

    assert service.get_room(room.id).maximum_members == 20
    assert verifier.calls == [(OWNER_ID, "pro")]


def test_service_rejects_capacity_above_absolute_maximum_before_verification() -> None:
    verifier = FakeEntitlementVerifier(active=True)
    service = RoomService(
        InMemoryRoomRepository(),
        membership_repository=InMemoryMembershipRepository(),
        premium_entitlement_verifier=verifier,
        premium_entitlement_lookup_key="pro",
    )
    with pytest.raises(InvalidRoomDataError):
        service.create_room(
            name="Invalid Room",
            maximum_members=21,
            owner_id=OWNER_ID,
            owner_display_name="Room Owner",
        )
    assert verifier.calls == []


def test_failed_postgres_entitlement_check_creates_no_rows(
    postgres_database: Database,
    postgres_user_repository: PostgresUserRepository,
) -> None:
    verifier = FakeEntitlementVerifier(active=False)
    service = RoomService(
        PostgresRoomRepository(postgres_database.session_factory),
        membership_repository=PostgresMembershipRepository(
            postgres_database.session_factory
        ),
        premium_entitlement_verifier=verifier,
        premium_entitlement_lookup_key="pro",
    )

    with pytest.raises(ProRequiredError):
        service.create_room(
            name="Rejected Large Room",
            maximum_members=20,
            owner_id=OWNER_ID,
            owner_display_name="Room Owner",
        )

    with postgres_database.session_factory() as session:
        room_count = session.scalar(select(func.count()).select_from(RoomModel))
        membership_count = session.scalar(
            select(func.count()).select_from(RoomMembershipModel)
        )
    assert room_count == 0
    assert membership_count == 0
