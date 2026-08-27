from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class InvitationCreate(BaseModel):
    email: EmailStr
    token_expires_at: datetime
    membership_expires_at: datetime | None = None
    resource_ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().casefold() if isinstance(value, str) else value

    @field_validator("resource_ids")
    @classmethod
    def unique_resources(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value) or len(set(value)) != len(value):
            raise ValueError("resource_ids must contain unique positive ids")
        return value

class InvitationResponse(BaseModel):
    id: int
    email: EmailStr
    status: Literal["pending", "accepted", "expired", "revoked"]
    token_expires_at: datetime
    membership_expires_at: datetime | None
    resource_ids: list[int]
    created_at: datetime


class InvitationCreatedResponse(InvitationResponse):
    token: str | None = None


class InvitationListResponse(BaseModel):
    items: list[InvitationResponse]


class InvitationRegenerate(BaseModel):
    token_expires_at: datetime


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    username: str | None = Field(default=None, min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
    password: str | None = Field(default=None, min_length=8, max_length=128)


class InvitationAcceptResponse(BaseModel):
    status: Literal["accepted", "already_accepted"]
    user_id: int
    membership_id: int
    organization_id: int


class GuestMembershipResponse(BaseModel):
    membership_id: int
    user_id: int
    username: str
    email: EmailStr
    status: Literal["active", "expired", "revoked"]
    expires_at: datetime | None
