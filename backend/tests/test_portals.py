"""Portals: CRUD, per-member status upsert incl. none-delete, rating bounds, stats."""


async def test_create_and_list(client, register, make_group, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    portal = await make_portal(
        account["headers"], group["id"], name="LinkedIn", url="https://linkedin.com"
    )
    assert portal["name"] == "LinkedIn"
    assert portal["created_by_username"] == "haris"
    assert portal["statuses"] == []
    assert portal["stats"] == {"applications_via": 0, "interviews_via": 0, "offers_via": 0}

    resp = await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["LinkedIn"]

    resp = await client.get(
        f"/api/groups/{group['id']}/activity", headers=account["headers"]
    )
    assert "portal_added" in [a["type"] for a in resp.json()]


async def test_status_upsert_and_rating_bounds(client, register, make_group, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    portal = await make_portal(account["headers"], group["id"])

    resp = await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "signed_up", "rating": 4, "notes": "decent"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["status"] == "signed_up"
    assert row["rating"] == 4

    # Upsert to a new status updates the same row.
    resp = await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "active", "rating": 5},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    listed = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    statuses = listed[0]["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["status"] == "active"
    assert statuses[0]["rating"] == 5

    # Rating outside 1-5 is a validation error.
    for bad_rating in (0, 6):
        resp = await client.put(
            f"/api/portals/{portal['id']}/status",
            json={"status": "active", "rating": bad_rating},
            headers=account["headers"],
        )
        assert resp.status_code == 422

    # Unknown status value rejected.
    resp = await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "bogus"},
        headers=account["headers"],
    )
    assert resp.status_code == 422


async def test_status_none_deletes_row(client, register, make_group, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    portal = await make_portal(account["headers"], group["id"])
    await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "signed_up"},
        headers=account["headers"],
    )

    resp = await client.put(
        f"/api/portals/{portal['id']}/status",
        json={"status": "none"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "none"

    listed = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    assert listed[0]["statuses"] == []


async def test_effectiveness_reflects_applications(
    client, register, make_group, make_company, make_portal
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    portal = await make_portal(account["headers"], group["id"], name="LinkedIn")
    company = await make_company(account["headers"], group["id"], name="TechCorp")

    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview", "applied_via_portal_id": portal["id"]},
        headers=account["headers"],
    )

    listed = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    assert listed[0]["stats"] == {
        "applications_via": 1,
        "interviews_via": 1,
        "offers_via": 0,
    }

    # Stats endpoint mirrors the same effectiveness numbers.
    stats = (
        await client.get(f"/api/groups/{group['id']}/stats", headers=account["headers"])
    ).json()
    assert stats["per_portal"] == [
        {
            "portal_id": portal["id"],
            "name": "LinkedIn",
            "applications_via": 1,
            "interviews_via": 1,
            "offers_via": 0,
        }
    ]
    me = next(m for m in stats["per_member"] if m["username"] == "haris")
    assert me["counts"]["interview"] == 1
    assert me["counts"]["total"] == 1
    assert me["response_rate"] == 1.0
    assert stats["group"]["companies"] == 1
    assert stats["group"]["portals"] == 1


async def test_patch_and_delete_rules(client, register, make_group, make_portal):
    owner = await register(username="haris")
    poster = await register(username="ali")
    other = await register(username="sara")
    group = await make_group(owner["headers"])
    for account in (poster, other):
        await client.post(
            "/api/groups/join",
            json={"invite_code": group["invite_code"]},
            headers=account["headers"],
        )
    portal = await make_portal(poster["headers"], group["id"], name="LinkedIn")

    # Any member can patch.
    resp = await client.patch(
        f"/api/portals/{portal['id']}", json={"notes": "shared note"}, headers=other["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "shared note"

    # Delete: neither poster nor owner -> 403.
    resp = await client.delete(f"/api/portals/{portal['id']}", headers=other["headers"])
    assert resp.status_code == 403

    # Poster can delete.
    resp = await client.delete(f"/api/portals/{portal['id']}", headers=poster["headers"])
    assert resp.status_code == 200
