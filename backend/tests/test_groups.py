"""Groups: create, join by code, idempotent re-join, leave rules, owner-only rename."""


async def test_create_group_creator_is_owner(client, register, make_group):
    owner = await register(username="haris")
    group = await make_group(owner["headers"], name="Job Hunt 2026")
    assert group["name"] == "Job Hunt 2026"
    assert group["owner_id"] == owner["user"]["id"]
    assert group["member_count"] == 1
    assert len(group["invite_code"]) == 8
    assert all(ch in "ABCDEFGHJKMNPQRSTUVWXYZ23456789" for ch in group["invite_code"])

    detail = await client.get(f"/api/groups/{group['id']}", headers=owner["headers"])
    assert detail.status_code == 200
    members = detail.json()["members"]
    assert len(members) == 1
    assert members[0]["role"] == "owner"
    assert members[0]["user_id"] == owner["user"]["id"]


async def test_join_by_code_case_insensitive(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    resp = await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"].lower()},
        headers=friend["headers"],
    )
    assert resp.status_code == 200
    joined = resp.json()
    assert joined["id"] == group["id"]
    assert joined["member_count"] == 2


async def test_rejoin_is_idempotent(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    for _ in range(2):
        resp = await client.post(
            "/api/groups/join",
            json={"invite_code": group["invite_code"]},
            headers=friend["headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["member_count"] == 2


async def test_join_unknown_code_404(client, register):
    account = await register(username="haris")
    resp = await client.post(
        "/api/groups/join", json={"invite_code": "ZZZZZZZZ"}, headers=account["headers"]
    )
    assert resp.status_code == 404


async def test_leave_rules(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )

    # Owner cannot leave while another member remains.
    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=owner["headers"])
    assert resp.status_code == 400
    assert "Owner cannot leave" in resp.json()["detail"]

    # A plain member can leave.
    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=friend["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # The last remaining member cannot leave (no group deletion in v1).
    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=owner["headers"])
    assert resp.status_code == 400
    assert "last member" in resp.json()["detail"]

    # The group and its data are still there for the owner.
    resp = await client.get(f"/api/groups/{group['id']}", headers=owner["headers"])
    assert resp.status_code == 200
    assert resp.json()["member_count"] == 1


async def test_leave_removes_pipeline_keeps_comments(
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

    # The friend builds a personal pipeline and leaves a comment.
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

    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=friend["headers"])
    assert resp.status_code == 200

    # Their applications and portal statuses left with them.
    detail = (
        await client.get(f"/api/companies/{company['id']}", headers=owner["headers"])
    ).json()
    assert [a["username"] for a in detail["applications"]] == []
    portals = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=owner["headers"])
    ).json()
    assert portals[0]["statuses"] == []

    # Their comments (conversation history) remain.
    assert [c["username"] for c in detail["comments"]] == ["ali"]


async def test_rename_is_owner_only(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )

    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"name": "Hijacked"}, headers=friend["headers"]
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/groups/{group['id']}", json={"name": "Renamed"}, headers=owner["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


async def test_member_joined_activity_recorded(client, register, make_group):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )
    resp = await client.get(f"/api/groups/{group['id']}/activity", headers=owner["headers"])
    assert resp.status_code == 200
    types = [item["type"] for item in resp.json()]
    assert "member_joined" in types
