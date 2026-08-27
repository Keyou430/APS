from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileCreate(BaseModel):
    user_id: int = Field(gt=0, examples=[1])


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    profile_name: str
    hermes_home: str
    port: int
    status: str
    created_at: datetime


class ProfileHealthResponse(BaseModel):
    user_id: int
    status: str
    healthy: bool
    detail: str
