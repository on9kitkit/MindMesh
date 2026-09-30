from typing import Literal

from pydantic import BaseModel, ConfigDict


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    confirmation: Literal["DELETE"]


class AccountDeletionResponse(BaseModel):
    status: Literal["account_deleted"]
    local_deletion_complete: Literal[True]
    provider_cleanup_pending: bool
