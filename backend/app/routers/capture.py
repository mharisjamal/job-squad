"""Browser-extension capture endpoints (Phase E1).

One POST that turns a job posting the user is looking at into a company, a
portal and their own application, and a lookup that answers "does my squad
already know this company?" before anything is written.

Every route here is group-scoped and member-only: a group the caller does not
belong to is a 404, so none of them can be used to write into, or read out of, a
stranger's squad. The lookup exists in three shapes with identical matching and
identical authz: GET (query string), POST (the browsed URL stays in the body,
out of the access log) and POST .../batch (Phase E2: a whole job-board results
page in one bounded round trip).
"""

from collections.abc import Sequence

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
from ..schemas import (
    NAME_MAX,
    URL_MAX,
    CaptureIn,
    CaptureLookupBatchIn,
    CaptureLookupIn,
)

router = APIRouter(tags=["capture"])

# A capture is a bookmark, not an application: the user says they applied.
DEFAULT_CAPTURE_STATUS = "saved"


# (id, name, website) for one group's companies: no application rows, no notes,
# nothing that grows with usage.
CompanyRows = Sequence[tuple[int, str, str | None]]
# Normalized name -> company id, and company website domain -> company id.
CompanyIndex = tuple[dict[str, int], dict[str, int]]


async def _company_rows(session: AsyncSession, group_id: int) -> CompanyRows:
    return (
        await session.execute(
            select(Company.id, Company.name, Company.website).where(
                Company.group_id == group_id
            )
        )
    ).all()


def _company_index(rows: CompanyRows) -> CompanyIndex:
    """Both match keys for a group's companies, computed once.

    First row wins per key, which is the order the row-by-row scan this
    replaced resolved ties in. Building the index up front is what lets the
    batched lookup answer fifty names without re-normalizing every company
    fifty times.
    """
    by_name: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for company_id, existing_name, existing_website in rows:
        key = normalize_company_name(existing_name)
        if key:
            by_name.setdefault(key, company_id)
        domain = company_domain(existing_website)
        if domain:
            by_domain.setdefault(domain, company_id)
    return by_name, by_domain


def _match_company_id(
    index: CompanyIndex, name: str | None, website: str | None
) -> int | None:
    """The one matching rule, shared by capture and by both lookups.

    Normalized name wins; a website whose registrable domain matches an
    existing company's is the fallback, which is what stops a second capture
    that spells the name differently ("Acme Inc" vs "Acme") from creating a
    twin.
    """
    by_name, by_domain = index
    wanted_name = normalize_company_name(name)
    if wanted_name:
        matched = by_name.get(wanted_name)
        if matched is not None:
            return matched
    wanted_domain = company_domain(website)
    if wanted_domain:
        return by_domain.get(wanted_domain)
    return None


async def _find_company(
    session: AsyncSession, group_id: int, name: str | None, website: str | None
) -> Company | None:
    """The existing company this capture belongs to, or None.

    KNOWN AND ACCEPTED LIMIT: there is no unique constraint on
    companies(group_id, name), so two members capturing the same brand-new
    company at the same instant can still create twin rows. Sequential
    re-capture dedupes correctly and the popup disables Save while a capture is
    in flight, so the window is tiny; adding the constraint would have to
    reckon with the existing hand-created rows, which is a bigger change than
    the risk warrants.
    """
    if not normalize_company_name(name) and not company_domain(website):
        return None
    rows = await _company_rows(session, group_id)
    company_id = _match_company_id(_company_index(rows), name, website)
    if company_id is None:
        return None
    return await session.get(Company, company_id)


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


def _unresolved() -> dict:
    """The answer for a company the squad has never heard of. The extension
    draws nothing for these, so silence is the default on a job board."""
    return {"company_id": None, "company_name": None, "my_status": None, "squad": []}


async def _standings(
    session: AsyncSession, user: User, company_ids: list[int]
) -> tuple[dict[int, str], dict[int, list[dict]]]:
    """Everyone's standing on these companies, in ONE query.

    Returns (my status per company, the rest of the squad per company). Shared
    by the single and the batched lookup so the two can never disagree about
    who counts as squad: I am always split out, never listed twice.
    """
    rows = (
        await session.execute(
            select(
                Application.company_id,
                Application.user_id,
                Application.status,
                User.display_name,
            )
            .join(User, User.id == Application.user_id)
            .where(Application.company_id.in_(company_ids))
            .order_by(Application.updated_at.desc())
        )
    ).all()
    mine: dict[int, str] = {}
    squads: dict[int, list[dict]] = {company_id: [] for company_id in company_ids}
    for company_id, member_id, status, display_name in rows:
        if member_id == user.id:
            mine[company_id] = status
        else:
            squads[company_id].append({"display_name": display_name, "status": status})
    return mine, squads


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
        return _unresolved()
    mine, squads = await _standings(session, user, [company.id])
    return {
        "company_id": company.id,
        "company_name": company.name,
        "my_status": mine.get(company.id),
        "squad": squads[company.id],
    }


async def _lookup_batch(
    session: AsyncSession, user: User, group_id: int, companies: list[str]
) -> dict:
    """One job-board page's worth of lookups, in a bounded number of queries.

    Three statements at most, whatever the page holds: the membership check,
    one read of the group's companies, and one read of the applications for
    every company that matched. Nothing here runs per name, because this is
    called on every board page and every SPA navigation.

    Names are trimmed and deduplicated on the same normalized key the matcher
    uses (case-, punctuation- and legal-suffix-insensitive) BEFORE any query
    runs, so fifty rows repeating five employers cost five resolutions.

    BLANK ENTRIES: a blank or whitespace-only name, and any name with nothing
    left to match on (punctuation only), is never queried, but it still gets
    its own all-null entry in the response. The extension pairs results to the
    rows it scanned by position, so dropping an entry would shift every chip
    after it onto the wrong job. Answers pair to the caller's list one-to-one,
    in order, always.
    """
    await require_member(session, group_id, user)

    # One key per DISTINCT company asked about, plus a sample of the caller's
    # spelling to run the shared matcher against.
    keys: list[str | None] = []
    samples: dict[str, str] = {}
    for raw in companies:
        trimmed = raw.strip()
        key = normalize_company_name(trimmed)
        keys.append(key or None)
        if key:
            samples.setdefault(key, trimmed)

    resolved: dict[str, dict] = {}
    if samples:
        rows = await _company_rows(session, group_id)
        index = _company_index(rows)
        names = {company_id: name for company_id, name, _website in rows}
        # A name is never a URL here, so only the name half of the index can
        # match; the domain fallback stays available for free.
        matched: dict[str, int] = {}
        for key, sample in samples.items():
            company_id = _match_company_id(index, sample, None)
            if company_id is not None:
                matched[key] = company_id
        if matched:
            mine, squads = await _standings(session, user, sorted(set(matched.values())))
            for key, company_id in matched.items():
                resolved[key] = {
                    "company_id": company_id,
                    "company_name": names[company_id],
                    "my_status": mine.get(company_id),
                    "squad": squads[company_id],
                }

    results = []
    for raw, key in zip(companies, keys, strict=True):
        payload = resolved.get(key) if key is not None else None
        # The caller's own string comes back untouched, so a client can pair
        # answers to its rows without repeating the server's normalization.
        results.append({"query": raw, **(payload or _unresolved())})
    return {"results": results}


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


@router.post("/capture/lookup/batch")
async def capture_lookup_batch(
    body: CaptureLookupBatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Squad standing for a whole job-board results page, in one round trip
    (Phase E2).

    Same matching, same member-only rule and the same 404 for a group the
    caller does not belong to as the single lookup: a batch is a cheaper way to
    ask the same question, never a wider one.
    """
    return await _lookup_batch(session, user, body.group_id, body.companies)
