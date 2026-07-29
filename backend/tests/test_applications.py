"""Applications: PUT upsert, uniqueness, activity logging, delete, list filters."""


async def test_put_upsert_creates_then_updates(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "applied_at": "2026-07-20", "notes": "CV v3"},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    first = resp.json()
    assert first["status"] == "applied"
    assert first["applied_at"] == "2026-07-20"
    assert first["company_name"] == "TechCorp"
    assert first["user_id"] == account["user"]["id"]

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview", "applied_at": "2026-07-20"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    second = resp.json()
    assert second["id"] == first["id"]  # same row, not a new one
    assert second["status"] == "interview"

    resp = await client.get(
        f"/api/groups/{group['id']}/applications",
        params={"user_id": "me"},
        headers=account["headers"],
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "interview"


async def test_status_change_writes_activity_with_detail(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")

    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=account["headers"],
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview"},
        headers=account["headers"],
    )
    # Same status again: no extra activity row.
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview"},
        headers=account["headers"],
    )

    resp = await client.get(
        f"/api/groups/{group['id']}/activity", headers=account["headers"]
    )
    changes = [a for a in resp.json() if a["type"] == "application_status_changed"]
    assert len(changes) == 2
    # Feed is newest-first.
    assert changes[0]["detail"] == {"from": "applied", "to": "interview"}
    assert changes[1]["detail"] == {"from": None, "to": "applied"}
    assert changes[0]["company_name"] == "TechCorp"


async def test_applied_via_portal(client, register, make_group, make_company, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    portal = await make_portal(account["headers"], group["id"], name="LinkedIn")

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "applied_via_portal_id": portal["id"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["applied_via_portal_name"] == "LinkedIn"

    # A portal id that does not exist in this group is rejected.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "applied_via_portal_id": 99999},
        headers=account["headers"],
    )
    assert resp.status_code == 422


async def test_delete_application(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=account["headers"],
    )

    resp = await client.delete(
        f"/api/companies/{company['id']}/application", headers=account["headers"]
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Removing again 404s.
    resp = await client.delete(
        f"/api/companies/{company['id']}/application", headers=account["headers"]
    )
    assert resp.status_code == 404

    resp = await client.get(
        f"/api/groups/{group['id']}/activity", headers=account["headers"]
    )
    assert "application_removed" in [a["type"] for a in resp.json()]


async def test_list_filters_user_and_status(client, register, make_group, make_company):
    owner = await register(username="haris")
    friend = await register(username="ali")
    group = await make_group(owner["headers"])
    await client.post(
        "/api/groups/join",
        json={"invite_code": group["invite_code"]},
        headers=friend["headers"],
    )
    company = await make_company(owner["headers"], group["id"], name="TechCorp")
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=owner["headers"],
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "offer"},
        headers=friend["headers"],
    )

    resp = await client.get(
        f"/api/groups/{group['id']}/applications", headers=owner["headers"]
    )
    assert len(resp.json()) == 2

    resp = await client.get(
        f"/api/groups/{group['id']}/applications",
        params={"user_id": "me"},
        headers=owner["headers"],
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["username"] == "haris"

    resp = await client.get(
        f"/api/groups/{group['id']}/applications",
        params={"status": "offer"},
        headers=owner["headers"],
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["username"] == "ali"

    resp = await client.get(
        f"/api/groups/{group['id']}/applications",
        params={"status": "nonsense"},
        headers=owner["headers"],
    )
    assert resp.status_code == 422
