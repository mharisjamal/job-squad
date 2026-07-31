"""Pydantic request models and wire serializers (snake_case, UTC ISO 8601 with Z)."""

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .models import (
    Activity,
    Application,
    Comment,
    Company,
    Group,
    GroupMember,
    Portal,
    PortalStatus,
    Resume,
    User,
)

ApplicationStatus = Literal[
    "saved", "applied", "assessment", "interview", "offer", "rejected", "ghosted"
]
PortalMemberStatus = Literal["none", "signed_up", "active", "abandoned"]

# Size caps for user-supplied text (defense in depth with the 1 MB body cap).
NAME_MAX = 120
URL_MAX = 2000
NOTES_MAX = 10000
# A pasted job description is far longer than a note; capped so the match
# report and the DB column stay bounded (422 past this).
JD_TEXT_MAX = 50000
# A portal's market label, e.g. "Middle East", "USA", "Global".
REGION_MAX = 60
TAGS_MAX_ITEMS = 20
TagStr = Annotated[str, StringConstraints(max_length=50)]


class RegisterIn(BaseModel):
    """Signup body. There is no username field: the server derives the handle."""

    display_name: str = Field(max_length=NAME_MAX)
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("display_name must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _normalize_email_value(value)


class LoginIn(BaseModel):
    """`identifier` is an email or a username. The legacy {username, password}
    body still works so pre-existing accounts and clients keep signing in."""

    identifier: str | None = Field(default=None, max_length=320)
    username: str | None = Field(default=None, max_length=320)
    password: str = Field(max_length=200)

    @model_validator(mode="after")
    def _require_an_identifier(self) -> "LoginIn":
        if not (self.identifier or self.username):
            raise ValueError("identifier is required")
        return self

    @property
    def login_key(self) -> str:
        return (self.identifier or self.username or "").strip().lower()


# Conservative email check: Pydantic's EmailStr needs the email-validator
# package and this project deliberately adds no dependencies. This catches
# typos and junk without trying to be RFC-complete.
_EMAIL_RE = re.compile(
    r"[^@\s,;:<>\"]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+"
)


def _normalize_email_value(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 320 or not _EMAIL_RE.fullmatch(value):
        raise ValueError("enter a valid email address")
    return value


def _clean_region(value: str | None) -> str | None:
    """Trim a portal region; an empty/whitespace-only value becomes null."""
    if value is None:
        return None
    return value.strip() or None


class RegisterStartIn(RegisterIn):
    """Same body as RegisterIn: {display_name, email, password}."""


class RegisterVerifyIn(BaseModel):
    email: str = Field(max_length=320)
    code: str = Field(max_length=12)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _normalize_email_value(value)

    @field_validator("code")
    @classmethod
    def _code_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("code must not be blank")
        return value


class GroupCreateIn(BaseModel):
    name: str = Field(max_length=NAME_MAX)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class GroupJoinIn(BaseModel):
    invite_code: str = Field(max_length=20)


class GroupRenameIn(GroupCreateIn):
    pass


class CompanyCreateIn(BaseModel):
    name: str = Field(max_length=NAME_MAX)
    website: str | None = Field(default=None, max_length=URL_MAX)
    careers_url: str | None = Field(default=None, max_length=URL_MAX)
    location: str | None = Field(default=None, max_length=NAME_MAX)
    tags: list[TagStr] = Field(default_factory=list, max_length=TAGS_MAX_ITEMS)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class CompanyPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX)
    website: str | None = Field(default=None, max_length=URL_MAX)
    careers_url: str | None = Field(default=None, max_length=URL_MAX)
    location: str | None = Field(default=None, max_length=NAME_MAX)
    tags: list[TagStr] | None = Field(default=None, max_length=TAGS_MAX_ITEMS)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    archived: bool | None = None


class ApplicationPutIn(BaseModel):
    status: ApplicationStatus
    applied_via_portal_id: int | None = None
    resume_id: int | None = None
    applied_at: date | None = None
    follow_up_at: date | None = None
    url: str | None = Field(default=None, max_length=URL_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    jd_text: str | None = Field(default=None, max_length=JD_TEXT_MAX)


RESUME_LABEL_MAX = 80


class ResumePatchIn(BaseModel):
    label: str = Field(max_length=RESUME_LABEL_MAX)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value


AIProvider = Literal["gemini", "groq", "custom"]

# The tailored LaTeX the model returns is bounded so a runaway reply cannot be
# stored unbounded; comfortably larger than any real single-page resume source.
TEX_SOURCE_MAX = 200_000


class AISettingsPutIn(BaseModel):
    """Save a user's BYOK AI settings. A blank/omitted key keeps the stored one;
    switching to a preset provider fills base_url/model when they are omitted."""

    provider: AIProvider
    base_url: str | None = Field(default=None, max_length=URL_MAX)
    model: str | None = Field(default=None, max_length=200)
    key: str | None = Field(default=None, max_length=500)


class TailorIn(BaseModel):
    resume_id: int


class TexCompileIn(BaseModel):
    tex_source: str = Field(min_length=1, max_length=TEX_SOURCE_MAX)
    label: str = Field(max_length=RESUME_LABEL_MAX)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("label must not be blank")
        return value


class PortalCreateIn(BaseModel):
    name: str = Field(max_length=NAME_MAX)
    url: str | None = Field(default=None, max_length=URL_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    region: str | None = Field(default=None, max_length=REGION_MAX)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("region")
    @classmethod
    def _clean_region_value(cls, value: str | None) -> str | None:
        return _clean_region(value)


class PortalPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX)
    url: str | None = Field(default=None, max_length=URL_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    region: str | None = Field(default=None, max_length=REGION_MAX)

    @field_validator("region")
    @classmethod
    def _clean_region_value(cls, value: str | None) -> str | None:
        return _clean_region(value)


class PortalStatusPutIn(BaseModel):
    status: PortalMemberStatus
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)


class CommentIn(BaseModel):
    body: str = Field(max_length=NOTES_MAX)

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
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_url": user.avatar_url,
    }


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


def serialize_application_brief(
    row: Application, user: User, resume_label: str | None = None
) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": row.status,
        "applied_at": iso_date(row.applied_at),
        "resume_id": row.resume_id,
        "resume_label": resume_label,
        "updated_at": iso_z(row.updated_at),
    }


def serialize_application_full(
    row: Application,
    user: User,
    company_name: str,
    portal_name: str | None,
    resume_label: str | None = None,
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
        "resume_id": row.resume_id,
        "resume_label": resume_label,
        "applied_at": iso_date(row.applied_at),
        "follow_up_at": iso_date(row.follow_up_at),
        "url": row.url,
        "notes": row.notes,
        "jd_text": row.jd_text,
        "created_at": iso_z(row.created_at),
        "updated_at": iso_z(row.updated_at),
    }


def serialize_resume(resume: Resume, attached_count: int) -> dict:
    return {
        "id": resume.id,
        "label": resume.label,
        "filename": resume.filename,
        "kind": resume.kind,
        "size_bytes": resume.size_bytes,
        "created_at": iso_z(resume.created_at),
        "attached_count": attached_count,
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
        "region": portal.region,
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
