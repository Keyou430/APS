from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import UserResponse


RoleName = Literal["admin", "manager", "user"]


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9._-]+$",
        examples=["alice"],
    )
    password: str = Field(min_length=8, max_length=128, examples=["change-me-123"])
    email: EmailStr = Field(examples=["alice@example.com"])
    role: RoleName = "user"


class UserUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=80,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    email: EmailStr | None = None
    is_active: bool | None = None


class RoleAssignment(BaseModel):
    role: RoleName


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    page_size: int
