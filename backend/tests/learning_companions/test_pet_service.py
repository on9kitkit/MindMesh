"""Offline pet transaction decisions; the PostgreSQL race gate is separate."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.learning_companions.contracts import PET_CATALOG
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    PetEquipmentModel,
    PetOwnershipModel,
    PetPurchaseModel,
)
from app.learning_companions.pet_service import (
    EquipmentNotOwned,
    InsufficientCoins,
    PetService,
    PurchaseRequestConflict,
    StarterAlreadyChosen,
    UnknownCatalogItem,
)


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
USER_ID = uuid4()
USER = SimpleNamespace(id=USER_ID, deleted_at=None, suspended_at=None)


class FakePetSession:
    def __init__(
        self,
        *,
        scalars: tuple[object, ...] = (),
        gets: tuple[object, ...] = (),
        rows: tuple[object, ...] = (),
    ):
        self.scalar_results = list(scalars)
        self.get_results = list(gets)
        self.rows = rows
        self.added: list[object] = []
        self.flush_snapshots: list[tuple[object, ...]] = []

    def scalar(self, _statement):
        return self.scalar_results.pop(0)

    def get(self, _model, _key):
        return self.get_results.pop(0)

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: list(self.rows))

    def add(self, row):
        self.added.append(row)

    def flush(self):
        self.flush_snapshots.append(tuple(self.added))


class FakePetFactory:
    def __init__(self, *sessions: FakePetSession):
        self.sessions = list(sessions)

    @contextmanager
    def begin(self):
        yield self.sessions.pop(0)


@pytest.fixture(autouse=True)
def fixed_db_clock(monkeypatch):
    monkeypatch.setattr(
        "app.learning_companions.pet_service._database_now", lambda _session: NOW
    )


def test_free_starter_is_permanent_and_replay_is_free() -> None:
    create = FakePetSession(scalars=(USER, None), gets=(None, None))
    chosen = PetService(FakePetFactory(create)).choose_starter(USER_ID, "pet.fox")
    assert chosen.created and chosen.item_id == "pet.fox"
    ownership = next(row for row in create.added if isinstance(row, PetOwnershipModel))
    equipment = next(row for row in create.added if isinstance(row, PetEquipmentModel))
    assert ownership.acquisition_kind == "starter" and ownership.purchase_id is None
    assert equipment.equipped_pet_id == "pet.fox"
    assert not any(isinstance(row, (CoinWalletModel, CoinLedgerModel)) for row in create.added)

    replay = FakePetSession(scalars=(USER, ownership))
    assert not PetService(FakePetFactory(replay)).choose_starter(USER_ID, "pet.fox").created
    assert replay.added == []
    conflict = FakePetSession(scalars=(USER, ownership))
    with pytest.raises(StarterAlreadyChosen):
        PetService(FakePetFactory(conflict)).choose_starter(USER_ID, "pet.owl")


def test_purchase_debits_once_and_retry_returns_original_balance() -> None:
    request_id = uuid4()
    wallet = CoinWalletModel(user_id=USER_ID, balance=150, state_version=1, updated_at=NOW)
    create = FakePetSession(scalars=(USER, None, wallet), gets=(None,))
    result = PetService(FakePetFactory(create)).purchase(
        USER_ID, request_id, "pet.tortoise"
    )
    assert not result.replayed
    assert result.price_charged == PET_CATALOG["pet.tortoise"].coin_price == 120
    assert result.balance_after == wallet.balance == 30
    purchase = next(row for row in create.added if isinstance(row, PetPurchaseModel))
    ledger = next(row for row in create.added if isinstance(row, CoinLedgerModel))
    ownership = next(row for row in create.added if isinstance(row, PetOwnershipModel))
    assert ledger.amount == -120 and ledger.balance_after == 30
    assert ledger.source_id == purchase.id == ownership.purchase_id
    assert create.flush_snapshots == [(purchase,)]

    replay = FakePetSession(scalars=(USER, purchase, ledger))
    again = PetService(FakePetFactory(replay)).purchase(
        USER_ID, request_id, "pet.tortoise"
    )
    assert again.replayed and again.balance_after == 30
    assert replay.added == []
    assert replay.flush_snapshots == []
    changed = FakePetSession(scalars=(USER, purchase))
    with pytest.raises(PurchaseRequestConflict):
        PetService(FakePetFactory(changed)).purchase(USER_ID, request_id, "pet.owl")


def test_insufficient_balance_and_pro_variant_do_not_create_ownership() -> None:
    wallet = CoinWalletModel(user_id=USER_ID, balance=39, state_version=1, updated_at=NOW)
    session = FakePetSession(scalars=(USER, None, wallet), gets=(None,))
    with pytest.raises(InsufficientCoins):
        PetService(FakePetFactory(session)).purchase(
            USER_ID, uuid4(), "cosmetic.study_scarf"
        )
    assert session.added == []
    assert wallet.balance == 39
    with pytest.raises(UnknownCatalogItem):
        PetService(FakePetFactory()).equip(
            USER_ID,
            pet_id="pet.owl",
            cosmetic_id=None,
            animation_id="animation.pro_flourish",
        )
    assert "animation.pro_flourish" not in PET_CATALOG


def test_equipping_requires_owned_catalog_items() -> None:
    session = FakePetSession(scalars=(USER,), rows=("pet.owl",))
    with pytest.raises(EquipmentNotOwned, match="owned"):
        PetService(FakePetFactory(session)).equip(
            USER_ID,
            pet_id="pet.owl",
            cosmetic_id="cosmetic.study_scarf",
            animation_id=None,
        )
    assert session.added == []
