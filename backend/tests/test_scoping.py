"""CRITICAL scoping: resources in a group you are not a member of return 404."""

import pytest


@pytest.fixture
async def two_worlds(client, register, make_group, make_company, make_portal):
    """User A with group A (company/portal/application) and outsider B with group B."""
    alice = await register(username="alice")
    group_a = await make_group(alice["headers"], name="Group A")
    company_a = await make_company(alice["headers"], group_a["id"], name="SecretCorp")
    portal_a = await make_portal(alice["headers"], group_a["id"], name="HiddenPortal")
    await client.put(
        f"/api/companies/{company_a['id']}/application",
        json={"status": "applied"},
        headers=alice["headers"],
    )
    bob = await register(username="bob")
    await make_group(bob["headers"], name="Group B")
    return {
        "alice": alice,
        "bob": bob,
        "group_a": group_a,
        "company_a": company_a,
        "portal_a": portal_a,
    }


async def test_non_member_group_detail_404(client, two_worlds):
    resp = await client.get(
        f"/api/groups/{two_worlds['group_a']['id']}", headers=two_worlds["bob"]["headers"]
    )
    assert resp.status_code == 404


async def test_non_member_company_endpoints_404(client, two_worlds):
    bob = two_worlds["bob"]["headers"]
    gid = two_worlds["group_a"]["id"]
    cid = two_worlds["company_a"]["id"]

    assert (await client.get(f"/api/groups/{gid}/companies", headers=bob)).status_code == 404
    assert (await client.get(f"/api/companies/{cid}", headers=bob)).status_code == 404
    assert (
        await client.patch(f"/api/companies/{cid}", json={"name": "Hacked"}, headers=bob)
    ).status_code == 404
    assert (await client.delete(f"/api/companies/{cid}", headers=bob)).status_code == 404
    assert (
        await client.post(
            f"/api/groups/{gid}/companies", json={"name": "Sneaky"}, headers=bob
        )
    ).status_code == 404


async def test_non_member_application_put_404(client, two_worlds):
    resp = await client.put(
        f"/api/companies/{two_worlds['company_a']['id']}/application",
        json={"status": "applied"},
        headers=two_worlds["bob"]["headers"],
    )
    assert resp.status_code == 404
    resp = await client.get(
        f"/api/groups/{two_worlds['group_a']['id']}/applications",
        headers=two_worlds["bob"]["headers"],
    )
    assert resp.status_code == 404


async def test_non_member_portal_endpoints_404(client, two_worlds):
    bob = two_worlds["bob"]["headers"]
    gid = two_worlds["group_a"]["id"]
    pid = two_worlds["portal_a"]["id"]

    assert (await client.get(f"/api/groups/{gid}/portals", headers=bob)).status_code == 404
    assert (
        await client.put(
            f"/api/portals/{pid}/status", json={"status": "active"}, headers=bob
        )
    ).status_code == 404
    assert (
        await client.patch(f"/api/portals/{pid}", json={"name": "Hacked"}, headers=bob)
    ).status_code == 404
    assert (await client.delete(f"/api/portals/{pid}", headers=bob)).status_code == 404


async def test_non_member_comments_404(client, two_worlds):
    bob = two_worlds["bob"]["headers"]
    cid = two_worlds["company_a"]["id"]
    assert (
        await client.get(f"/api/companies/{cid}/comments", headers=bob)
    ).status_code == 404
    assert (
        await client.post(f"/api/companies/{cid}/comments", json={"body": "hi"}, headers=bob)
    ).status_code == 404


async def test_non_member_activity_stats_export_404(client, two_worlds):
    bob = two_worlds["bob"]["headers"]
    gid = two_worlds["group_a"]["id"]

    assert (await client.get(f"/api/groups/{gid}/activity", headers=bob)).status_code == 404
    assert (await client.get(f"/api/groups/{gid}/stats", headers=bob)).status_code == 404
    for name in ("applications", "companies", "portals"):
        resp = await client.get(f"/api/groups/{gid}/export/{name}.csv", headers=bob)
        assert resp.status_code == 404


async def test_member_still_sees_everything(client, two_worlds):
    """Sanity: the scoping guards do not lock out actual members."""
    alice = two_worlds["alice"]["headers"]
    gid = two_worlds["group_a"]["id"]
    cid = two_worlds["company_a"]["id"]
    assert (await client.get(f"/api/groups/{gid}", headers=alice)).status_code == 200
    assert (await client.get(f"/api/companies/{cid}", headers=alice)).status_code == 200
    assert (await client.get(f"/api/groups/{gid}/stats", headers=alice)).status_code == 200
