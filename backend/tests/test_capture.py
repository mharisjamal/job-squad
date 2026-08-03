"""Browser-extension capture (Phase E1): POST /api/capture and
GET /api/capture/lookup - dedupe, portal mapping, merge semantics, scoping."""

import pytest

from app.capture import (
    company_domain,
    normalize_company_name,
    portal_name_for_domain,
    registrable_domain,
)
from app.schemas import JD_TEXT_MAX

LINKEDIN_POSTING = "https://www.linkedin.com/jobs/view/4012345678/"


async def _capture(client, headers, **body):
    return await client.post("/api/capture", json=body, headers=headers)


async def _join(client, headers, group):
    resp = await client.post(
        "/api/groups/join", json={"invite_code": group["invite_code"]}, headers=headers
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# The matching rules (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("TechCorp", "techcorp"),
        ("  TechCorp  ", "techcorp"),
        ("TECHCORP", "techcorp"),
        ("TechCorp, Inc.", "techcorp"),
        ("TechCorp Pvt Ltd", "techcorp"),
        ("TechCorp GmbH", "techcorp"),
        ("Tech   Labs", "tech labs"),
        ("Tech-Labs", "tech labs"),
        # A trailing legal-form word is a suffix wherever it appears, so
        # "Tech Corp" and "Tech" are deliberately one company.
        ("Tech Corp", "tech"),
        # Only trailing words are stripped, and never the last one.
        ("Corp Bank", "corp bank"),
        ("Ltd", "ltd"),
        ("", ""),
    ],
)
def test_normalize_company_name(name, expected):
    assert normalize_company_name(name) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://www.techcorp.com/careers", "techcorp.com"),
        ("techcorp.com", "techcorp.com"),
        ("http://jobs.eu.techcorp.com/x?y=1", "techcorp.com"),
        ("https://careers.techcorp.co.uk/", "techcorp.co.uk"),
        ("https://acme.wd5.myworkdayjobs.com/en-US/careers", "myworkdayjobs.com"),
        ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse.io"),
        ("https://jobs.lever.co/acme/abc", "lever.co"),
        ("localhost", None),
        ("http://127.0.0.1:8100/x", None),
        ("", None),
        (None, None),
    ],
)
def test_registrable_domain(value, expected):
    assert registrable_domain(value) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        (LINKEDIN_POSTING, "LinkedIn"),
        ("https://uk.indeed.com/viewjob?jk=1", "Indeed"),
        ("https://www.glassdoor.com/job-listing/x", "Glassdoor"),
        ("https://www.glassdoor.co.uk/job-listing/x", "Glassdoor"),
        ("https://wellfound.com/jobs/1", "Wellfound"),
        ("https://www.bayt.com/en/uae/jobs/x", "Bayt"),
        ("https://www.rozee.pk/job/x", "Rozee"),
        ("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1", "Workday"),
        ("https://boards.greenhouse.io/acme/jobs/1", "Greenhouse"),
        ("https://jobs.lever.co/acme/abc", "Lever"),
        # Unknown board: the registrable domain becomes the portal name.
        ("https://careers.techcorp.com/job/1", "techcorp.com"),
        ("https://jobs.some-tiny-board.io/x", "some-tiny-board.io"),
    ],
)
def test_portal_name_for_domain(url, expected):
    assert portal_name_for_domain(registrable_domain(url)) == expected


def test_job_board_domains_are_never_a_company_identity():
    """Two postings on LinkedIn are two employers, not one company."""
    assert company_domain(LINKEDIN_POSTING) is None
    assert company_domain("https://acme.wd5.myworkdayjobs.com/x") is None
    assert company_domain("https://www.techcorp.com/careers") == "techcorp.com"


# ---------------------------------------------------------------------------
# POST /api/capture
# ---------------------------------------------------------------------------


async def test_capture_creates_company_portal_and_application(
    client, register, make_group
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        company_website="https://techcorp.com",
        location="Dubai",
        posting_url=LINKEDIN_POSTING,
        job_title="Senior Backend Engineer",
        jd_text="We need Python and SQL.",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "company_id",
        "company_name",
        "application_id",
        "status",
        "job_title",
        "created_company",
        "created_portal",
        "portal_name",
    }
    assert body["company_name"] == "TechCorp"
    assert body["job_title"] == "Senior Backend Engineer"
    assert body["created_company"] is True
    assert body["created_portal"] is True
    assert body["portal_name"] == "LinkedIn"
    assert body["status"] == "saved"

    detail = (
        await client.get(f"/api/companies/{body['company_id']}", headers=account["headers"])
    ).json()
    assert detail["website"] == "https://techcorp.com"
    assert detail["location"] == "Dubai"
    assert len(detail["applications"]) == 1
    application = detail["applications"][0]
    assert application["id"] == body["application_id"]
    assert application["status"] == "saved"
    assert application["url"] == LINKEDIN_POSTING
    assert application["job_title"] == "Senior Backend Engineer"
    assert application["jd_text"] == "We need Python and SQL."
    assert application["applied_via_portal_name"] == "LinkedIn"


async def test_capture_twice_creates_no_duplicate_company(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    first = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        posting_url=LINKEDIN_POSTING,
    )
    second = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        # Same employer, spelled the way a different page renders it.
        company_name="TechCorp, Inc.",
        posting_url="https://www.linkedin.com/jobs/view/999/",
        jd_text="Second posting.",
        status="applied",
    )
    assert second.status_code == 200, second.text
    assert second.json()["created_company"] is False
    assert second.json()["created_portal"] is False
    assert second.json()["company_id"] == first.json()["company_id"]
    assert second.json()["application_id"] == first.json()["application_id"]
    assert second.json()["status"] == "applied"

    companies = (
        await client.get(f"/api/groups/{group['id']}/companies", headers=account["headers"])
    ).json()
    assert len(companies) == 1
    portals = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    assert len(portals) == 1

    application = companies[0]["applications"][0]
    assert application["status"] == "applied"
    detail = (
        await client.get(
            f"/api/companies/{first.json()['company_id']}", headers=account["headers"]
        )
    ).json()
    assert detail["applications"][0]["jd_text"] == "Second posting."
    assert detail["applications"][0]["url"] == "https://www.linkedin.com/jobs/view/999/"


async def test_capture_dedupes_on_website_domain(client, register, make_group):
    """A different trading name with the same website is the same company."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    first = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        company_website="https://www.techcorp.com/",
    )
    second = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="Tech Corp Global",
        company_website="https://careers.techcorp.com/jobs",
    )
    assert second.json()["created_company"] is False
    assert second.json()["company_id"] == first.json()["company_id"]
    companies = (
        await client.get(f"/api/groups/{group['id']}/companies", headers=account["headers"])
    ).json()
    assert len(companies) == 1
    # The stored name is the one the squad already had.
    assert companies[0]["name"] == "TechCorp"


async def test_capture_reuses_a_hand_made_company_and_fills_blanks(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    existing = await make_company(account["headers"], group["id"], name="TechCorp")
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp Ltd",
        company_website="https://techcorp.com",
        careers_url="https://techcorp.com/careers",
        location="Dubai",
    )
    assert resp.json()["company_id"] == existing["id"]
    assert resp.json()["created_company"] is False
    detail = (
        await client.get(f"/api/companies/{existing['id']}", headers=account["headers"])
    ).json()
    assert detail["website"] == "https://techcorp.com"
    assert detail["careers_url"] == "https://techcorp.com/careers"
    assert detail["location"] == "Dubai"


async def test_capture_never_overwrites_curated_company_fields(
    client, register, make_group, make_company
):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    existing = await make_company(
        account["headers"], group["id"], name="TechCorp", location="Dubai"
    )
    await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        location="Remote",
    )
    detail = (
        await client.get(f"/api/companies/{existing['id']}", headers=account["headers"])
    ).json()
    assert detail["location"] == "Dubai"


async def test_capture_reuses_a_hand_made_portal(client, register, make_group, make_portal):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    existing = await make_portal(account["headers"], group["id"], name="linkedin")
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        posting_url=LINKEDIN_POSTING,
    )
    assert resp.json()["created_portal"] is False
    assert resp.json()["portal_name"] == "linkedin"
    portals = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    assert [p["id"] for p in portals] == [existing["id"]]


async def test_capture_without_posting_url_has_no_portal(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client, account["headers"], group_id=group["id"], company_name="TechCorp"
    )
    assert resp.status_code == 200
    assert resp.json()["portal_name"] is None
    assert resp.json()["created_portal"] is False
    portals = (
        await client.get(f"/api/groups/{group['id']}/portals", headers=account["headers"])
    ).json()
    assert portals == []


async def test_recapture_does_not_reset_status_or_clear_fields(
    client, register, make_group
):
    """Merge semantics: re-capturing a posting must not drag an interview back
    to "saved" or wipe a job description the user already has."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    first = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        posting_url=LINKEDIN_POSTING,
        jd_text="Original JD.",
        status="interview",
    )
    assert first.json()["status"] == "interview"
    second = await _capture(
        client, account["headers"], group_id=group["id"], company_name="TechCorp"
    )
    assert second.json()["status"] == "interview"
    detail = (
        await client.get(
            f"/api/companies/{first.json()['company_id']}", headers=account["headers"]
        )
    ).json()
    application = detail["applications"][0]
    assert application["jd_text"] == "Original JD."
    assert application["url"] == LINKEDIN_POSTING


async def test_recapture_without_a_title_keeps_the_saved_one(
    client, register, make_group
):
    """The extension often cannot read the role. Missing must never mean
    "clear what the user already has"."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    first = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="Senior Backend Engineer",
    )
    assert first.json()["job_title"] == "Senior Backend Engineer"
    second = await _capture(
        client, account["headers"], group_id=group["id"], company_name="TechCorp"
    )
    assert second.json()["job_title"] == "Senior Backend Engineer"
    # A blank title is the same as no title.
    third = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="   ",
    )
    assert third.json()["job_title"] == "Senior Backend Engineer"


async def test_recapture_with_a_new_title_replaces_it(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="Backend Engineer",
    )
    second = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="  Staff Backend Engineer  ",
    )
    assert second.json()["job_title"] == "Staff Backend Engineer"


async def test_capture_job_title_over_the_cap_is_422(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="x" * 201,
    )
    assert resp.status_code == 422
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        job_title="x" * 200,
    )
    assert resp.status_code == 200, resp.text


async def test_capture_records_activity(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        posting_url=LINKEDIN_POSTING,
    )
    types = [
        row["type"]
        for row in (
            await client.get(
                f"/api/groups/{group['id']}/activity", headers=account["headers"]
            )
        ).json()
    ]
    assert "company_added" in types
    assert "portal_added" in types
    assert "application_status_changed" in types


async def test_capture_into_a_group_i_am_not_in_is_404(client, register, make_group):
    owner = await register(username="haris")
    outsider = await register(username="ali")
    group = await make_group(owner["headers"])
    resp = await _capture(
        client, outsider["headers"], group_id=group["id"], company_name="TechCorp"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Group not found"
    # Nothing was written into the group.
    companies = (
        await client.get(f"/api/groups/{group['id']}/companies", headers=owner["headers"])
    ).json()
    assert companies == []


async def test_capture_into_an_unknown_group_is_404(client, register):
    account = await register(username="haris")
    resp = await _capture(
        client, account["headers"], group_id=999_999, company_name="TechCorp"
    )
    assert resp.status_code == 404


async def test_capture_needs_auth(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.post(
        "/api/capture", json={"group_id": group["id"], "company_name": "TechCorp"}
    )
    assert resp.status_code == 401


async def test_capture_with_an_extension_token(client, register, make_group):
    """The whole point of E1: the extension's own credential works here."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    paired = (
        await client.post("/api/auth/extension-token", headers=account["headers"])
    ).json()
    headers = {"Authorization": f"Bearer {paired['token']}"}
    resp = await _capture(
        client,
        headers,
        group_id=group["id"],
        company_name="TechCorp",
        posting_url=LINKEDIN_POSTING,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created_company"] is True


async def test_jd_text_over_the_cap_is_422(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        jd_text="x" * (JD_TEXT_MAX + 1),
    )
    assert resp.status_code == 422


async def test_jd_text_at_the_cap_is_accepted(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        jd_text="x" * JD_TEXT_MAX,
    )
    assert resp.status_code == 200, resp.text


async def test_blank_company_name_is_422(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client, account["headers"], group_id=group["id"], company_name="   "
    )
    assert resp.status_code == 422


async def test_invalid_status_is_422(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        status="hired",
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/capture/lookup
# ---------------------------------------------------------------------------


async def test_lookup_returns_my_status_and_the_squad(
    client, register, make_group, make_company
):
    owner = await register(username="haris")
    friend = await register(username="ali", display_name="Ali")
    group = await make_group(owner["headers"])
    await _join(client, friend["headers"], group)
    company = await make_company(
        owner["headers"], group["id"], name="TechCorp", website="https://techcorp.com"
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=owner["headers"],
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "rejected"},
        headers=friend["headers"],
    )

    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "company_name": "TechCorp Inc"},
        headers=owner["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"company_id", "company_name", "my_status", "squad"}
    assert body["company_id"] == company["id"]
    assert body["company_name"] == "TechCorp"
    assert body["my_status"] == "applied"
    assert body["squad"] == [{"display_name": "Ali", "status": "rejected"}]


async def test_lookup_resolves_by_url_domain(client, register, make_group, make_company):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    company = await make_company(
        account["headers"], group["id"], name="TechCorp", website="https://techcorp.com"
    )
    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "url": "https://careers.techcorp.com/job/1"},
        headers=account["headers"],
    )
    assert resp.json()["company_id"] == company["id"]
    assert resp.json()["my_status"] is None
    assert resp.json()["squad"] == []


async def test_lookup_does_not_match_on_a_job_board_url(
    client, register, make_group, make_company
):
    """A LinkedIn URL must not resolve to whichever company happens to list
    linkedin.com as its website."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    await make_company(
        account["headers"], group["id"], name="Some Recruiter",
        website="https://www.linkedin.com/company/some-recruiter",
    )
    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "url": LINKEDIN_POSTING},
        headers=account["headers"],
    )
    assert resp.json()["company_id"] is None


async def test_lookup_unknown_company_is_all_null(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "company_name": "Nobody"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "company_id": None,
        "company_name": None,
        "my_status": None,
        "squad": [],
    }


async def test_lookup_for_a_non_member_is_404(client, register, make_group, make_company):
    owner = await register(username="haris")
    outsider = await register(username="ali")
    group = await make_group(owner["headers"])
    await make_company(owner["headers"], group["id"], name="TechCorp")
    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "company_name": "TechCorp"},
        headers=outsider["headers"],
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Group not found"


async def test_lookup_needs_auth(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.get("/api/capture/lookup", params={"group_id": group["id"]})
    assert resp.status_code == 401


async def test_lookup_without_group_id_is_422(client, register):
    account = await register(username="haris")
    resp = await client.get("/api/capture/lookup", headers=account["headers"])
    assert resp.status_code == 422


async def test_lookup_after_capture_sees_what_was_written(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    captured = await _capture(
        client,
        account["headers"],
        group_id=group["id"],
        company_name="TechCorp",
        company_website="https://techcorp.com",
        posting_url=LINKEDIN_POSTING,
        status="applied",
    )
    resp = await client.get(
        "/api/capture/lookup",
        params={"group_id": group["id"], "company_name": "techcorp ltd"},
        headers=account["headers"],
    )
    assert resp.json()["company_id"] == captured.json()["company_id"]
    assert resp.json()["my_status"] == "applied"


# ---------------------------------------------------------------------------
# POST /api/capture/lookup (F3): the same lookup with the browsed URL in the
# body, where it stays out of the server's access log.
# ---------------------------------------------------------------------------


async def test_post_lookup_matches_the_get_exactly(
    client, register, make_group, make_company
):
    owner = await register(username="haris")
    friend = await register(username="ali", display_name="Ali")
    group = await make_group(owner["headers"])
    await _join(client, friend["headers"], group)
    company = await make_company(
        owner["headers"], group["id"], name="TechCorp", website="https://techcorp.com"
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "applied"},
        headers=owner["headers"],
    )
    await client.put(
        f"/api/companies/{company['id']}/application",
        json={"status": "rejected"},
        headers=friend["headers"],
    )

    params = {"group_id": group["id"], "url": "https://careers.techcorp.com/job/1"}
    from_get = await client.get(
        "/api/capture/lookup", params=params, headers=owner["headers"]
    )
    from_post = await client.post(
        "/api/capture/lookup", json=params, headers=owner["headers"]
    )
    assert from_post.status_code == 200, from_post.text
    assert from_post.json() == from_get.json()
    assert from_post.json()["my_status"] == "applied"
    assert from_post.json()["squad"] == [{"display_name": "Ali", "status": "rejected"}]


async def test_post_lookup_unknown_company_is_all_null(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.post(
        "/api/capture/lookup",
        json={"group_id": group["id"], "company_name": "Nobody"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "company_id": None,
        "company_name": None,
        "my_status": None,
        "squad": [],
    }


async def test_post_lookup_for_a_non_member_is_404(
    client, register, make_group, make_company
):
    owner = await register(username="haris")
    outsider = await register(username="ali")
    group = await make_group(owner["headers"])
    await make_company(owner["headers"], group["id"], name="TechCorp")
    resp = await client.post(
        "/api/capture/lookup",
        json={"group_id": group["id"], "company_name": "TechCorp"},
        headers=outsider["headers"],
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Group not found"


async def test_post_lookup_needs_auth_and_a_group_id(client, register, make_group):
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.post("/api/capture/lookup", json={"group_id": group["id"]})
    assert resp.status_code == 401
    resp = await client.post(
        "/api/capture/lookup", json={"company_name": "X"}, headers=account["headers"]
    )
    assert resp.status_code == 422


async def test_post_lookup_keeps_the_url_out_of_the_query_string(
    client, register, make_group
):
    """The point of the POST form: nothing private lands in the request line
    that uvicorn writes to the access log."""
    account = await register(username="haris")
    group = await make_group(account["headers"])
    resp = await client.post(
        "/api/capture/lookup",
        json={"group_id": group["id"], "url": "https://boards.example.com/secret-job"},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    assert resp.request.url.query == b""
    assert "secret-job" not in str(resp.request.url)
