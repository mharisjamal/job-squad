"""Application endpoints: PUT upsert of my row, delete mine, group-wide list."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
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
    Company,
    Portal,
    User,
    utcnow,
)
from ..schemas import ApplicationPutIn, serialize_application_full

router = APIRouter(tags=["applications"])


@router.put("/companies/{cid}/application")
async def upsert_application(
    cid: int,
    body: ApplicationPutIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    portal: Portal | None = None
    if body.applied_via_portal_id is not None:
        portal = await session.get(Portal, body.applied_via_portal_id)
        if portal is None or portal.group_id != company.group_id:
            raise HTTPException(status_code=422, detail="Unknown portal for this group")
    row = await session.scalar(
        select(Application).where(
            Application.company_id == cid, Application.user_id == user.id
        )
    )
    old_status = row.status if row is not None else None
    if row is None:
        row = Application(company_id=cid, user_id=user.id, status=body.status)
        session.add(row)
    row.status = body.status
    row.applied_via_portal_id = body.applied_via_portal_id
    row.applied_at = body.applied_at
    row.follow_up_at = body.follow_up_at
    row.url = body.url
    row.notes = body.notes
    row.updated_at = utcnow()
    await session.flush()
    if old_status != body.status:
        await record(
            session,
            request.app.state.broker,
            group_id=company.group_id,
            user=user,
            type_="application_status_changed",
            company=company,
            detail={"from": old_status, "to": body.status},
        )
    await session.commit()
    return serialize_application_full(row, user, company.name, portal.name if portal else None)


@router.delete("/companies/{cid}/application")
async def delete_application(
    cid: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    row = await session.scalar(
        select(Application).where(
            Application.company_id == cid, Application.user_id == user.id
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No application to remove")
    await session.delete(row)
    await record(
        session,
        request.app.state.broker,
        group_id=company.group_id,
        user=user,
        type_="application_removed",
        company=company,
    )
    await session.commit()
    return {"ok": True}


@router.get("/groups/{gid}/applications")
async def list_applications(
    gid: int,
    user_id: str | None = None,
    status: str | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
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
    if status:
        if status not in APPLICATION_STATUSES:
            raise HTTPException(status_code=422, detail="Invalid status filter")
        query = query.where(Application.status == status)
    rows = (await session.execute(query.order_by(Application.updated_at.desc()))).all()
    return [
        serialize_application_full(a, u, c.name, p.name if p else None)
        for a, u, c, p in rows
    ]
