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

    # Merge semantics: a status-only PUT updates status and preserves the rest.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    second = resp.json()
    assert second["id"] == first["id"]  # same row, not a new one
    assert second["status"] == "interview"
    assert second["applied_at"] == "2026-07-20"
    assert second["notes"] == "CV v3"

    resp = await client.get(
        f"/api/groups/{group['id']}/applications",
        params={"user_id": "me"},
        headers=account["headers"],
    )
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "interview"


async def test_create_with_status_only_leaves_fields_null(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "saved"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["status"] == "saved"
    for field in ("applied_via_portal_id", "applied_via_portal_name", "applied_at",
                  "follow_up_at", "url", "notes"):
        assert row[field] is None


async def test_status_only_put_preserves_all_other_fields(
    client, register, make_group, make_company, make_portal
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    portal = await make_portal(account["headers"], group["id"], name="LinkedIn")

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={
            "status": "applied",
            "applied_via_portal_id": portal["id"],
            "applied_at": "2026-07-20",
            "follow_up_at": "2026-08-01",
            "url": "https://techcorp.example/jobs/1",
            "notes": "CV v3",
        },
        headers=account["headers"],
    )
    assert resp.status_code == 200

    # The kanban drag / inline select sends only the status.
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["status"] == "interview"
    assert row["applied_via_portal_id"] == portal["id"]
    assert row["applied_via_portal_name"] == "LinkedIn"
    assert row["applied_at"] == "2026-07-20"
    assert row["follow_up_at"] == "2026-08-01"
    assert row["url"] == "https://techcorp.example/jobs/1"
    assert row["notes"] == "CV v3"


async def test_explicit_null_clears_only_that_field(
    client, register, make_group, make_company, make_portal
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    portal = await make_portal(account["headers"], group["id"], name="LinkedIn")

    await client.put(
        f"/api/companies/{company['id']}/application",
        json={
            "status": "applied",
            "applied_via_portal_id": portal["id"],
            "url": "https://techcorp.example/jobs/1",
            "notes": "CV v3",
        },
        headers=account["headers"],
    )

    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "interview", "notes": None},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["notes"] is None
    assert row["url"] == "https://techcorp.example/jobs/1"
    assert row["applied_via_portal_id"] == portal["id"]
    assert row["applied_via_portal_name"] == "LinkedIn"


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


# ---------------------------------------------------------------------------
# job_title (Phase E1 addendum): the role, not just the company
# ---------------------------------------------------------------------------


async def test_job_title_set_preserved_and_cleared(
    client, register, make_group, make_company
):
    """Merge semantics on job_title: omitted leaves it, explicit null clears."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    url = f"/api/companies/{company['id']}/application"

    resp = await client.put(
        url,
        json={"status": "applied", "job_title": "  Senior Backend Engineer  "},
        headers=account["headers"],
    )
    assert resp.status_code == 200, resp.text
    # Stored trimmed.
    assert resp.json()["job_title"] == "Senior Backend Engineer"

    # Omitted: unchanged.
    resp = await client.put(url, json={"status": "interview"}, headers=account["headers"])
    assert resp.json()["job_title"] == "Senior Backend Engineer"

    # Explicit null: cleared.
    resp = await client.put(
        url, json={"status": "interview", "job_title": None}, headers=account["headers"]
    )
    assert resp.json()["job_title"] is None


async def test_blank_job_title_becomes_null(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "job_title": "   "},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["job_title"] is None


async def test_job_title_over_200_is_422(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    url = f"/api/companies/{company['id']}/application"
    resp = await client.put(
        url, json={"status": "applied", "job_title": "x" * 201}, headers=account["headers"]
    )
    assert resp.status_code == 422
    resp = await client.put(
        url, json={"status": "applied", "job_title": "x" * 200}, headers=account["headers"]
    )
    assert resp.status_code == 200, resp.text


async def test_new_application_has_a_null_job_title(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    resp = await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "saved"},
        headers=account["headers"],
    )
    assert resp.json()["job_title"] is None


async def test_job_title_rides_both_application_shapes(
    client, register, make_group, make_company
):
    """ApplicationFull (application list, company detail) and ApplicationBrief
    (the company list's squad row) both carry the role."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied", "job_title": "Data Engineer"},
        headers=account["headers"],
    )

    rows = (
        await client.get(
            f"/api/groups/{group['id']}/applications", headers=account["headers"]
        )
    ).json()
    assert rows[0]["job_title"] == "Data Engineer"

    detail = (
        await client.get(f"/api/companies/{company['id']}", headers=account["headers"])
    ).json()
    assert detail["applications"][0]["job_title"] == "Data Engineer"

    listing = (
        await client.get(
            f"/api/groups/{group['id']}/companies", headers=account["headers"]
        )
    ).json()
    brief = listing[0]["applications"][0]
    assert brief["job_title"] == "Data Engineer"
    # The brief stays a brief: it gained one column, not the whole row.
    assert "jd_text" not in brief


async def test_list_reads_do_not_scale_their_query_count_with_rows(
    client, register, make_group, make_company, asgi_app
):
    """job_title is a plain column on the row, so it rides the existing joins.

    Guard against a future N+1: the company list and the application list must
    issue the same number of SQL statements for four companies as for one.
    """
    from sqlalchemy import event

    account = await register(username="haris")
    group = await make_group(account["headers"])
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    sync_engine = asgi_app.state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        counts = []
        for index in range(4):
            company = await make_company(
                account["headers"], group["id"], name=f"Company {index}"
            )
            await client.put(
                f"/api/companies/{company['id']}/application",
                json={"status": "applied", "job_title": f"Engineer {index}"},
                headers=account["headers"],
            )
            if index in (0, 3):
                statements.clear()
                await client.get(
                    f"/api/groups/{group['id']}/companies", headers=account["headers"]
                )
                await client.get(
                    f"/api/groups/{group['id']}/applications", headers=account["headers"]
                )
                counts.append(len(statements))
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    assert counts[0] == counts[1], statements
