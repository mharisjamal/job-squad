"""Pydantic request models and wire serializers (snake_case, UTC ISO 8601 with Z)."""

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import (
    Activity,
    Application,
    Comment,
    Company,
    Group,
    GroupMember,
    Portal,
    PortalStatus,
    User,
)

ApplicationStatus = Literal[
    "saved", "applied", "assessment", "interview", "offer", "rejected", "ghosted"
]
PortalMemberStatus = Literal["none", "signed_up", "active", "abandoned"]

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")


class RegisterIn(BaseModel):
    username: str
    display_name: str
    password: str = Field(min_length=8)

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not _USERNAME_RE.fullmatch(value):
            raise ValueError("username must be 3-30 chars of a-z, 0-9 or _")
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must not be blank")
        return value


class LoginIn(BaseModel):
    username: str
    password: str


class GroupCreateIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class GroupJoinIn(BaseModel):
    invite_code: str


class GroupRenameIn(GroupCreateIn):
    pass


class CompanyCreateIn(BaseModel):
    name: str
    website: str | None = None
    careers_url: str | None = None
    location: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class CompanyPatchIn(BaseModel):
    name: str | None = None
    website: str | None = None
    careers_url: str | None = None
    location: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    archived: bool | None = None


class ApplicationPutIn(BaseModel):
    status: ApplicationStatus
    applied_via_portal_id: int | None = None
    applied_at: date | None = None
    follow_up_at: date | None = None
    url: str | None = None
    notes: str | None = None


class PortalCreateIn(BaseModel):
    name: str
    url: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class PortalPatchIn(BaseModel):
    name: str | None = None
    url: str | None = None
    notes: str | None = None


class PortalStatusPutIn(BaseModel):
    status: PortalMemberStatus
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = None


class CommentIn(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("body must not be blank")
        return value


# ---------------------------------------------------------------------------
# Wire serializers (plain dicts so nested/computed shapes match the contract)
# ---------------------------------------------------------------------------


def iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def iso_date(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def serialize_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name}


def serialize_group(group: Group, member_count: int) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "invite_code": group.invite_code,
        "owner_id": group.owner_id,
        "created_at": iso_z(group.created_at),
        "member_count": member_count,
    }


def serialize_group_member(member: GroupMember, user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": member.role,
        "joined_at": iso_z(member.joined_at),
    }


def serialize_application_brief(row: Application, user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": row.status,
        "applied_at": iso_date(row.applied_at),
        "updated_at": iso_z(row.updated_at),
    }


def serialize_application_full(
    row: Application, user: User, company_name: str, portal_name: str | None
) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "company_name": company_name,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": row.status,
        "applied_via_portal_id": row.applied_via_portal_id,
        "applied_via_portal_name": portal_name,
        "applied_at": iso_date(row.applied_at),
        "follow_up_at": iso_date(row.follow_up_at),
        "url": row.url,
        "notes": row.notes,
        "created_at": iso_z(row.created_at),
        "updated_at": iso_z(row.updated_at),
    }


def serialize_company(
    company: Company,
    created_by_username: str,
    applications: list[dict],
    comment_count: int,
) -> dict:
    return {
        "id": company.id,
        "group_id": company.group_id,
        "name": company.name,
        "website": company.website,
        "careers_url": company.careers_url,
        "location": company.location,
        "tags": list(company.tags or []),
        "notes": company.notes,
        "archived": company.archived,
        "created_by": company.created_by,
        "created_by_username": created_by_username,
        "created_at": iso_z(company.created_at),
        "updated_at": iso_z(company.updated_at),
        "applications": applications,
        "comment_count": comment_count,
    }


def serialize_portal_status(row: PortalStatus, user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": row.status,
        "rating": row.rating,
        "notes": row.notes,
        "updated_at": iso_z(row.updated_at),
    }


def serialize_portal(
    portal: Portal,
    created_by_username: str,
    statuses: list[dict],
    stats: dict,
) -> dict:
    return {
        "id": portal.id,
        "group_id": portal.group_id,
        "name": portal.name,
        "url": portal.url,
        "notes": portal.notes,
        "created_by": portal.created_by,
        "created_by_username": created_by_username,
        "created_at": iso_z(portal.created_at),
        "updated_at": iso_z(portal.updated_at),
        "statuses": statuses,
        "stats": stats,
    }


def serialize_comment(comment: Comment, user: User) -> dict:
    return {
        "id": comment.id,
        "company_id": comment.company_id,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "body": comment.body,
        "created_at": iso_z(comment.created_at),
    }


def serialize_activity(
    row: Activity,
    username: str,
    display_name: str,
    company_name: str | None,
    portal_name: str | None,
) -> dict:
    return {
        "id": row.id,
        "group_id": row.group_id,
        "user_id": row.user_id,
        "username": username,
        "display_name": display_name,
        "type": row.type,
        "company_id": row.company_id,
        "company_name": company_name,
        "portal_id": row.portal_id,
        "portal_name": portal_name,
        "detail": dict(row.detail or {}),
        "created_at": iso_z(row.created_at),
    }
