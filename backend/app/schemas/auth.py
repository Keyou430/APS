from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import Role


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, examples=["admin"])
    password: str = Field(min_length=1, examples=["admin123"])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(description="Refresh token returned by the login endpoint")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds")
    organization_id: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None
    email: EmailStr
    role: str
    member_type: str = "internal"
    permissions: list[str] = Field(default_factory=list)
    membership_id: int | None = None
    membership_expires_at: datetime | None = None
    organization_id: int
    is_active: bool
    created_at: datetime

    @field_validator("role", mode="before")
    @classmethod
    def role_name(cls, value: object) -> object:
        return value.name if isinstance(value, Role) else value


class OrganizationMembershipResponse(BaseModel):
    organization_id: int
    organization_name: str
    organization_slug: str
    role: str
    member_type: str
    expires_at: datetime | None


class OrganizationMembershipListResponse(BaseModel):
    current_organization_id: int
    items: list[OrganizationMembershipResponse]


class SwitchOrganizationRequest(BaseModel):
    organization_id: int = Field(gt=0)
