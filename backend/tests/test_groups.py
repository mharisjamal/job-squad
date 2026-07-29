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

    # A plain member can leave.
    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=friend["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Now the owner (sole member) can leave too.
    resp = await client.post(f"/api/groups/{group['id']}/leave", headers=owner["headers"])
    assert resp.status_code == 200

    # The departed group is gone for its ex-owner.
    resp = await client.get(f"/api/groups/{group['id']}", headers=owner["headers"])
    assert resp.status_code == 404


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
