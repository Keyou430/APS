from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrganizationUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None
    name: str
    code: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationPositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_id: int
    title: str
    level: str | None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OrganizationPlacementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_id: int
    unit_id: int
    position_id: int
    manager_membership_id: int | None
    created_at: datetime
    updated_at: datetime


class OrganizationPersonResponse(BaseModel):
    membership_id: int
    user_id: int
    username: str
    email: str
    role: str
    member_type: str


class OrganizationStructureResponse(BaseModel):
    organization_id: int
    revision: int
    units: list[OrganizationUnitResponse]
    positions: list[OrganizationPositionResponse]
    placements: list[OrganizationPlacementResponse]
    people: list[OrganizationPersonResponse]


class RevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class OrganizationUnitCreate(RevisionRequest):
    parent_id: int
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    sort_order: int = 0


class OrganizationUnitUpdate(RevisionRequest):
    parent_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    sort_order: int | None = None
    is_active: bool | None = None


class OrganizationPositionCreate(RevisionRequest):
    unit_id: int
    title: str = Field(min_length=1, max_length=255)
    level: str | None = Field(default=None, max_length=80)
    sort_order: int = 0


class OrganizationPositionUpdate(RevisionRequest):
    unit_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    level: str | None = Field(default=None, max_length=80)
    sort_order: int | None = None
    is_active: bool | None = None


class OrganizationPlacementInput(BaseModel):
    membership_id: int
    unit_id: int
    position_id: int
    manager_membership_id: int | None = None


class OrganizationPlacementUpdate(RevisionRequest):
    unit_id: int
    position_id: int
    manager_membership_id: int | None = None


class OrganizationPlacementBatch(RevisionRequest):
    items: list[OrganizationPlacementInput] = Field(min_length=1, max_length=200)
