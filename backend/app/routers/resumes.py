"""Resume vault: upload, list, rename, delete, file serving, outcome stats.

Visibility model (mirrors the shared-notes philosophy): a resume is private to
its owner until it is attached to an application; then anyone sharing a group
where it is attached may view the FILE. List/rename/delete/stats stay
owner-only. The ?access_token= query fallback is NOT honored here: in-app
viewing fetches with the Bearer header into a blob URL.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_current_user, get_session
from ..models import Application, Company, GroupMember, Resume, User
from ..schemas import RESUME_LABEL_MAX, ResumePatchIn, serialize_resume

router = APIRouter(tags=["resumes"])

MAX_RESUME_BYTES = 2 * 1024 * 1024  # 2 MB per file
MAX_RESUMES_PER_USER = 10
INTERVIEW_STATUSES = ("assessment", "interview")

# Content type is derived from the detected kind, never trusted from the client.
KIND_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "tex": "text/x-tex",
}


def detect_kind(content: bytes, filename: str | None) -> str | None:
    """Kind by magic bytes (%PDF, PK zip for docx); .tex by extension only,
    because LaTeX source is plain text with no magic number."""
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return "docx"
    if (filename or "").lower().endswith(".tex"):
        return "tex"
    return None


def clean_filename(raw: str | None) -> str | None:
    """Basename only (browsers may send paths), control chars out, length capped."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32).strip()
    return name[:255] or None


def inline_disposition(filename: str) -> str:
    """Content-Disposition: inline with a safe ASCII fallback filename plus an
    RFC 5987 filename* when the real name is not pure ASCII. Quotes, backslashes
    and control characters can never reach the header."""
    cleaned = "".join(ch for ch in filename if ch not in '"\\' and ord(ch) >= 32)
    fallback = cleaned.encode("ascii", "ignore").decode() or "resume"
    if fallback == cleaned:
        return f'inline; filename="{fallback}"'
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{quote(cleaned)}"


async def get_own_resume(session: AsyncSession, resume_id: int, user: User) -> Resume:
    """Owner-only lookup; someone else's resume 404s (no existence leak)."""
    resume = await session.get(Resume, resume_id)
    if resume is None or resume.user_id != user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


async def attached_counts(session: AsyncSession, resume_ids: list[int]) -> dict[int, int]:
    counts = dict.fromkeys(resume_ids, 0)
    if not resume_ids:
        return counts
    rows = (
        await session.execute(
            select(Application.resume_id, func.count())
            .where(Application.resume_id.in_(resume_ids))
            .group_by(Application.resume_id)
        )
    ).all()
    for resume_id, count in rows:
        counts[resume_id] = int(count)
    return counts


async def _my_resumes(session: AsyncSession, user: User) -> list[Resume]:
    return list(
        (
            await session.scalars(
                select(Resume)
                .where(Resume.user_id == user.id)
                .order_by(Resume.created_at.desc(), Resume.id.desc())
            )
        ).all()
    )


async def _visible_via_shared_group(
    session: AsyncSession, resume_id: int, user_id: int
) -> bool:
    """True when the resume is attached to an application in a group the
    requester belongs to. Unattached resumes never match."""
    row = await session.scalar(
        select(Application.id)
        .join(Company, Company.id == Application.company_id)
        .join(GroupMember, GroupMember.group_id == Company.group_id)
        .where(Application.resume_id == resume_id, GroupMember.user_id == user_id)
        .limit(1)
    )
    return row is not None


@router.post("/resumes")
async def upload_resume(
    label: str = Form(max_length=200),
    file: UploadFile = File(),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    label = label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="label must not be blank")
    if len(label) > RESUME_LABEL_MAX:
        raise HTTPException(
            status_code=422, detail=f"label must be {RESUME_LABEL_MAX} characters or fewer"
        )
    # Read at most one byte past the cap: enough to detect oversize without
    # ever buffering an arbitrarily large file.
    content = await file.read(MAX_RESUME_BYTES + 1)
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume file is larger than 2 MB")
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    kind = detect_kind(content, file.filename)
    if kind is None:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Upload a PDF, DOCX, or .tex file.",
        )
    resume = Resume(
        user_id=user.id,
        label=label,
        filename=clean_filename(file.filename),
        kind=kind,
        content_type=KIND_CONTENT_TYPES[kind],
        size_bytes=len(content),
        data=content,
    )
    session.add(resume)
    await session.flush()
    # Enforce the per-user cap AFTER the insert is visible within this
    # transaction, so two concurrent uploads cannot both read a stale count of
    # 9 and each slip past the check (the old count-then-insert TOCTOU). The
    # newest row over the limit is the one rolled back.
    total = await session.scalar(
        select(func.count()).select_from(Resume).where(Resume.user_id == user.id)
    )
    if int(total or 0) > MAX_RESUMES_PER_USER:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Resume limit reached ({MAX_RESUMES_PER_USER}). Delete one first.",
        )
    await session.commit()
    return serialize_resume(resume, 0)


@router.get("/resumes")
async def list_resumes(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    resumes = await _my_resumes(session, user)
    counts = await attached_counts(session, [r.id for r in resumes])
    return [serialize_resume(resume, counts[resume.id]) for resume in resumes]


# Declared before the /{resume_id} routes so "stats" is never parsed as an id.
@router.get("/resumes/stats")
async def resume_stats(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    resumes = await _my_resumes(session, user)
    resume_ids = [r.id for r in resumes]
    by_resume: dict[int, dict[str, int]] = {rid: {} for rid in resume_ids}
    if resume_ids:
        rows = (
            await session.execute(
                select(Application.resume_id, Application.status, func.count())
                .where(Application.resume_id.in_(resume_ids))
                .group_by(Application.resume_id, Application.status)
            )
        ).all()
        for resume_id, status, count in rows:
            by_resume[resume_id][status] = int(count)
    payload = []
    for resume in resumes:
        counts = by_resume[resume.id]
        payload.append(
            {
                "resume_id": resume.id,
                "label": resume.label,
                "applications": sum(counts.values()),
                "interviews": sum(counts.get(s, 0) for s in INTERVIEW_STATUSES),
                "offers": counts.get("offer", 0),
                "rejected": counts.get("rejected", 0),
                "ghosted": counts.get("ghosted", 0),
            }
        )
    return payload


@router.patch("/resumes/{resume_id}")
async def rename_resume(
    resume_id: int,
    body: ResumePatchIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    resume = await get_own_resume(session, resume_id, user)
    resume.label = body.label
    await session.commit()
    counts = await attached_counts(session, [resume.id])
    return serialize_resume(resume, counts[resume.id])


@router.delete("/resumes/{resume_id}")
async def delete_resume(
    resume_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    resume = await get_own_resume(session, resume_id, user)
    # The FK (ON DELETE SET NULL) detaches it from any applications.
    await session.delete(resume)
    await session.commit()
    return {"ok": True}


@router.get("/resumes/{resume_id}/file")
async def resume_file(
    resume_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    resume = await session.get(Resume, resume_id)
    if resume is None or (
        resume.user_id != user.id
        and not await _visible_via_shared_group(session, resume_id, user.id)
    ):
        raise HTTPException(status_code=404, detail="Resume not found")
    data = await session.scalar(select(Resume.data).where(Resume.id == resume_id))
    filename = resume.filename or f"resume-{resume.id}.{resume.kind}"
    return Response(
        content=bytes(data or b""),
        media_type=resume.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": inline_disposition(filename),
            "X-Content-Type-Options": "nosniff",
        },
    )
