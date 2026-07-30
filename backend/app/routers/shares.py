"""The single unauthenticated route: serve a shared PDF resume by token.

This router is mounted at the app root (NOT under /api) and carries no auth
dependency, so anyone with the 32-hex token can view the PDF. It leaks nothing
else: an unknown or revoked token 404s, only PDF bytes are ever returned, and
no owner, label, or other resume served here.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session
from ..models import Resume, ResumeShare

router = APIRouter(include_in_schema=False)


@router.get("/r/{token}")
async def serve_shared_resume(
    token: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    share = await session.scalar(
        select(ResumeShare).where(
            ResumeShare.token == token, ResumeShare.revoked.is_(False)
        )
    )
    if share is None:
        raise HTTPException(status_code=404, detail="Not found")
    resume = await session.get(Resume, share.resume_id)
    if resume is None or resume.kind != "pdf":
        raise HTTPException(status_code=404, detail="Not found")
    data = await session.scalar(select(Resume.data).where(Resume.id == resume.id))
    return Response(
        content=bytes(data or b""),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline; filename=\"resume.pdf\"",
            "X-Content-Type-Options": "nosniff",
        },
    )
