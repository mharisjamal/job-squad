"""Comment endpoints: list/post on a company, author-only delete."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..activity import record
from ..deps import get_company_for_member, get_current_user, get_session
from ..models import Comment, Company, GroupMember, User
from ..schemas import CommentIn, serialize_comment

router = APIRouter(tags=["comments"])


@router.get("/companies/{cid}/comments")
async def list_comments(
    cid: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await get_company_for_member(session, cid, user)
    rows = (
        await session.execute(
            select(Comment, User)
            .join(User, User.id == Comment.user_id)
            .where(Comment.company_id == cid)
            .order_by(Comment.created_at)
        )
    ).all()
    return [serialize_comment(c, u) for c, u in rows]


@router.post("/companies/{cid}/comments")
async def post_comment(
    cid: int,
    body: CommentIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    company = await get_company_for_member(session, cid, user)
    comment = Comment(company_id=cid, user_id=user.id, body=body.body)
    session.add(comment)
    await session.flush()
    await record(
        session,
        request.app.state.broker,
        group_id=company.group_id,
        user=user,
        type_="comment_added",
        company=company,
    )
    await session.commit()
    return serialize_comment(comment, user)


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    company = await session.get(Company, comment.company_id)
    member = None
    if company is not None:
        member = await session.scalar(
            select(GroupMember).where(
                GroupMember.group_id == company.group_id, GroupMember.user_id == user.id
            )
        )
    if company is None or member is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the author can delete a comment")
    await session.delete(comment)
    await session.commit()
    return {"ok": True}
