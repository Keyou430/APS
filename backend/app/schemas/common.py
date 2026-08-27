from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str = Field(description="Human-readable operation result")


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
