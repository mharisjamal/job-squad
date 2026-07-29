"""Company endpoints: list with filters, create, detail, patch, delete."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..deps import (
    get_company_for_member,
    get_current_user,
    get_session,
    require_member,
)
from ..models import (
    APPLICATION_STATUSES,
    Application,
    Comment,
    Company,
    Group,
    Portal,
    User,
)
from ..schemas import (
    CompanyCreateIn,
    CompanyPatchIn,
    serialize_application_brief,
    serialize_application_full,
    serialize_comment,
    serialize_company,
)

router = APIRouter(tags=["companies"])


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards (and the escape char itself) in user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _company_extras(
    session: AsyncSession, company_ids: list[int]
) -> tuple[dict[int, list[dict]], dict[int, int]]:
    """Batch-load ApplicationBrief lists and comment counts for the given companies."""
    briefs: dict[int, list[dict]] = {cid: [] for cid in company_ids}
    counts: dict[int, int] = {cid: 0 for cid in company_ids}
    if not company_ids:
        return briefs, counts
    app_rows = (
        await session.execute(
            select(Application, User)
            .join(User, User.id == Application.user_id)
            .where(Application.company_id.in_(company_ids))
            .order_by(Application.updated_at.desc())
        )
    ).all()
    for app_row, user in app_rows:
        briefs[app_row.company_id].append(serialize_application_brief(app_row, user))
    count_rows = (
        await session.execute(
            select(Comment.company_id, func.count())
            .where(Comment.company_id.in_(company_ids))
            .group_by(Comment.company_id)
        )
    ).all()
    for cid, count in count_rows:
        counts[cid] = int(count)
    return briefs, counts


async def _serialize_one(session: AsyncSession, company: Company) -> dict:
    creator = await session.get(User, company.created_by)
    briefs, counts = await _company_extras(session, [company.id])
    return serialize_company(
        company,
        creator.username if creator else "",
        briefs[company.id],
        counts[company.id],
    )


@router.get("/groups/{gid}/companies")
async def list_companies(
    gid: int,
    q: str | None = Query(default=None, max_length=200),
    tag: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_member(session, gid, user)
    query = (
        select(Company, User.username)
        .join(User, User.id == Company.created_by)
        .where(Company.group_id == gid)
    )
    if not include_archived:
        query = query.where(Company.archived.is_(False))
    if q:
        needle = f"%{_escape_like(q.strip().lower())}%"
        query = query.where(
            func.lower(Company.name).like(needle, escape="\\")
            | func.lower(func.coalesce(Company.location, "")).like(needle, escape="\\")
        )
    if status:
        my_app = exists().where(
            Application.company_id == Company.id, Application.user_id == user.id
        )
        if status == "not_applied":
            query = query.where(~my_app)
        elif status in APPLICATION_STATUSES:
            query = query.where(
                exists().where(
                    Application.company_id == Company.id,
                    Application.user_id == user.id,
                    Application.status == status,
                )
            )
        else:
            raise HTTPException(status_code=422, detail="Invalid status filter")
    query = query.order_by(Company.updated_at.desc())
    rows = (await session.execute(query)).all()
    if tag:
        wanted = tag.strip().lower()
        rows = [
            (company, username)
            for company, username in rows
            if any(str(t).strip().lower() == wanted for t in (company.tags or []))
        ]
    company_ids = [company.id for company, _ in rows]
    briefs, counts = await _company_extras(session, company_ids)
    return [
        serialize_company(company, username, briefs[company.id], counts[company.id])
        for company, username in rows
    ]


@router.post("/groups/{gid}/companies")
async def create_company(
    gid: int,
    body: CompanyCreateIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_member(session, gid, user)
    company = Company(
        group_id=gid,
        name=body.name,
        website=body.website,
        careers_url=body.careers_url,
        location=body.location,
        tags=body.tags,
        notes=body.notes,
        created_by=user.id,
    )
    session.add(company)
    await session.flush()
    await record(
        session,
        request.app.state.broker,
        group_id=gid,
        user=user,
        type_="company_added",
        company=company,
    )
    await session.commit()
    return serialize_company(company, user.username, [], 0)


@router.get("/companies/{cid}")
async def company_detail(
    cid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    creator = await session.get(User, company.created_by)
    app_rows = (
        await session.execute(
            select(Application, User, Portal)
            .join(User, User.id == Application.user_id)
            .outerjoin(Portal, Portal.id == Application.applied_via_portal_id)
            .where(Application.company_id == cid)
            .order_by(Application.updated_at.desc())
        )
    ).all()
    comment_rows = (
        await session.execute(
            select(Comment, User)
            .join(User, User.id == Comment.user_id)
            .where(Comment.company_id == cid)
            .order_by(Comment.created_at)
        )
    ).all()
    applications = [
        serialize_application_full(a, u, company.name, p.name if p else None)
        for a, u, p in app_rows
    ]
    payload = serialize_company(
        company,
        creator.username if creator else "",
        applications,
        len(comment_rows),
    )
    payload["comments"] = [serialize_comment(c, u) for c, u in comment_rows]
    return payload


@router.patch("/companies/{cid}")
async def patch_company(
    cid: int,
    body: CompanyPatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    provided = body.model_dump(exclude_unset=True)
    if "name" in provided:
        name = (provided["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be blank")
        company.name = name
    for field in ("website", "careers_url", "location", "notes"):
        if field in provided:
            setattr(company, field, provided[field])
    if "tags" in provided:
        company.tags = provided["tags"] or []
    if "archived" in provided and provided["archived"] is not None:
        company.archived = provided["archived"]
    await session.commit()
    return await _serialize_one(session, company)


@router.delete("/companies/{cid}")
async def delete_company(
    cid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    group = await session.get(Group, company.group_id)
    if company.created_by != user.id and (group is None or group.owner_id != user.id):
        raise HTTPException(
            status_code=403, detail="Only the poster or the group owner can delete a company"
        )
    await session.delete(company)
    await session.commit()
    return {"ok": True}
