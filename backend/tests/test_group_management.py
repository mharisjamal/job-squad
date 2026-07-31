"""Phase G1 group management: visibility, discover, join requests, member
removal, invite regeneration, and the visibility/description migration."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import init_db, make_engine, make_sessionmaker
from app.models import Group, GroupJoinRequest, User


async def _create_group(
    client, headers, name="Job Hunt 2026", visibility="private", description=None
):
    body: dict = {"name": name, "visibility": visibility}
    if description is not None:
        body["description"] = description
    resp = await client.post("/api/groups", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Wire shape: visibility + description + owner-only pending_request_count
# ---------------------------------------------------------------------------


async def test_create_public_group_with_trimmed_description(client, register):
    owner = await register(username="haris")
    group = await _create_group(
        client, owner["headers"], visibility="public", description="  Grads hunting  "
    )
    assert group["visibility"] == "public"
    assert group["description"] == "Grads hunting"
    # The creator is the owner, so the count is present (and starts at zero).
    assert group["pending_request_count"] == 0


async def test_default_visibility_is_private(client, register, make_group):
    owner = await register(username="haris")
    group = await make_group(owner["headers"])
    assert group["visibility"] == "private"
    assert group["description"] is None


async def test_pending_request_count_is_owner_only(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    member = await register(username="sam")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(
        "/api/groups/join",
        json={"invite_code": public["invite_code"]},
        headers=member["headers"],
    )
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])

    # Owner sees the count on both detail and list.
    detail = await client.get(f"/api/groups/{public['id']}", headers=owner["headers"])
    assert detail.json()["pending_request_count"] == 1
    listing = await client.get("/api/groups", headers=owner["headers"])
    row = next(g for g in listing.json() if g["id"] == public["id"])
    assert row["pending_request_count"] == 1

    # A non-owner member never gets the key.
    detail = await client.get(f"/api/groups/{public['id']}", headers=member["headers"])
    assert "pending_request_count" not in detail.json()
    listing = await client.get("/api/groups", headers=member["headers"])
    row = next(g for g in listing.json() if g["id"] == public["id"])
    assert "pending_request_count" not in row


# ---------------------------------------------------------------------------
# PATCH visibility/description (owner only, merge semantics)
# ---------------------------------------------------------------------------


async def test_patch_visibility_and_description_owner_only(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )

    resp = await client.patch(
        f"/api/groups/{group['id']}",
        json={"visibility": "public"},
        headers=friend["headers"],
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/groups/{group['id']}",
        json={"visibility": "public", "description": "open group"},
        headers=owner["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["visibility"] == "public"
    assert body["description"] == "open group"
    # Merge: the name was not sent and must be preserved.
    assert body["name"] == group["name"]


async def test_patch_rejects_invalid_visibility(client, register, make_group):
    owner = await register(username="haris")
    group = await make_group(owner["headers"])
    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"visibility": "secret"}, headers=owner["headers"]
    )
    assert resp.status_code == 422


async def test_patch_description_length_and_empty(client, register, make_group):
    owner = await register(username="haris")
    group = await make_group(owner["headers"])
    # Over the 280-char cap -> 422.
    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"description": "x" * 281}, headers=owner["headers"]
    )
    assert resp.status_code == 422
    # Exactly 280 is accepted.
    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"description": "y" * 280}, headers=owner["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "y" * 280
    # Whitespace-only collapses to null.
    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"description": "   "}, headers=owner["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["description"] is None


# ---------------------------------------------------------------------------
# Discover
# ---------------------------------------------------------------------------


async def test_discover_lists_only_public_not_mine(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    await _create_group(
        client, owner["headers"], name="Public Grads", visibility="public",
        description="open to all",
    )
    await _create_group(client, owner["headers"], name="Secret Squad", visibility="private")
    await _create_group(client, seeker["headers"], name="My Public", visibility="public")

    resp = await client.get("/api/groups/discover", headers=seeker["headers"])
    assert resp.status_code == 200
    listed = {g["name"] for g in resp.json()}
    assert "Public Grads" in listed
    assert "Secret Squad" not in listed  # private never leaks into discover
    assert "My Public" not in listed  # already a member

    entry = next(g for g in resp.json() if g["name"] == "Public Grads")
    assert entry["request_status"] == "none"
    assert entry["member_count"] == 1
    assert entry["description"] == "open to all"
    assert "invite_code" not in entry  # discover never exposes the code


async def test_discover_search_matches_name_and_description(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    await _create_group(
        client, owner["headers"], name="Frontend Guild", visibility="public",
        description="react and typescript",
    )
    await _create_group(
        client, owner["headers"], name="Backend Guild", visibility="public",
        description="python and go",
    )

    resp = await client.get(
        "/api/groups/discover", params={"q": "typescript"}, headers=seeker["headers"]
    )
    assert {g["name"] for g in resp.json()} == {"Frontend Guild"}

    resp = await client.get(
        "/api/groups/discover", params={"q": "guild"}, headers=seeker["headers"]
    )
    assert {g["name"] for g in resp.json()} == {"Frontend Guild", "Backend Guild"}

    resp = await client.get(
        "/api/groups/discover", params={"q": "nomatch"}, headers=seeker["headers"]
    )
    assert resp.json() == []


async def test_discover_reflects_pending_request(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])

    resp = await client.get("/api/groups/discover", headers=seeker["headers"])
    entry = next(g for g in resp.json() if g["id"] == public["id"])
    assert entry["request_status"] == "pending"


# ---------------------------------------------------------------------------
# Request to join
# ---------------------------------------------------------------------------


async def test_request_public_group_ok_then_duplicate_409(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")

    resp = await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    resp = await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 409


async def test_request_private_or_unknown_group_404(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    private = await _create_group(client, owner["headers"], name="Secret", visibility="private")

    resp = await client.post(f"/api/groups/{private['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 404  # no leak: private looks unknown

    resp = await client.post("/api/groups/999999/request", headers=seeker["headers"])
    assert resp.status_code == 404


async def test_request_when_already_member_409(client, register):
    owner = await register(username="haris")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    # The owner is already a member of their own group.
    resp = await client.post(f"/api/groups/{public['id']}/request", headers=owner["headers"])
    assert resp.status_code == 409


async def test_request_records_join_requested_activity(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])

    acts = await client.get(f"/api/groups/{public['id']}/activity", headers=owner["headers"])
    types = [a["type"] for a in acts.json()]
    assert "join_requested" in types


# ---------------------------------------------------------------------------
# Owner request management: list / approve / reject
# ---------------------------------------------------------------------------


async def test_list_requests_owner_only(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    member = await register(username="sam")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(
        "/api/groups/join",
        json={"invite_code": public["invite_code"]},
        headers=member["headers"],
    )
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])

    # Owner sees the requester's identity.
    resp = await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    assert resp.status_code == 200
    reqs = resp.json()
    assert len(reqs) == 1
    assert reqs[0]["username"] == "ali"
    assert reqs[0]["display_name"] == "Ali"

    # A member who is not the owner gets 403 (not 404: they can see the group).
    resp = await client.get(f"/api/groups/{public['id']}/requests", headers=member["headers"])
    assert resp.status_code == 403

    # A non-member gets 404 (existence must not leak).
    assert (
        await client.get(f"/api/groups/{public['id']}/requests", headers=seeker["headers"])
    ).status_code == 404


async def test_approve_adds_member_then_reapprove_is_409(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]

    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/approve", headers=owner["headers"]
    )
    assert resp.status_code == 200

    detail = await client.get(f"/api/groups/{public['id']}", headers=seeker["headers"])
    assert detail.status_code == 200
    assert detail.json()["member_count"] == 2

    # FIX D: the request is now decided; re-approving it -> 409, list stays empty.
    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/approve", headers=owner["headers"]
    )
    assert resp.status_code == 409
    reqs = await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    assert reqs.json() == []

    # member_joined activity was recorded for the approval.
    acts = await client.get(f"/api/groups/{public['id']}/activity", headers=owner["headers"])
    assert "member_joined" in [a["type"] for a in acts.json()]


async def test_cannot_decide_an_already_decided_request(client, register):
    """FIX D: approve/reject act only on a pending request."""
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]

    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/reject", headers=owner["headers"]
    )
    assert resp.status_code == 200

    # Approving the already-rejected request by id is refused.
    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/approve", headers=owner["headers"]
    )
    assert resp.status_code == 409
    # Rejecting it again is likewise refused.
    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/reject", headers=owner["headers"]
    )
    assert resp.status_code == 409


async def test_reject_leaves_no_membership_and_allows_rerequest(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]

    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/reject", headers=owner["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    # Not a member, and the pending list is empty.
    assert (
        await client.get(f"/api/groups/{public['id']}", headers=seeker["headers"])
    ).status_code == 404
    reqs = await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    assert reqs.json() == []

    # A rejected user may request again (rejected != pending).
    resp = await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 200


async def test_approve_and_reject_are_owner_only(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    member = await register(username="sam")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(
        "/api/groups/join",
        json={"invite_code": public["invite_code"]},
        headers=member["headers"],
    )
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]

    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/approve", headers=member["headers"]
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/reject", headers=member["headers"]
    )
    assert resp.status_code == 403


async def test_approve_request_from_another_group_404(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    g1 = await _create_group(client, owner["headers"], name="G1", visibility="public")
    g2 = await _create_group(client, owner["headers"], name="G2", visibility="public")
    await client.post(f"/api/groups/{g1['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{g1['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]

    resp = await client.post(
        f"/api/groups/{g2['id']}/requests/{req_id}/approve", headers=owner["headers"]
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Remove member
# ---------------------------------------------------------------------------


async def test_remove_member_cleans_pipeline_keeps_comments(
    client, register, make_group, make_company, make_portal
):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )
    company = await make_company(owner["headers"], group["id"], name="TechCorp")
    portal = await make_portal(owner["headers"], group["id"], name="LinkedIn")
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=friend["headers"],
    )
    await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "active", "rating": 4},
        headers=friend["headers"],
    )
    await client.post(
        f"/api/companies/{company['id']}/comments",
        json={"body": "good place"},
        headers=friend["headers"],
    )

    # A non-owner cannot remove anyone.
    resp = await client.delete(
        f"/api/groups/{group['id']}/members/{owner['user']['id']}", headers=friend["headers"]
    )
    assert resp.status_code == 403

    # The owner removes the friend.
    resp = await client.delete(
        f"/api/groups/{group['id']}/members/{friend['user']['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 200

    # The friend is no longer a member.
    assert (
        await client.get(f"/api/groups/{group['id']}", headers=friend["headers"])
    ).status_code == 404

    # Their applications and portal statuses left with them; comments remain.
    comp = (
        await client.get(f"/api/companies/{company['id']}", headers=owner["headers"])
    ).json()
    assert [a["username"] for a in comp["applications"]] == []
    assert [c["username"] for c in comp["comments"]] == ["ali"]
    portals = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=owner["headers"])
    ).json()
    assert portals[0]["statuses"] == []


async def test_remove_member_cannot_target_self_or_unknown(client, register, make_group):
    owner = await register(username="haris")
    stranger = await register(username="sam")
    group = await make_group(owner["headers"])
    # The owner cannot remove themselves (that is the leave route's job); since
    # the caller must be the owner, this also covers "cannot remove the owner".
    resp = await client.delete(
        f"/api/groups/{group['id']}/members/{owner['user']['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 400
    # A user who is not a member of the group cannot be removed.
    resp = await client.delete(
        f"/api/groups/{group['id']}/members/{stranger['user']['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regenerate invite
# ---------------------------------------------------------------------------


async def test_regenerate_invite_invalidates_old_code(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    old_code = group["invite_code"]
    await client.post(
        "/api/groups/join", json={"invite_code": old_code}, headers=friend["headers"]
    )

    # A non-owner member cannot regenerate.
    resp = await client.post(
        f"/api/groups/{group['id']}/regenerate-invite", headers=friend["headers"]
    )
    assert resp.status_code == 403

    # The owner regenerates; the code changes.
    resp = await client.post(
        f"/api/groups/{group['id']}/regenerate-invite", headers=owner["headers"]
    )
    assert resp.status_code == 200
    new_code = resp.json()["invite_code"]
    assert new_code != old_code
    assert len(new_code) == 8

    # The old code no longer joins; the new one does.
    newcomer = await register(username="sam")
    resp = await client.post(
        "/api/groups/join", json={"invite_code": old_code}, headers=newcomer["headers"]
    )
    assert resp.status_code == 404
    resp = await client.post(
        "/api/groups/join", json={"invite_code": new_code}, headers=newcomer["headers"]
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# FIX A-support: member_removed activity names the removed user
# ---------------------------------------------------------------------------


async def test_member_removed_activity_names_the_removed_user(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )
    await client.delete(
        f"/api/groups/{group['id']}/members/{friend['user']['id']}", headers=owner["headers"]
    )

    acts = await client.get(f"/api/groups/{group['id']}/activity", headers=owner["headers"])
    removed = next(a for a in acts.json() if a["type"] == "member_removed")
    assert removed["detail"]["removed_user_id"] == friend["user"]["id"]
    assert removed["detail"]["removed_user_name"] == "Ali"


# ---------------------------------------------------------------------------
# FIX C: no ghost-pending lockout after joining by code or being removed
# ---------------------------------------------------------------------------


async def test_join_by_code_resolves_a_pending_request(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])

    # The seeker joins with the code instead of waiting for approval.
    resp = await client.post(
        "/api/groups/join",
        json={"invite_code": public["invite_code"]},
        headers=seeker["headers"],
    )
    assert resp.status_code == 200

    # Their pending request was resolved, so the owner no longer sees it.
    reqs = await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    assert reqs.json() == []


async def test_no_lockout_after_join_by_code_then_leave(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": public["invite_code"]},
        headers=seeker["headers"],
    )
    await client.post(f"/api/groups/{public['id']}/leave", headers=seeker["headers"])

    # The old request was resolved (not left pending), so a fresh request works
    # instead of colliding with a ghost pending row on the partial-unique index.
    resp = await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 200


async def test_removed_member_can_request_again(client, register):
    owner = await register(username="haris")
    seeker = await register(username="ali")
    public = await _create_group(client, owner["headers"], name="Grads", visibility="public")
    await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    req_id = (
        await client.get(f"/api/groups/{public['id']}/requests", headers=owner["headers"])
    ).json()[0]["id"]
    await client.post(
        f"/api/groups/{public['id']}/requests/{req_id}/approve", headers=owner["headers"]
    )

    resp = await client.delete(
        f"/api/groups/{public['id']}/members/{seeker['user']['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 200

    # Their join requests were cleared on removal, so they can request again.
    resp = await client.post(f"/api/groups/{public['id']}/request", headers=seeker["headers"])
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# FIX B: partial-unique index enforces one pending request per (group, user)
# ---------------------------------------------------------------------------


async def test_partial_unique_blocks_second_pending_allows_decided(tmp_path):
    """The DB-level guard (independent of the route precheck) rejects a second
    PENDING row for the same (group, user) but allows a decided row to coexist
    with a new pending one."""
    engine = make_engine(tmp_path / "pending_idx.db")
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)

    async with sessionmaker() as session:
        # Parents first (foreign_keys=ON): user, then groups, then the request.
        session.add(User(id=1, username="u1", display_name="U1"))
        await session.flush()
        session.add(Group(id=1, name="G1", invite_code="CODE0001", owner_id=1, visibility="public"))
        session.add(Group(id=2, name="G2", invite_code="CODE0002", owner_id=1, visibility="public"))
        await session.flush()
        session.add(GroupJoinRequest(group_id=1, user_id=1, status="pending"))
        await session.commit()

    # A second pending row for the same (group, user) violates the partial index.
    async with sessionmaker() as session:
        session.add(GroupJoinRequest(group_id=1, user_id=1, status="pending"))
        with pytest.raises(IntegrityError):
            await session.commit()

    # A decided (rejected) row does NOT block a fresh pending row for another group.
    async with sessionmaker() as session:
        session.add(GroupJoinRequest(group_id=2, user_id=1, status="rejected"))
        await session.commit()
    async with sessionmaker() as session:
        session.add(GroupJoinRequest(group_id=2, user_id=1, status="pending"))
        await session.commit()
    async with sessionmaker() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GroupJoinRequest)
            .where(GroupJoinRequest.group_id == 2, GroupJoinRequest.user_id == 1)
        )
        assert count == 2
    await engine.dispose()


# ---------------------------------------------------------------------------
# Migration (visibility + description)
# ---------------------------------------------------------------------------


class _FakeConnection:
    """Records init_db's statements so the Postgres branch can be asserted
    without a live database."""

    def __init__(self, log: list[str]):
        self._log = log

    async def run_sync(self, _fn):
        self._log.append("create_all")

    async def execute(self, statement):
        self._log.append(str(statement))


class _FakeEngine:
    def __init__(self, dialect_name: str):
        self.dialect = SimpleNamespace(name=dialect_name)
        self.log: list[str] = []

    def begin(self):
        log = self.log

        @asynccontextmanager
        async def _ctx():
            yield _FakeConnection(log)

        return _ctx()


async def test_postgres_migration_emits_group_visibility_statements(monkeypatch):
    async def _no_sqlite_migrate(_engine):
        pass

    monkeypatch.setattr("app.db._migrate", _no_sqlite_migrate)

    pg = _FakeEngine("postgresql")
    await init_db(pg)
    joined = "\n".join(pg.log)
    assert (
        "ALTER TABLE groups ADD COLUMN IF NOT EXISTS visibility TEXT"
        " NOT NULL DEFAULT 'private'" in joined
    )
    assert "ALTER TABLE groups ADD COLUMN IF NOT EXISTS description TEXT" in joined

    lite = _FakeEngine("sqlite")
    await init_db(lite)
    assert "IF NOT EXISTS visibility" not in "\n".join(lite.log)


async def test_sqlite_migration_adds_visibility_without_losing_rows(tmp_path):
    """A pre-G1 groups table (real rows, as the live DB has) survives: the new
    columns appear, every existing group becomes private, and rows are intact."""
    engine = make_engine(tmp_path / "pre_g1.db")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE groups ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " invite_code VARCHAR(8) NOT NULL,"
                " owner_id INTEGER NOT NULL,"
                " created_at DATETIME,"
                " UNIQUE (invite_code))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO groups (id, name, invite_code, owner_id) VALUES"
                " (1, 'Job Hunt', 'ABCD2345', 1),"
                " (2, 'Grads', 'EFGH6789', 2)"
            )
        )

    await init_db(engine)

    async with engine.begin() as conn:
        cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(groups)"))).all()}
        assert "visibility" in cols
        assert "description" in cols
        rows = (
            await conn.execute(
                text("SELECT id, name, visibility, description FROM groups ORDER BY id")
            )
        ).all()
        assert rows == [
            (1, "Job Hunt", "private", None),
            (2, "Grads", "private", None),
        ]
    await engine.dispose()


async def test_sqlite_group_migration_is_idempotent(tmp_path):
    engine = make_engine(tmp_path / "g1_twice.db")
    await init_db(engine)
    await init_db(engine)
    async with engine.begin() as conn:
        cols = [row[1] for row in (await conn.execute(text("PRAGMA table_info(groups)"))).all()]
        assert cols.count("visibility") == 1
        assert cols.count("description") == 1
    await engine.dispose()
