"""Companies: CRUD, filters (q, status, not_applied, archived), delete rules, comments."""


async def _apply(client, headers, cid, status="applied"):
    resp = await client.put(
        f"/api/companies/{cid}/application", json={"status": status}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_create_and_list(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(
        account["headers"],
        group["id"],
        name="TechCorp",
        website="https://techcorp.example",
        location="Lahore",
        tags=["fintech", "remote"],
        notes="Friend works here",
    )
    assert company["name"] == "TechCorp"
    assert company["tags"] == ["fintech", "remote"]
    assert company["created_by_username"] == "haris"
    assert company["applications"] == []
    assert company["comment_count"] == 0

    resp = await client.get(
        f"/api/groups/{group['id']}/companies", headers=account["headers"]
    )
    assert resp.status_code == 200
    listed = resp.json()
    assert [c["name"] for c in listed] == ["TechCorp"]


async def test_q_filter_matches_name_and_location(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    await make_company(account["headers"], group["id"], name="TechCorp", location="Lahore")
    await make_company(account["headers"], group["id"], name="DataWorks", location="Karachi")

    resp = await client.get(
        f"/api/groups/{group['id']}/companies", params={"q": "tech"}, headers=account["headers"]
    )
    assert [c["name"] for c in resp.json()] == ["TechCorp"]

    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"q": "karachi"},
        headers=account["headers"],
    )
    assert [c["name"] for c in resp.json()] == ["DataWorks"]


async def test_status_filters(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    applied_to = await make_company(account["headers"], group["id"], name="TechCorp")
    untouched = await make_company(account["headers"], group["id"], name="DataWorks")
    await _apply(client, account["headers"], applied_to["id"], status="applied")

    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"status": "applied"},
        headers=account["headers"],
    )
    assert [c["id"] for c in resp.json()] == [applied_to["id"]]

    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"status": "not_applied"},
        headers=account["headers"],
    )
    assert [c["id"] for c in resp.json()] == [untouched["id"]]

    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"status": "bogus"},
        headers=account["headers"],
    )
    assert resp.status_code == 422


async def test_tag_filter(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    tagged = await make_company(
        account["headers"], group["id"], name="TechCorp", tags=["remote"]
    )
    await make_company(account["headers"], group["id"], name="DataWorks", tags=["onsite"])
    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"tag": "remote"},
        headers=account["headers"],
    )
    assert [c["id"] for c in resp.json()] == [tagged["id"]]


async def test_archived_excluded_by_default(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    resp = await client.patch(
        f"/api/companies/{company['id']}", json={"archived": True}, headers=account["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["archived"] is True

    resp = await client.get(
        f"/api/groups/{group['id']}/companies", headers=account["headers"]
    )
    assert resp.json() == []

    resp = await client.get(
        f"/api/groups/{group['id']}/companies",
        params={"include_archived": "true"},
        headers=account["headers"],
    )
    assert [c["id"] for c in resp.json()] == [company["id"]]


async def test_patch_updates_fields(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(account["headers"], group["id"], name="TechCorp")
    resp = await client.patch(
        f"/api/companies/{company['id']}",
        json={"name": "TechCorp Ltd", "location": "Remote", "tags": ["fintech"]},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "TechCorp Ltd"
    assert body["location"] == "Remote"
    assert body["tags"] == ["fintech"]


async def test_delete_poster_or_owner_only(client, register, make_group, make_company):
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
    company = await make_company(poster["headers"], group["id"], name="TechCorp")

    # A member who neither posted it nor owns the group gets 403.
    resp = await client.delete(
        f"/api/companies/{company['id']}", headers=other["headers"]
    )
    assert resp.status_code == 403

    # The poster can delete their own company.
    resp = await client.delete(
        f"/api/companies/{company['id']}", headers=poster["headers"]
    )
    assert resp.status_code == 200

    # The group owner can delete someone else's post.
    company2 = await make_company(poster["headers"], group["id"], name="DataWorks")
    resp = await client.delete(
        f"/api/companies/{company2['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 200


async def test_comments_post_list_delete_author_only(
    client, register, make_group, make_company
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

    resp = await client.post(
        f"/api/companies/{company['id']}/comments",
        json={"body": "Referral possible"},
        headers=friend["headers"],
    )
    assert resp.status_code == 200
    comment = resp.json()
    assert comment["body"] == "Referral possible"
    assert comment["username"] == "ali"

    resp = await client.get(
        f"/api/companies/{company['id']}/comments", headers=owner["headers"]
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Company detail counts and embeds comments.
    resp = await client.get(f"/api/companies/{company['id']}", headers=owner["headers"])
    assert resp.json()["comment_count"] == 1
    assert resp.json()["comments"][0]["body"] == "Referral possible"

    # Not the author -> 403.
    resp = await client.delete(
        f"/api/comments/{comment['id']}", headers=owner["headers"]
    )
    assert resp.status_code == 403

    # Author deletes fine.
    resp = await client.delete(
        f"/api/comments/{comment['id']}", headers=friend["headers"]
    )
    assert resp.status_code == 200
    resp = await client.get(
        f"/api/companies/{company['id']}/comments", headers=owner["headers"]
    )
    assert resp.json() == []
