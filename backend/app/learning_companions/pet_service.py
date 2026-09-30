"""Server-authoritative earned pet catalog, ownership, spend and equipment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.learning_companions.contracts import (
    CoinLedgerKind,
    CatalogItem,
    CatalogKind,
    PET_CATALOG,
    STARTER_PET_IDS,
)
from app.learning_companions.models import (
    CoinLedgerModel,
    CoinWalletModel,
    PetEquipmentModel,
    PetOwnershipModel,
    PetPurchaseModel,
)
from app.learning_companions.reward_repository import _database_now
from app.learning_companions.reward_service import _lock_active_user


class UnknownCatalogItem(ValueError):
    pass


class StarterAlreadyChosen(ValueError):
    pass


class ItemAlreadyOwned(ValueError):
    pass


class InsufficientCoins(ValueError):
    pass


class PurchaseRequestConflict(ValueError):
    pass


class EquipmentNotOwned(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StarterChoice:
    item_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class PurchaseResult:
    purchase_id: UUID
    request_id: UUID
    item_id: str
    price_charged: int
    balance_after: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class EquipmentSelection:
    pet_id: str
    cosmetic_id: str | None
    animation_id: str | None


@dataclass(frozen=True, slots=True)
class PetState:
    catalog: tuple[CatalogItem, ...]
    owned_item_ids: tuple[str, ...]
    starter_pet_id: str | None
    equipment: EquipmentSelection | None
    balance: int


def _item(item_id: str, *, kind: CatalogKind | None = None) -> CatalogItem:
    item = PET_CATALOG.get(item_id)
    if item is None or (kind is not None and item.kind != kind):
        raise UnknownCatalogItem("Choose an available earned catalog item.")
    return item


def _locked_wallet(session: Session, user_id: UUID, now: datetime) -> CoinWalletModel:
    wallet = session.scalar(
        select(CoinWalletModel)
        .where(CoinWalletModel.user_id == user_id)
        .with_for_update()
    )
    if wallet is None:
        wallet = CoinWalletModel(user_id=user_id, balance=0, state_version=1, updated_at=now)
        session.add(wallet)
    return wallet


class PetService:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def choose_starter(self, user_id: UUID, item_id: str) -> StarterChoice:
        _item(item_id, kind=CatalogKind.PET)
        if item_id not in STARTER_PET_IDS:
            raise UnknownCatalogItem("Choose an available starter pet.")
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            starter = session.scalar(
                select(PetOwnershipModel)
                .where(
                    PetOwnershipModel.user_id == user_id,
                    PetOwnershipModel.acquisition_kind == "starter",
                )
                .with_for_update()
            )
            if starter is not None:
                if starter.item_id != item_id:
                    raise StarterAlreadyChosen("The free starter pet was already chosen.")
                return StarterChoice(item_id, False)
            owned = session.get(PetOwnershipModel, (user_id, item_id))
            if owned is not None:
                raise ItemAlreadyOwned("This pet is already owned.")
            now = _database_now(session)
            session.add(
                PetOwnershipModel(
                    user_id=user_id,
                    item_id=item_id,
                    acquisition_kind="starter",
                    purchase_id=None,
                    acquired_at=now,
                )
            )
            equipment = session.get(PetEquipmentModel, user_id)
            if equipment is None:
                session.add(
                    PetEquipmentModel(
                        user_id=user_id,
                        equipped_pet_id=item_id,
                        equipped_cosmetic_id=None,
                        equipped_animation_id=None,
                        updated_at=now,
                    )
                )
            return StarterChoice(item_id, True)

    def purchase(self, user_id: UUID, request_id: UUID, item_id: str) -> PurchaseResult:
        """One idempotent debit and permanent ownership, under the user lock."""
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            earlier = session.scalar(
                select(PetPurchaseModel)
                .where(
                    PetPurchaseModel.user_id == user_id,
                    PetPurchaseModel.request_id == request_id,
                )
                .with_for_update()
            )
            if earlier is not None:
                if earlier.item_id != item_id:
                    raise PurchaseRequestConflict("Purchase request was used for another item.")
                ledger = session.scalar(
                    select(CoinLedgerModel).where(
                        CoinLedgerModel.user_id == user_id,
                        CoinLedgerModel.kind == CoinLedgerKind.PET_PURCHASE.value,
                        CoinLedgerModel.source_id == earlier.id,
                    )
                )
                if ledger is None:
                    raise RuntimeError("Committed purchase is missing its debit ledger.")
                return PurchaseResult(
                    earlier.id,
                    request_id,
                    earlier.item_id,
                    earlier.price_charged,
                    ledger.balance_after,
                    True,
                )

            item = _item(item_id)
            if session.get(PetOwnershipModel, (user_id, item_id)) is not None:
                raise ItemAlreadyOwned("This item is already owned.")
            now = _database_now(session)
            wallet = _locked_wallet(session, user_id, now)
            if wallet.balance < item.coin_price:
                raise InsufficientCoins("Not enough earned coins for this item.")
            balance_after = wallet.balance - item.coin_price
            purchase_id = uuid4()
            wallet.balance = balance_after
            wallet.state_version += 1
            wallet.updated_at = now
            session.add(
                PetPurchaseModel(
                    id=purchase_id,
                    user_id=user_id,
                    request_id=request_id,
                    item_id=item_id,
                    price_charged=item.coin_price,
                    created_at=now,
                )
            )
            # Ownership has an immediate composite FK to this purchase. Keep
            # both rows in one transaction, but insert the parent first.
            session.flush()
            session.add(
                CoinLedgerModel(
                    id=uuid4(),
                    user_id=user_id,
                    kind=CoinLedgerKind.PET_PURCHASE.value,
                    source_id=purchase_id,
                    amount=-item.coin_price,
                    balance_after=balance_after,
                    study_date=None,
                    created_at=now,
                )
            )
            session.add(
                PetOwnershipModel(
                    user_id=user_id,
                    item_id=item_id,
                    acquisition_kind="purchase",
                    purchase_id=purchase_id,
                    acquired_at=now,
                )
            )
            return PurchaseResult(
                purchase_id,
                request_id,
                item_id,
                item.coin_price,
                balance_after,
                False,
            )

    def equip(
        self,
        user_id: UUID,
        *,
        pet_id: str,
        cosmetic_id: str | None,
        animation_id: str | None,
    ) -> EquipmentSelection:
        _item(pet_id, kind=CatalogKind.PET)
        if cosmetic_id is not None:
            _item(cosmetic_id, kind=CatalogKind.COSMETIC)
        if animation_id is not None:
            _item(animation_id, kind=CatalogKind.ANIMATION)
        requested = {pet_id, cosmetic_id, animation_id} - {None}
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            owned = set(
                session.scalars(
                    select(PetOwnershipModel.item_id).where(
                        PetOwnershipModel.user_id == user_id,
                        PetOwnershipModel.item_id.in_(requested),
                    )
                ).all()
            )
            if requested != owned:
                raise EquipmentNotOwned("Equip only earned or owned items.")
            now = _database_now(session)
            equipment = session.scalar(
                select(PetEquipmentModel)
                .where(PetEquipmentModel.user_id == user_id)
                .with_for_update()
            )
            if equipment is None:
                equipment = PetEquipmentModel(
                    user_id=user_id,
                    equipped_pet_id=pet_id,
                    equipped_cosmetic_id=cosmetic_id,
                    equipped_animation_id=animation_id,
                    updated_at=now,
                )
                session.add(equipment)
            else:
                equipment.equipped_pet_id = pet_id
                equipment.equipped_cosmetic_id = cosmetic_id
                equipment.equipped_animation_id = animation_id
                equipment.updated_at = now
            return EquipmentSelection(pet_id, cosmetic_id, animation_id)

    def get_state(self, user_id: UUID) -> PetState:
        with self._session_factory.begin() as session:
            _lock_active_user(session, user_id)
            ownership = session.scalars(
                select(PetOwnershipModel)
                .where(PetOwnershipModel.user_id == user_id)
                .order_by(PetOwnershipModel.item_id)
            ).all()
            equipment = session.get(PetEquipmentModel, user_id)
            wallet = session.get(CoinWalletModel, user_id)
            return PetState(
                catalog=tuple(PET_CATALOG.values()),
                owned_item_ids=tuple(item.item_id for item in ownership),
                starter_pet_id=next(
                    (item.item_id for item in ownership if item.acquisition_kind == "starter"),
                    None,
                ),
                equipment=(
                    EquipmentSelection(
                        equipment.equipped_pet_id,
                        equipment.equipped_cosmetic_id,
                        equipment.equipped_animation_id,
                    )
                    if equipment is not None
                    else None
                ),
                balance=wallet.balance if wallet is not None else 0,
            )
