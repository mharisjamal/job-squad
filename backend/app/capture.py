"""Matching rules for the browser-extension capture endpoints (Phase E1).

Pure functions, no database and no request objects, so the dedupe behavior -
the thing that decides whether a repeat capture of the same posting creates a
second company - is directly testable and identical on both capture routes.
"""

import re
from urllib.parse import urlsplit

# Legal-form words stripped from the TAIL of a company name before matching, so
# "Acme Pvt Ltd", "Acme, Inc." and "Acme" are one company. Only trailing tokens
# are removed, and never the last one, so a company literally named "Co" keeps
# its name.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "incorporated", "llc", "lc", "ltd", "limited", "plc", "llp", "lp",
        "co", "corp", "corporation", "company", "gmbh", "ag", "bv", "nv", "sa",
        "sas", "srl", "spa", "oy", "ab", "as", "aps", "pvt", "private", "pte",
        "pty", "kk", "kft", "sro", "doo",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Job-board domains that map to a known portal name. Anything else becomes a
# portal named after its own registrable domain (the plan's fallback rule).
PORTAL_NAMES_BY_DOMAIN = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "glassdoor.com": "Glassdoor",
    "wellfound.com": "Wellfound",
    "bayt.com": "Bayt",
    "rozee.pk": "Rozee",
    # Every Workday tenant is <tenant>.<pod>.myworkdayjobs.com, which reduces to
    # this one registrable domain.
    "myworkdayjobs.com": "Workday",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
}

# Glassdoor runs the same product on a dozen country domains (glassdoor.co.uk,
# glassdoor.ca, ...), so it is matched on the brand label rather than listed.
_WILDCARD_BRANDS = frozenset({"glassdoor"})

# Two-label public suffixes: without these, "acme.co.uk" would reduce to
# "co.uk" and every UK company would look like the same one. Not the full
# public suffix list (that would be a dependency); the suffixes a job hunt
# actually meets.
_MULTI_PART_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk", "sch.uk",
        "com.au", "net.au", "org.au", "edu.au", "gov.au",
        "co.nz", "net.nz", "org.nz",
        "co.za", "org.za", "co.ke", "com.ng", "com.gh", "com.eg",
        "com.br", "com.mx", "com.ar", "com.co", "com.pe", "com.ve", "com.uy",
        "co.in", "net.in", "org.in", "com.pk", "com.bd", "com.np", "com.lk",
        "co.jp", "or.jp", "ne.jp", "co.kr", "or.kr", "com.cn", "com.tw",
        "com.hk", "com.sg", "com.my", "com.ph", "com.vn", "co.th", "co.id",
        "com.tr", "com.ua", "com.pl", "com.ru", "co.il",
        "com.sa", "com.qa", "com.kw", "com.bh", "com.om", "com.lb", "com.jo",
    }
)


def normalize_company_name(name: str | None) -> str:
    """A comparison key: lowercased, punctuation-free, whitespace-collapsed,
    with trailing legal-form words removed. Empty when there is nothing to
    compare (the caller treats that as "no match possible")."""
    base = " ".join(_NON_ALNUM.sub(" ", (name or "").lower()).split())
    tokens = base.split()
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def registrable_domain(value: str | None) -> str | None:
    """The registrable domain of a URL or bare host, or None when there is not
    one (blank input, a bare label like "localhost", or an IP address)."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    if "//" not in raw:
        # A bare host such as "acme.com/careers": give urlsplit an authority.
        raw = "//" + raw
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return None
    host = host.strip().lower().rstrip(".")
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return None
    tail = ".".join(labels[-2:])
    if tail in _MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return tail


def is_job_board_domain(domain: str | None) -> bool:
    """True for the domains that host postings for OTHER companies."""
    if not domain:
        return False
    return domain in PORTAL_NAMES_BY_DOMAIN or domain.split(".")[0] in _WILDCARD_BRANDS


def portal_name_for_domain(domain: str | None) -> str | None:
    """The portal name for a posting domain: a known board's proper name, else
    the registrable domain itself."""
    if not domain:
        return None
    known = PORTAL_NAMES_BY_DOMAIN.get(domain)
    if known:
        return known
    if domain.split(".")[0] in _WILDCARD_BRANDS:
        return domain.split(".")[0].title()
    return domain


def company_domain(value: str | None) -> str | None:
    """The domain a COMPANY may be identified by, or None.

    A job-board domain is never a company identity: two postings on
    linkedin.com are two different employers, and merging them would be the
    worst possible dedupe bug.
    """
    domain = registrable_domain(value)
    if domain is None or is_job_board_domain(domain):
        return None
    return domain
