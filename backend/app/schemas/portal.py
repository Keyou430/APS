from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class PortalSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CompanyResponse(PortalSchema):
    id: str
    name: str
    short_name: str
    industry: str = "Enterprise services"
    size: Literal["small", "medium", "large", "enterprise"] = "medium"
    description: str = ""


class DepartmentResponse(PortalSchema):
    id: str
    name: str
    parent_id: str | None = None
    member_count: int = Field(ge=0)


class PositionResponse(PortalSchema):
    id: str
    title: str
    department_id: str
    level: str


class PersonResponse(PortalSchema):
    id: str
    name: str
    email: str
    department_id: str
    department: str
    position_id: str
    position: str
    avatar: str | None = None
    joined_at: datetime | None = None


class CurrentUserResponse(PersonResponse):
    role: Literal["admin", "manager", "user"]


class AnnouncementResponse(PortalSchema):
    id: str
    title: str
    summary: str
    author: str
    priority: Literal["normal", "important"]
    published_at: datetime | None
    content: str | None = Field(default=None, max_length=100_000)
    is_pinned: bool = False
    is_read: bool = False
    status: Literal["draft", "published", "withdrawn"] = "published"


class AnnouncementCreate(PortalSchema):
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(default="", max_length=500)
    content: str | None = Field(default=None, max_length=100_000)
    priority: Literal["normal", "important"] = "normal"


class AnnouncementUpdate(PortalSchema):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=500)
    content: str | None = None
    priority: Literal["normal", "important"] | None = None


class AnnouncementPinUpdate(PortalSchema):
    is_pinned: bool


class AnnouncementListResponse(PortalSchema):
    items: list[AnnouncementResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class ActivityResponse(PortalSchema):
    id: str
    type: Literal["news", "notice", "event"]
    title: str
    summary: str
    occurred_at: datetime


class PortalTodoResponse(PortalSchema):
    id: str
    title: str
    due_at: datetime | None = None
    priority: Literal["low", "medium", "high"]
    completed: bool
    href: str | None = None


class PortalTodoUpdate(PortalSchema):
    completed: bool


class QuickLinkResponse(PortalSchema):
    id: str
    name: str
    url: str
    icon: str
    order: int = Field(ge=0)


class EnterpriseInfoResponse(PortalSchema):
    company: CompanyResponse
    current_user: CurrentUserResponse
    announcements: list[AnnouncementResponse]
    departments: list[DepartmentResponse]
    positions: list[PositionResponse]
    people: list[PersonResponse]


class EnterprisePortalResponse(EnterpriseInfoResponse):
    activities: list[ActivityResponse]
    todos: list[PortalTodoResponse]
    quick_links: list[QuickLinkResponse]
    collaborators: list[PersonResponse]


DashboardWidgetType = Literal[
    "todo",
    "pipeline",
    "calendar",
    "notification",
    "recent-visits",
    "quick-actions",
    "business-overview",
    "approval",
    "quick-entry",
    "knowledge",
    "activity",
    "statistics",
]


class DashboardWidgetResponse(PortalSchema):
    id: str
    type: DashboardWidgetType
    title: str
    enabled: bool = True
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)


class DashboardGridItem(PortalSchema):
    i: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)
    min_w: int | None = Field(default=None, gt=0)
    min_h: int | None = Field(default=None, gt=0)
    max_w: int | None = Field(default=None, gt=0)
    max_h: int | None = Field(default=None, gt=0)
    static: bool = False


class DashboardLayouts(PortalSchema):
    lg: list[DashboardGridItem]
    md: list[DashboardGridItem]
    sm: list[DashboardGridItem]
    xs: list[DashboardGridItem] | None = None
    xxs: list[DashboardGridItem] | None = None


class DashboardLayoutUpdate(PortalSchema):
    layouts: DashboardLayouts
    expected_revision: int = Field(ge=1)


class DashboardLayoutResponse(PortalSchema):
    id: str
    user_id: str
    layouts: DashboardLayouts
    updated_at: datetime
    revision: int
    widgets: list[DashboardWidgetResponse]


class DashboardDataResponse(PortalSchema):
    todos: list[dict[str, object]] = Field(default_factory=list)
    pipelines: list[dict[str, object]] = Field(default_factory=list)
    calendar_events: list[dict[str, object]] = Field(default_factory=list)
    notifications: list[dict[str, object]] = Field(default_factory=list)
    recent_visits: list[dict[str, object]] = Field(default_factory=list)
    quick_actions: list[dict[str, object]] = Field(default_factory=list)
    metrics: list[dict[str, object]] = Field(default_factory=list)
