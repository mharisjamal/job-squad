"""CSV exports (text/csv attachments); auth also works via ?access_token=."""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session, require_member
from ..models import Application, Company, Portal, User
from ..schemas import iso_date, iso_z
from .portals import portal_stats

router = APIRouter(tags=["export"])


# Values starting with these can execute as formulas in spreadsheet apps.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _csv_response(filename: str, header: list[str], rows: list[list[str]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/groups/{gid}/export/applications.csv")
async def export_applications(
    gid: int,
    user_id: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_member(session, gid, user)
    query = (
        select(Application, User, Company, Portal)
        .join(Company, Company.id == Application.company_id)
        .join(User, User.id == Application.user_id)
        .outerjoin(Portal, Portal.id == Application.applied_via_portal_id)
        .where(Company.group_id == gid)
    )
    if user_id:
        if user_id == "me":
            target_id = user.id
        else:
            try:
                target_id = int(user_id)
            except ValueError:
                raise HTTPException(status_code=422, detail="Invalid user_id") from None
        query = query.where(Application.user_id == target_id)
    rows = (
        await session.execute(query.order_by(Company.name, User.username))
    ).all()
    header = [
        "company", "member", "status", "applied_at", "follow_up_at",
        "applied_via", "posting_url", "notes", "updated_at",
    ]
    data = [
        [
            _cell(company.name),
            _cell(member.display_name),
            _cell(application.status),
            _cell(iso_date(application.applied_at)),
            _cell(iso_date(application.follow_up_at)),
            _cell(portal.name) if portal is not None else "",
            _cell(application.url),
            _cell(application.notes),
            _cell(iso_z(application.updated_at)),
        ]
        for application, member, company, portal in rows
    ]
    return _csv_response("applications.csv", header, data)


@router.get("/groups/{gid}/export/companies.csv")
async def export_companies(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_member(session, gid, user)
    rows = (
        await session.execute(
            select(Company, User)
            .join(User, User.id == Company.created_by)
            .where(Company.group_id == gid)
            .order_by(Company.name)
        )
    ).all()
    header = [
        "name", "website", "careers_url", "location", "tags",
        "notes", "posted_by", "created_at", "archived",
    ]
    data = [
        [
            _cell(company.name),
            _cell(company.website),
            _cell(company.careers_url),
            _cell(company.location),
            _cell(";".join(str(t) for t in (company.tags or []))),
            _cell(company.notes),
            _cell(poster.display_name),
            _cell(iso_z(company.created_at)),
            "true" if company.archived else "false",
        ]
        for company, poster in rows
    ]
    return _csv_response("companies.csv", header, data)


@router.get("/groups/{gid}/export/portals.csv")
async def export_portals(
    gid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await require_member(session, gid, user)
    rows = (
        await session.execute(
            select(Portal, User)
            .join(User, User.id == Portal.created_by)
            .where(Portal.group_id == gid)
            .order_by(Portal.name)
        )
    ).all()
    stats = await portal_stats(session, [portal.id for portal, _ in rows])
    header = ["name", "url", "notes", "posted_by", "applications_via", "created_at"]
    data = [
        [
            _cell(portal.name),
            _cell(portal.url),
            _cell(portal.notes),
            _cell(poster.display_name),
            str(stats[portal.id]["applications_via"]),
            _cell(iso_z(portal.created_at)),
        ]
        for portal, poster in rows
    ]
    return _csv_response("portals.csv", header, data)
