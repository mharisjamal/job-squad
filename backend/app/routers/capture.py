"""Browser-extension capture endpoints (Phase E1).

One POST that turns a job posting the user is looking at into a company, a
portal and their own application, and a lookup that answers "does my squad
already know this company?" before anything is written.

Every route here is group-scoped and member-only: a group the caller does not
belong to is a 404, so none of them can be used to write into, or read out of, a
stranger's squad. The lookup exists in two shapes, GET and POST, with identical
behavior: the POST carries the browsed URL in the body, where it stays out of
the access log.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..capture import (
    company_domain,
    normalize_company_name,
    portal_name_for_domain,
    registrable_domain,
)
from ..deps import get_current_user, get_session, require_member
from ..models import Application, Company, Portal, User, utcnow
from ..schemas import NAME_MAX, URL_MAX, CaptureIn, CaptureLookupIn

router = APIRouter(tags=["capture"])

# A capture is a bookmark, not an application: the user says they applied.
DEFAULT_CAPTURE_STATUS = "saved"


async def _find_company(
    session: AsyncSession, group_id: int, name: str | None, website: str | None
) -> Company | None:
    """The existing company this capture belongs to, or None.

    Normalized name wins; a website whose registrable domain matches an existing
    company's is the fallback, which is what stops a second capture that spells
    the name differently ("Acme Inc" vs "Acme") from creating a twin.

    KNOWN AND ACCEPTED LIMIT: there is no unique constraint on
    companies(group_id, name), so two members capturing the same brand-new
    company at the same instant can still create twin rows. Sequential
    re-capture dedupes correctly and the popup disables Save while a capture is
    in flight, so the window is tiny; adding the constraint would have to
    reckon with the existing hand-created rows, which is a bigger change than
    the risk warrants.
    """
    wanted_name = normalize_company_name(name)
    wanted_domain = company_domain(website)
    if not wanted_name and not wanted_domain:
        return None
    # Three light columns for one group's companies: no application rows, no
    # notes, nothing that grows with usage.
    rows = (
        await session.execute(
            select(Company.id, Company.name, Company.website).where(
                Company.group_id == group_id
            )
        )
    ).all()
    domain_match: int | None = None
    for company_id, existing_name, existing_website in rows:
        if wanted_name and normalize_company_name(existing_name) == wanted_name:
            return await session.get(Company, company_id)
        if (
            wanted_domain
            and domain_match is None
            and company_domain(existing_website) == wanted_domain
        ):
            domain_match = company_id
    if domain_match is not None:
        return await session.get(Company, domain_match)
    return None


async def _find_or_create_portal(
    session: AsyncSession, group_id: int, user: User, posting_url: str | None
) -> tuple[Portal | None, bool]:
    """The portal this posting came from, created on first sight.

    Matched on the portal's name or its own URL's domain, so a portal the squad
    already added by hand is reused instead of duplicated.
    """
    domain = registrable_domain(posting_url)
    name = portal_name_for_domain(domain)
    if domain is None or name is None:
        return None, False
    portals = (
        await session.scalars(select(Portal).where(Portal.group_id == group_id))
    ).all()
    wanted = name.strip().lower()
    for portal in portals:
        if (portal.name or "").strip().lower() == wanted:
            return portal, False
        if registrable_domain(portal.url) == domain:
            return portal, False
    portal = Portal(
        group_id=group_id, name=name, url=f"https://{domain}", created_by=user.id
    )
    session.add(portal)
    await session.flush()
    return portal, True


async def _capture_once(
    session: AsyncSession, request: Request, body: CaptureIn, user: User
) -> dict:
    await require_member(session, body.group_id, user)

    company = await _find_company(
        session, body.group_id, body.company_name, body.company_website
    )
    created_company = company is None
    if company is None:
        company = Company(
            group_id=body.group_id,
            name=body.company_name,
            website=body.company_website,
            careers_url=body.careers_url,
            location=body.location,
            created_by=user.id,
        )
        session.add(company)
        await session.flush()
    else:
        # Fill blanks only. A capture enriches what the squad curated by hand;
        # it never overwrites it.
        for field, value in (
            ("website", body.company_website),
            ("careers_url", body.careers_url),
            ("location", body.location),
        ):
            if value and not getattr(company, field):
                setattr(company, field, value)

    portal, created_portal = await _find_or_create_portal(
        session, body.group_id, user, body.posting_url
    )

    row = await session.scalar(
        select(Application).where(
            Application.company_id == company.id, Application.user_id == user.id
        )
    )
    old_status = row.status if row is not None else None
    if row is None:
        row = Application(
            company_id=company.id,
            user_id=user.id,
            status=body.status or DEFAULT_CAPTURE_STATUS,
        )
        session.add(row)
    elif body.status is not None:
        # Merge semantics: an omitted status leaves an existing application
        # where it is. Re-capturing a posting must never drag an interview back
        # to "saved".
        row.status = body.status
    if body.posting_url:
        row.url = body.posting_url
    if body.job_title:
        # A capture that could not read the role leaves the one already saved
        # alone; it never blanks a title the user typed.
        row.job_title = body.job_title
    if body.jd_text:
        row.jd_text = body.jd_text
    if portal is not None:
        row.applied_via_portal_id = portal.id
    row.updated_at = utcnow()
    await session.flush()

    broker = request.app.state.broker
    if created_portal and portal is not None:
        await record(
            session,
            broker,
            group_id=body.group_id,
            user=user,
            type_="portal_added",
            portal=portal,
        )
    if created_company:
        await record(
            session,
            broker,
            group_id=body.group_id,
            user=user,
            type_="company_added",
            company=company,
        )
    if old_status != row.status:
        await record(
            session,
            broker,
            group_id=body.group_id,
            user=user,
            type_="application_status_changed",
            company=company,
            detail={"from": old_status, "to": row.status},
        )
    await session.commit()
    return {
        "company_id": company.id,
        "company_name": company.name,
        "application_id": row.id,
        "status": row.status,
        "job_title": row.job_title,
        "created_company": created_company,
        "created_portal": created_portal,
        "portal_name": portal.name if portal is not None else None,
    }


@router.post("/capture")
async def capture(
    body: CaptureIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Save the posting the user is looking at, in one transaction.

    Company, portal and application land together or not at all, so a failure
    can never leave a company with no application against it.
    """
    for _attempt in range(2):
        try:
            return await _capture_once(session, request, body, user)
        except IntegrityError:
            # A concurrent capture inserted my application row first: start over
            # against the state it committed.
            await session.rollback()
    raise HTTPException(status_code=409, detail="Concurrent update, please retry")


async def _lookup(
    session: AsyncSession,
    user: User,
    group_id: int,
    url: str | None,
    company_name: str | None,
) -> dict:
    """What the squad already knows about this company, before saving anything.

    Resolved by the same rules the capture write uses, so the popup's preview
    and the row it later creates or updates always agree. Shared verbatim by the
    GET and POST forms, so the two can never drift in behavior or in authz.
    """
    await require_member(session, group_id, user)
    company = await _find_company(session, group_id, company_name, url)
    if company is None:
        return {
            "company_id": None,
            "company_name": None,
            "my_status": None,
            "squad": [],
        }
    rows = (
        await session.execute(
            select(Application, User)
            .join(User, User.id == Application.user_id)
            .where(Application.company_id == company.id)
            .order_by(Application.updated_at.desc())
        )
    ).all()
    my_status: str | None = None
    squad: list[dict] = []
    for application, member in rows:
        if member.id == user.id:
            my_status = application.status
        else:
            squad.append(
                {"display_name": member.display_name, "status": application.status}
            )
    return {
        "company_id": company.id,
        "company_name": company.name,
        "my_status": my_status,
        "squad": squad,
    }


@router.get("/capture/lookup")
async def capture_lookup(
    group_id: int = Query(ge=1, le=2**63 - 1),
    url: str | None = Query(default=None, max_length=URL_MAX),
    company_name: str | None = Query(default=None, max_length=NAME_MAX),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Query-string form, kept for compatibility. Prefer the POST: this one
    writes the browsed URL into the server's access log."""
    return await _lookup(session, user, group_id, url, company_name)


@router.post("/capture/lookup")
async def capture_lookup_post(
    body: CaptureLookupIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Body form: identical result and identical authz, with the browsed URL
    kept out of the query string (and therefore out of the access log)."""
    return await _lookup(session, user, body.group_id, body.url, body.company_name)
