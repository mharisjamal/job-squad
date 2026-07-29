"""CSV exports: status 200, text/csv, exact headers, seeded rows, query-param auth."""

APPLICATIONS_HEADER = (
    "company,member,status,applied_at,follow_up_at,applied_via,posting_url,notes,updated_at"
)
COMPANIES_HEADER = "name,website,careers_url,location,tags,notes,posted_by,created_at,archived"
PORTALS_HEADER = "name,url,notes,posted_by,applications_via,created_at"


async def _seed(client, register, make_group, make_company, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    portal = await make_portal(account["headers"], group["id"], name="LinkedIn")
    company = await make_company(
        account["headers"], group["id"], name="TechCorp", tags=["fintech", "remote"]
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={
            "status": "applied",
            "applied_via_portal_id": portal["id"],
            "applied_at": "2026-07-20",
        },
        headers=account["headers"],
    )
    return account, group


async def test_applications_csv(client, register, make_group, make_company, make_portal):
    account, group = await _seed(client, register, make_group, make_company, make_portal)
    resp = await client.get(
        f"/api/groups/{group['id']}/export/applications.csv", headers=account["headers"]
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0].strip() == APPLICATIONS_HEADER
    assert any("TechCorp" in line and "applied" in line for line in lines[1:])
    assert any("LinkedIn" in line for line in lines[1:])


async def test_applications_csv_access_token_query_param(
    client, register, make_group, make_company, make_portal
):
    account, group = await _seed(client, register, make_group, make_company, make_portal)
    # No Authorization header at all: token rides the query string.
    resp = await client.get(
        f"/api/groups/{group['id']}/export/applications.csv",
        params={"access_token": account["token"], "user_id": "me"},
    )
    assert resp.status_code == 200
    assert "TechCorp" in resp.text

    # And without any token it is a 401.
    resp = await client.get(f"/api/groups/{group['id']}/export/applications.csv")
    assert resp.status_code == 401


async def test_companies_csv(client, register, make_group, make_company, make_portal):
    account, group = await _seed(client, register, make_group, make_company, make_portal)
    resp = await client.get(
        f"/api/groups/{group['id']}/export/companies.csv", headers=account["headers"]
    )
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert lines[0].strip() == COMPANIES_HEADER
    assert any("TechCorp" in line and "fintech;remote" in line for line in lines[1:])


async def test_csv_formula_injection_neutralized(client, register, make_group, make_company):
    import csv
    import io

    account = await register(username="haris")
    group = await make_group(account["headers"])
    hostile_name = "=cmd|' /C calc'!A0"
    await make_company(account["headers"], group["id"], name=hostile_name)

    resp = await client.get(
        f"/api/groups/{group['id']}/export/companies.csv", headers=account["headers"]
    )
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[1][0] == "'" + hostile_name  # quote prefix defuses the formula


async def test_portals_csv(client, register, make_group, make_company, make_portal):
    account, group = await _seed(client, register, make_group, make_company, make_portal)
    resp = await client.get(
        f"/api/groups/{group['id']}/export/portals.csv", headers=account["headers"]
    )
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    assert lines[0].strip() == PORTALS_HEADER
    assert any("LinkedIn" in line and ",1," in line for line in lines[1:])
