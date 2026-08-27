"""Delivery observability endpoints (Phase 1 C2/C4).

Exposes outbox health and provider configuration status so operations can
distinguish feishu_not_configured from real send failures without ever
touching secrets.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import OrganizationContext, require_permission
from app.database import get_db
from app.models import DeliveryOutbox
from app.services.feishu_delivery import feishu_configuration_status

router = APIRouter(prefix="/api/delivery", tags=["Delivery"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
DeliveryContext = Annotated[
    OrganizationContext, Depends(require_permission("pipeline:observe"))
]


class DeliveryStatusResponse(BaseModel):
    providers: dict[str, str]
    outbox: dict[str, int]


@router.get("/status", response_model=DeliveryStatusResponse)
async def delivery_status(
    db: DbSession,
    context: DeliveryContext,
) -> DeliveryStatusResponse:
    rows = (
        await db.execute(
            select(DeliveryOutbox.status, func.count())
            .where(DeliveryOutbox.organization_id == context.organization_id)
            .group_by(DeliveryOutbox.status)
        )
    ).all()
    return DeliveryStatusResponse(
        providers={"feishu": feishu_configuration_status()},
        outbox={status: count for status, count in rows},
    )
