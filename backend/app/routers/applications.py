"""Application endpoints: PUT upsert of my row, delete mine, group-wide list."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ai
from ..activity import record
from ..deps import (
    get_company_for_member,
    get_current_user,
    get_session,
    require_member,
)
from ..extraction import extract_text
from ..models import (
    APPLICATION_STATUSES,
    Application,
    Company,
    Portal,
    Resume,
    User,
    UserAISettings,
    utcnow,
)
from ..schemas import ApplicationPutIn, TailorIn, serialize_application_full
from ..security import decrypt_secret
from ..skills import find_skills

logger = logging.getLogger(__name__)

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
    provided = body.model_dump(exclude_unset=True)
    if provided.get("applied_via_portal_id") is not None:
        portal = await session.get(Portal, provided["applied_via_portal_id"])
        if portal is None or portal.group_id != company.group_id:
            raise HTTPException(status_code=422, detail="Unknown portal for this group")
    if provided.get("resume_id") is not None:
        resume_owner = await session.scalar(
            select(Resume.user_id).where(Resume.id == provided["resume_id"])
        )
        if resume_owner != user.id:
            raise HTTPException(status_code=422, detail="Unknown resume")
    saved_row: Application | None = None
    for _attempt in range(2):
        row = await session.scalar(
            select(Application).where(
                Application.company_id == cid, Application.user_id == user.id
            )
        )
        old_status = row.status if row is not None else None
        if row is None:
            row = Application(company_id=cid, user_id=user.id, status=body.status)
            session.add(row)
        # Merge semantics: only fields present in the request JSON are applied.
        # An explicit null clears the column; an omitted field is left unchanged
        # on an existing row and defaults to null on create.
        for field in (
            "status", "applied_via_portal_id", "resume_id",
            "applied_at", "follow_up_at", "url", "notes", "job_title", "jd_text",
        ):
            if field in provided:
                setattr(row, field, provided[field])
        row.updated_at = utcnow()
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent request inserted my row first: retry as an update.
            await session.rollback()
            company = await get_company_for_member(session, cid, user)
            continue
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
        saved_row = row
        break
    if saved_row is None:
        raise HTTPException(status_code=409, detail="Concurrent update, please retry")
    portal_name = None
    if saved_row.applied_via_portal_id is not None:
        portal_name = await session.scalar(
            select(Portal.name).where(Portal.id == saved_row.applied_via_portal_id)
        )
    resume_label = None
    if saved_row.resume_id is not None:
        resume_label = await session.scalar(
            select(Resume.label).where(Resume.id == saved_row.resume_id)
        )
    return serialize_application_full(saved_row, user, company.name, portal_name, resume_label)


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
    # Resume.label rides the same query (no per-row lookups); selecting the
    # column, not the entity, keeps the file bytes out of the result set.
    query = (
        select(Application, User, Company, Portal, Resume.label)
        .join(Company, Company.id == Application.company_id)
        .join(User, User.id == Application.user_id)
        .outerjoin(Portal, Portal.id == Application.applied_via_portal_id)
        .outerjoin(Resume, Resume.id == Application.resume_id)
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
        serialize_application_full(a, u, c.name, p.name if p else None, resume_label)
        for a, u, c, p, resume_label in rows
    ]


async def _ensure_extracted_text(session: AsyncSession, resume: Resume) -> str:
    """Return the resume's plain text, extracting and persisting it lazily.

    extracted_text is NULL only on rows uploaded before extraction existed; an
    empty string means extraction already ran and found nothing (a scanned or
    image-only PDF), so it is never re-attempted.
    """
    if resume.extracted_text is not None:
        return resume.extracted_text
    data = await session.scalar(select(Resume.data).where(Resume.id == resume.id))
    text = extract_text(resume.kind, bytes(data or b""))
    resume.extracted_text = text
    await session.commit()
    return text


@router.get("/applications/{app_id}/match")
async def match_application(
    app_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Deterministic JD-to-resume skills report for MY application.

    Not-mine or cross-group is a 404 (no existence leak). The report is a raw,
    honest present/missing signal: coverage is present/total, missing items are
    opportunities to consider, and no "score" beyond that is invented. The
    frontend frames the numbers; this endpoint only reports the facts.
    """
    row = await session.get(Application, app_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    # Membership check keeps the scoping rule explicit (my row is always in a
    # group I belong to, but this is defense in depth and 404s if it is not).
    await get_company_for_member(session, row.company_id, user)

    jd = (row.jd_text or "").strip()
    resume = await session.get(Resume, row.resume_id) if row.resume_id else None
    if not jd and resume is None:
        raise HTTPException(
            status_code=409,
            detail="Add a job description and attach a resume to see the match.",
        )
    if not jd:
        raise HTTPException(
            status_code=409, detail="Add a job description to see the match."
        )
    if resume is None:
        raise HTTPException(
            status_code=409, detail="Attach a resume to see the match."
        )

    resume_text = await _ensure_extracted_text(session, resume)
    # An image-only/scanned PDF extracts to nothing. Flag it so the frontend
    # shows a "could not read this resume's text" notice instead of a
    # misleading 0% report where every JD skill looks like a gap.
    resume_text_available = bool(resume_text.strip())
    jd_skills_ordered = find_skills(jd)
    resume_skill_set = set(find_skills(resume_text))
    jd_skills = [
        {"skill": skill, "present": skill in resume_skill_set}
        for skill in jd_skills_ordered
    ]
    present_count = sum(1 for entry in jd_skills if entry["present"])
    total = len(jd_skills)
    coverage = round(100 * present_count / total) if total else 0
    missing = [entry["skill"] for entry in jd_skills if not entry["present"]]
    return {
        "jd_skills": jd_skills,
        "coverage": coverage,
        "missing": missing,
        "resume_id": resume.id,
        "resume_label": resume.label,
        "resume_text_available": resume_text_available,
    }


async def _resume_source_for_tailor(session: AsyncSession, resume: Resume) -> str:
    """The text handed to the model: full LaTeX for a .tex resume (or a compiled
    PDF that retained its source), otherwise the extracted plain text."""
    if resume.kind == "tex" or resume.source_tex:
        if resume.source_tex:
            return resume.source_tex
        data = await session.scalar(select(Resume.data).where(Resume.id == resume.id))
        return bytes(data or b"").decode("utf-8", errors="replace")
    return await _ensure_extracted_text(session, resume)


async def _tailor_via_ai(kind: str, resume_text: str, jd_text: str, **client_kwargs) -> dict:
    """Call the AI once, parse, retry once with a format nudge, else 502.

    The tex path parses SENTINEL-delimited plain text (the model returns raw
    LaTeX, never JSON-escaped - mid-tier models fail that escaping most of the
    time). The advice path stays on JSON (short strings, which they get right).
    """
    if kind == "tex":
        parse = ai.parse_tailored_tex
        build_retry = ai.tex_retry_messages
        fail_detail = "The AI did not return the tailored resume in the expected format. Try again."
    else:
        parse = ai.parse_tailor_json
        build_retry = ai.json_retry_messages
        fail_detail = "The AI provider did not return usable JSON. Try again."

    messages = ai.build_tailor_messages(kind, resume_text, jd_text)
    try:
        reply = await ai.chat_completion(messages=messages, **client_kwargs)
    except ai.AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    parsed = parse(reply)
    if parsed is None:
        try:
            reply = await ai.chat_completion(messages=build_retry(messages, reply), **client_kwargs)
        except ai.AIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        parsed = parse(reply)
    if parsed is None:
        raise HTTPException(status_code=502, detail=fail_detail)
    return parsed


@router.post("/applications/{app_id}/tailor")
async def tailor_application(
    app_id: int,
    body: TailorIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """AI-tailor MY resume to this application's job description (BYOK).

    Not-mine or cross-group is a 404. Missing prerequisites are 409s that say
    exactly which one is missing (job description, resume, or AI settings). The
    system prompt hard-constrains the model against inventing facts.
    """
    row = await session.get(Application, app_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found")
    await get_company_for_member(session, row.company_id, user)

    resume = await session.get(Resume, body.resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=409, detail="Choose one of your resumes to tailor.")
    jd = (row.jd_text or "").strip()
    if not jd:
        raise HTTPException(
            status_code=409, detail="Add a job description to this application first."
        )
    settings = await session.get(UserAISettings, user.id)
    if settings is None or not settings.key_encrypted:
        raise HTTPException(
            status_code=409, detail="Configure your AI provider and key in Settings first."
        )
    api_key = decrypt_secret(settings.key_encrypted, request.app.state.settings.secret)
    if not api_key:
        raise HTTPException(
            status_code=409, detail="Your stored AI key could not be read. Re-enter it in Settings."
        )

    resume_text = await _resume_source_for_tailor(session, resume)
    if not resume_text.strip():
        raise HTTPException(
            status_code=409,
            detail="This resume has no readable text to tailor. Upload a text-based file.",
        )

    client_kwargs = {
        "base_url": settings.base_url or "",
        "api_key": api_key,
        "model": settings.model or "",
    }
    parsed = await _tailor_via_ai(resume.kind, resume_text, jd, **client_kwargs)

    if resume.kind == "tex":
        tailored = parsed.get("tailored_tex")
        if not isinstance(tailored, str) or not tailored.strip():
            raise HTTPException(
                status_code=502, detail="The AI did not return tailored LaTeX. Try again."
            )
        changes = [str(c) for c in parsed.get("changes", []) if isinstance(c, str | int | float)]
        # No skill backstop on the tex branch: tailored_tex is shown to the user
        # as a full before/after diff they review and accept, so a fabricated
        # skill would be visible and rejectable, not silently applied.
        return {"kind": "tex", "tailored_tex": tailored, "changes": changes}

    # ADVICE branch (pdf/docx): the model returns suggested rewrites. A mid-tier
    # model sometimes writes a JD skill the resume LACKS into a "suggested"
    # rewrite as if the candidate had it - the highest-harm output (it could get
    # the user caught lying). Deterministic backstop that does NOT trust the
    # model to obey the prompt.
    resume_skills = set(find_skills(resume_text))
    jd_skills = set(find_skills(jd))
    raw_suggestions = _clean_suggestions(parsed.get("suggestions"))
    keywords = [
        str(k) for k in (parsed.get("keywords_to_add") or []) if isinstance(k, str | int | float)
    ]
    suggestions, keywords = _apply_skill_backstop(
        raw_suggestions, keywords, resume_skills, jd_skills
    )
    return {"kind": "advice", "suggestions": suggestions, "keywords_to_add": keywords}


def _apply_skill_backstop(
    suggestions: list[dict],
    keywords: list[str],
    resume_skills: set[str],
    jd_skills: set[str],
) -> tuple[list[dict], list[str]]:
    """Drop any suggestion whose rewrite introduces a skill the resume lacks.

    Conservative: a legitimate rephrase reuses only existing skills (added is
    empty) and is kept verbatim. A dropped skill that the JD actually wants is
    re-surfaced honestly in keywords_to_add ("add X if true"), never as a
    fait-accompli rewrite. keywords_to_add is then trimmed to genuine gaps.
    """
    kept: list[dict] = []
    dropped_skills: set[str] = set()
    for suggestion in suggestions:
        added = set(find_skills(suggestion["suggested"])) - resume_skills
        if added:
            dropped_skills |= added
            continue
        kept.append(suggestion)
    filtered = len(suggestions) - len(kept)
    if filtered:
        logger.debug("tailor advice: dropped %d suggestion(s) that added unlisted skills", filtered)

    result_keywords = list(keywords)
    # A dropped, JD-wanted skill is still shown as an honest gap.
    for skill in dropped_skills:
        if skill in jd_skills and skill not in result_keywords:
            result_keywords.append(skill)
    # Genuine gaps only: drop any keyword the resume already covers (via the same
    # alias-aware matcher), so covered skills never clutter the gap list.
    result_keywords = [
        keyword
        for keyword in result_keywords
        if not (set(find_skills(keyword)) & resume_skills)
    ]
    return kept, result_keywords


def _clean_suggestions(raw) -> list[dict]:
    """Keep only well-formed suggestion objects, coercing fields to strings."""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "section": str(item.get("section", "")),
                "original": str(item.get("original", "")),
                "suggested": str(item.get("suggested", "")),
                "reason": str(item.get("reason", "")),
            }
        )
    return out
