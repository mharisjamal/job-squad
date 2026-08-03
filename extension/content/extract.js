/*
 * JobSquad extraction script.
 *
 * Injected on demand with chrome.scripting.executeScript on the tab the user
 * invoked the extension on, so the extension needs no job board host
 * permissions (activeTab is enough).
 *
 * Order, per the frozen E1 contract:
 *   1. schema.org/JobPosting JSON-LD
 *   2. site rules: LinkedIn, Indeed, Workday, Greenhouse, Lever
 *   3. generic fallback: cleaned document.title, og meta, largest main block
 *
 * Always resolves to {company_name, job_title, location, posting_url, jd_text,
 * jd_source} with empty strings for anything it could not find, and never
 * throws. jd_source records which of the three stages produced the description,
 * so the popup can refuse to tick "Include job description" by default when the
 * text came from the generic fallback rather than a recognised posting. The
 * value of the last expression is what executeScript hands back, so this file
 * ends in an immediately invoked function that returns the result object.
 */

(function jobsquadExtract() {
  "use strict";

  var MAX_JD = 50000;

  function blankResult() {
    return {
      company_name: "",
      job_title: "",
      location: "",
      posting_url: "",
      jd_text: "",
      // "jsonld", "site", "generic", or "" when there is no description.
      jd_source: ""
    };
  }

  /* ------------------------------------------------------------- text utils */

  function oneLine(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/\s+/g, " ").trim();
  }

  function block(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/\r\n?/g, "\n")
      .replace(/[ \t\u00a0\u200b]+/g, " ")
      .split("\n")
      .map(function (line) {
        return line.trim();
      })
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function stripJunk(root) {
    if (!root || !root.querySelectorAll) return;
    var junk = root.querySelectorAll("script, style, noscript, template, svg, iframe, canvas");
    for (var i = 0; i < junk.length; i++) {
      var node = junk[i];
      if (node && node.parentNode) node.parentNode.removeChild(node);
    }
  }

  // innerText already skips script/style and anything not rendered, so it is
  // the better source when the node is live. The clone path is the fallback
  // for detached or hidden nodes.
  function textFrom(node) {
    if (!node) return "";
    try {
      var live = node.innerText;
      if (live && live.trim()) return block(live);
    } catch (err) {
      // Fall through to the clone.
    }
    try {
      var copy = node.cloneNode(true);
      stripJunk(copy);
      return block(copy.textContent || "");
    } catch (err) {
      return "";
    }
  }

  function htmlToText(html) {
    if (!html) return "";
    var raw = String(html);
    if (raw.indexOf("<") === -1) return block(raw);
    var spaced = raw
      .replace(/<\s*br\s*\/?\s*>/gi, "\n")
      .replace(/<\/\s*(p|div|li|ul|ol|h[1-6]|tr|section|article)\s*>/gi, "\n");
    try {
      var doc = new DOMParser().parseFromString(spaced, "text/html");
      stripJunk(doc.body);
      return block(doc.body ? doc.body.textContent || "" : "");
    } catch (err) {
      return block(spaced.replace(/<[^>]*>/g, " "));
    }
  }

  function firstText(selectors, root) {
    var scope = root || document;
    for (var i = 0; i < selectors.length; i++) {
      var node = null;
      try {
        node = scope.querySelector(selectors[i]);
      } catch (err) {
        node = null;
      }
      if (!node) continue;
      var value = oneLine(textFrom(node));
      if (value) return value;
    }
    return "";
  }

  function firstNode(selectors, root) {
    var scope = root || document;
    for (var i = 0; i < selectors.length; i++) {
      var node = null;
      try {
        node = scope.querySelector(selectors[i]);
      } catch (err) {
        node = null;
      }
      if (node) return node;
    }
    return null;
  }

  function metaContent(names) {
    for (var i = 0; i < names.length; i++) {
      var node = null;
      try {
        node =
          document.querySelector('meta[property="' + names[i] + '"]') ||
          document.querySelector('meta[name="' + names[i] + '"]');
      } catch (err) {
        node = null;
      }
      if (node) {
        var value = oneLine(node.getAttribute("content"));
        if (value) return value;
      }
    }
    return "";
  }

  function prettifySlug(slug) {
    var value = oneLine(String(slug || "").replace(/[-_+]+/g, " "));
    if (!value) return "";
    return value
      .split(" ")
      .map(function (word) {
        if (!word) return "";
        if (word.length <= 3 && word === word.toUpperCase()) return word;
        return word.charAt(0).toUpperCase() + word.slice(1);
      })
      .join(" ")
      .trim();
  }

  function pathParts() {
    return window.location.pathname.split("/").filter(function (part) {
      return part.length > 0;
    });
  }

  /* ------------------------------------------------------------------ urls */

  function canonicalUrl() {
    try {
      var link = document.querySelector('link[rel="canonical"]');
      if (link && link.href) {
        var parsed = new URL(link.href, window.location.href);
        if (parsed.host === window.location.host && parsed.pathname && parsed.pathname !== "/") {
          return parsed.href;
        }
      }
    } catch (err) {
      // A malformed canonical is simply ignored.
    }
    return window.location.href;
  }

  // A posting can put anything in its JSON-LD url, including javascript: and
  // data: payloads. Only http and https ever survive this.
  function safeUrl(value) {
    var text = oneLine(value);
    if (!text) return "";
    try {
      var parsed = new URL(text, window.location.href);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
    } catch (err) {
      return "";
    }
    return "";
  }

  /* -------------------------------------------------------------- json-ld */

  function collectNodes(value, out, depth) {
    if (!value || depth > 6) return;
    if (Array.isArray(value)) {
      for (var i = 0; i < value.length; i++) collectNodes(value[i], out, depth + 1);
      return;
    }
    if (typeof value !== "object") return;
    out.push(value);
    if (value["@graph"]) collectNodes(value["@graph"], out, depth + 1);
    if (value.mainEntity) collectNodes(value.mainEntity, out, depth + 1);
    if (value.itemListElement) collectNodes(value.itemListElement, out, depth + 1);
    if (value.item) collectNodes(value.item, out, depth + 1);
  }

  function jsonLdNodes() {
    var out = [];
    var scripts;
    try {
      scripts = document.querySelectorAll('script[type="application/ld+json"]');
    } catch (err) {
      return out;
    }
    for (var i = 0; i < scripts.length; i++) {
      var raw = scripts[i].textContent;
      if (!raw || !raw.trim()) continue;
      var parsed = null;
      try {
        parsed = JSON.parse(raw);
      } catch (err) {
        try {
          parsed = JSON.parse(raw.replace(/[\u0000-\u001f]+/g, " "));
        } catch (err2) {
          parsed = null;
        }
      }
      if (parsed) collectNodes(parsed, out, 0);
    }
    return out;
  }

  function isJobPosting(node) {
    var type = node && node["@type"];
    if (!type) return false;
    if (Array.isArray(type)) {
      for (var i = 0; i < type.length; i++) {
        if (String(type[i]).toLowerCase() === "jobposting") return true;
      }
      return false;
    }
    return String(type).toLowerCase() === "jobposting";
  }

  function nameOf(value) {
    if (!value) return "";
    if (typeof value === "string") return oneLine(value);
    if (Array.isArray(value)) return nameOf(value[0]);
    if (typeof value === "object") {
      if (typeof value.name === "string") return oneLine(value.name);
      if (value.name) return nameOf(value.name);
      if (typeof value.legalName === "string") return oneLine(value.legalName);
    }
    return "";
  }

  function addressString(address) {
    if (!address) return "";
    if (typeof address === "string") return oneLine(address);
    if (Array.isArray(address)) return addressString(address[0]);
    if (typeof address !== "object") return "";
    var parts = [
      nameOf(address.addressLocality) || oneLine(address.addressLocality),
      nameOf(address.addressRegion) || oneLine(address.addressRegion),
      nameOf(address.addressCountry) || oneLine(address.addressCountry)
    ];
    var seen = {};
    var kept = [];
    for (var i = 0; i < parts.length; i++) {
      var part = oneLine(parts[i]);
      if (!part) continue;
      var key = part.toLowerCase();
      if (seen[key]) continue;
      seen[key] = true;
      kept.push(part);
    }
    return kept.join(", ");
  }

  function jobLocationString(node) {
    var location = node.jobLocation;
    var value = "";
    if (Array.isArray(location)) {
      for (var i = 0; i < location.length && !value; i++) {
        value = addressString(location[i] && location[i].address ? location[i].address : location[i]);
      }
    } else if (location && typeof location === "object") {
      value = addressString(location.address ? location.address : location);
    } else if (typeof location === "string") {
      value = oneLine(location);
    }
    if (!value) {
      var remoteType = oneLine(node.jobLocationType);
      if (remoteType && remoteType.toUpperCase() === "TELECOMMUTE") value = "Remote";
    }
    if (!value && node.applicantLocationRequirements) {
      value = nameOf(node.applicantLocationRequirements);
    }
    return value;
  }

  function fromJsonLd() {
    var nodes = jsonLdNodes();
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      if (!isJobPosting(node)) continue;
      var result = blankResult();
      result.job_title = oneLine(node.title) || oneLine(node.name);
      result.company_name = nameOf(node.hiringOrganization);
      result.location = jobLocationString(node);
      result.jd_text = htmlToText(node.description);
      result.posting_url = safeUrl(node.url);
      if (result.job_title || result.company_name || result.jd_text) return result;
    }
    return null;
  }

  /* ---------------------------------------------------------- site rules */

  function linkedInRule() {
    var result = blankResult();
    result.job_title = firstText([
      ".job-details-jobs-unified-top-card__job-title h1",
      ".job-details-jobs-unified-top-card__job-title",
      ".jobs-unified-top-card__job-title",
      ".top-card-layout__title",
      "h1.topcard__title",
      ".topcard__title",
      "h1"
    ]);
    result.company_name = firstText([
      ".job-details-jobs-unified-top-card__company-name a",
      ".job-details-jobs-unified-top-card__company-name",
      ".jobs-unified-top-card__company-name",
      "a.topcard__org-name-link",
      ".topcard__org-name-link",
      ".top-card-layout__second-subline a"
    ]);
    result.location = firstText([
      ".job-details-jobs-unified-top-card__primary-description-container .tvm__text",
      ".job-details-jobs-unified-top-card__bullet",
      ".jobs-unified-top-card__bullet",
      ".topcard__flavor--bullet",
      ".top-card-layout__second-subline .topcard__flavor:nth-child(2)"
    ]);
    result.jd_text = textFrom(
      firstNode([
        "#job-details",
        ".jobs-description__content",
        ".jobs-box__html-content",
        ".description__text",
        ".show-more-less-html__markup"
      ])
    );

    // Collections view keeps the real posting id in the query string.
    var jobId = "";
    var match = window.location.pathname.match(/\/jobs\/view\/(\d+)/);
    if (match) {
      jobId = match[1];
    } else {
      try {
        jobId = new URLSearchParams(window.location.search).get("currentJobId") || "";
      } catch (err) {
        jobId = "";
      }
    }
    if (/^\d+$/.test(jobId)) {
      result.posting_url = "https://www.linkedin.com/jobs/view/" + jobId + "/";
    }
    return result;
  }

  function indeedRule() {
    var result = blankResult();
    result.job_title = firstText([
      'h1.jobsearch-JobInfoHeader-title span',
      "h1.jobsearch-JobInfoHeader-title",
      '[data-testid="jobsearch-JobInfoHeader-title"]',
      ".jobsearch-JobInfoHeader-title",
      "h2.jobTitle",
      "h1"
    ]);
    result.company_name = firstText([
      '[data-testid="inlineHeader-companyName"] a',
      '[data-testid="inlineHeader-companyName"]',
      '[data-company-name="true"]',
      ".jobsearch-CompanyInfoContainer a",
      ".jobsearch-InlineCompanyRating div:first-child",
      ".jobsearch-CompanyReview--heading"
    ]);
    result.location = firstText([
      '[data-testid="inlineHeader-companyLocation"]',
      '[data-testid="job-location"]',
      '[data-testid="jobsearch-JobInfoHeader-companyLocation"]',
      ".jobsearch-JobInfoHeader-subtitle > div:last-child"
    ]);
    result.jd_text = textFrom(
      firstNode(["#jobDescriptionText", ".jobsearch-jobDescriptionText", '[id="jobDescriptionText"]'])
    );
    return result;
  }

  function workdayRule() {
    var result = blankResult();
    result.job_title = firstText([
      '[data-automation-id="jobPostingHeader"]',
      'h2[data-automation-id="jobPostingHeader"]',
      '[data-automation-id="jobTitle"]',
      "h1",
      "h2"
    ]);
    result.location = firstText([
      '[data-automation-id="locations"] dd',
      '[data-automation-id="locations"]',
      '[data-automation-id="jobPostingLocation"]'
    ]);
    result.jd_text = textFrom(
      firstNode([
        '[data-automation-id="jobPostingDescription"]',
        '[data-automation-id="jobPostingPage"]',
        "main"
      ])
    );
    // acme.wd5.myworkdayjobs.com carries the employer in the first host label.
    var host = window.location.hostname.split(".");
    if (host.length && host[0] && host[0] !== "www") result.company_name = prettifySlug(host[0]);
    return result;
  }

  function greenhouseRule() {
    var result = blankResult();
    result.job_title = firstText([
      "h1.app-title",
      ".job__title h1",
      ".job__title",
      '[class*="job-title"]',
      "h1"
    ]);
    result.company_name = firstText([".company-name", ".job__company", '[class*="company-name"]']);
    result.location = firstText([".location", ".job__location", '[class*="job-location"]']);
    result.jd_text = textFrom(firstNode(["#content", ".job__description", ".job-post", "main"]));

    // boards.greenhouse.io/{slug}/jobs/{id} and the embed variant.
    var parts = pathParts();
    var slug = "";
    if (parts.length && parts[0] !== "embed") slug = parts[0];
    if (!slug) {
      try {
        slug = new URLSearchParams(window.location.search).get("for") || "";
      } catch (err) {
        slug = "";
      }
    }
    if (!result.company_name && slug) result.company_name = prettifySlug(slug);
    // Greenhouse renders the company as "at Acme" in some themes.
    result.company_name = result.company_name.replace(/^at\s+/i, "").trim();
    return result;
  }

  function leverRule() {
    var result = blankResult();
    result.job_title = firstText([
      ".posting-headline h2",
      '[data-qa="posting-name"]',
      ".posting-header h2",
      "h2",
      "h1"
    ]);
    result.location = firstText([
      ".posting-categories .location",
      ".posting-categories .sort-by-location",
      '[class*="location"]'
    ]);
    result.jd_text = textFrom(
      firstNode([
        ".section-wrapper.page-full-width",
        '[data-qa="job-description"]',
        ".content .section-wrapper",
        ".posting-page",
        "main"
      ])
    );
    var parts = pathParts();
    if (parts.length) result.company_name = prettifySlug(parts[0]);
    var logo = firstNode([".main-header-logo img", "img.main-header-logo"]);
    if (logo) {
      var alt = oneLine(logo.getAttribute("alt"));
      if (alt) result.company_name = alt.replace(/\s+logo$/i, "").trim();
    }
    return result;
  }

  function siteRule() {
    var host = window.location.hostname.toLowerCase().replace(/^www\./, "");
    try {
      if (host === "linkedin.com" || /\.linkedin\.com$/.test(host)) return linkedInRule();
      if (host.indexOf("indeed.") === 0 || /(^|\.)indeed\.com$/.test(host) || /\.indeed\./.test(host)) {
        return indeedRule();
      }
      if (/myworkdayjobs\.com$/.test(host) || /myworkdaysite\.com$/.test(host)) return workdayRule();
      if (/greenhouse\.io$/.test(host)) return greenhouseRule();
      if (/lever\.co$/.test(host)) return leverRule();
    } catch (err) {
      return null;
    }
    return null;
  }

  /* ------------------------------------------------------------- fallback */

  var SEPARATORS = /\s+[|\u2013\u2014\u2022\u00b7\u203a>]\s+|\s+-\s+/;

  function cleanTitle(raw, siteName, companyName) {
    var title = oneLine(raw);
    if (!title) return "";
    var segments = title.split(SEPARATORS).filter(function (part) {
      return oneLine(part).length > 0;
    });
    if (segments.length > 1) {
      var last = oneLine(segments[segments.length - 1]);
      var site = oneLine(siteName);
      if (site && last.toLowerCase() === site.toLowerCase()) {
        segments.pop();
      } else {
        segments = [segments[0]];
      }
      title = oneLine(segments.join(" - "));
    }
    if (companyName) {
      var escaped = companyName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      title = title.replace(new RegExp("\\s+(at|@)\\s+" + escaped + "\\s*$", "i"), "").trim();
    }
    title = title.replace(/\s*[-|]\s*$/, "").trim();
    return title;
  }

  function largestMainBlock() {
    var candidates = [];
    try {
      var nodes = document.querySelectorAll(
        'main, article, [role="main"], #content, #main, #job, .job-description'
      );
      for (var i = 0; i < nodes.length; i++) candidates.push(nodes[i]);
    } catch (err) {
      candidates = [];
    }
    var best = "";
    for (var j = 0; j < candidates.length; j++) {
      var text = textFrom(candidates[j]);
      if (text.length > best.length) best = text;
    }
    if (best.length >= 200) return best;
    var bodyText = textFrom(document.body);
    return bodyText.length > best.length ? bodyText : best;
  }

  function fallbackRule(companyHint) {
    var result = blankResult();
    var siteName = metaContent(["og:site_name"]);
    var company =
      companyHint ||
      siteName ||
      metaContent(["author", "twitter:site"]) ||
      prettifySlug(window.location.hostname.replace(/^www\./, "").split(".")[0]);
    result.company_name = oneLine(company).replace(/^@/, "");
    result.job_title = cleanTitle(
      metaContent(["og:title", "twitter:title"]) || document.title,
      siteName,
      result.company_name
    );
    result.jd_text = largestMainBlock();
    return result;
  }

  /* ------------------------------------------------------------------ run */

  function merge(target, source) {
    if (!source) return target;
    ["company_name", "job_title", "location", "posting_url", "jd_text"].forEach(function (key) {
      if (!target[key] && source[key]) target[key] = source[key];
    });
    return target;
  }

  var result = blankResult();

  // Where jd_text came from. The popup uses this to decide whether including
  // the description is safe enough to tick by default: "jsonld" and "site" mean
  // this really is a job posting, while "generic" means we scraped the main
  // text block of an arbitrary page, which could just as easily be a private
  // wiki or an email thread.
  var jdSource = "";

  function noteJdSource(stage) {
    if (!jdSource && result.jd_text) jdSource = stage;
  }

  try {
    merge(result, fromJsonLd());
    noteJdSource("jsonld");
  } catch (err) {
    // A broken JSON-LD block must not stop the site rules from running.
  }

  try {
    merge(result, siteRule());
    noteJdSource("site");
  } catch (err) {
    // Same for a site rule that hit an unexpected DOM.
  }

  try {
    merge(result, fallbackRule(result.company_name));
    noteJdSource("generic");
  } catch (err) {
    // The fallback is best effort by definition.
  }

  try {
    // Anything that is not http or https is dropped, then replaced by the live
    // page URL, which the popup has already limited to http(s) pages.
    result.posting_url = safeUrl(result.posting_url) || safeUrl(canonicalUrl());
    result.company_name = oneLine(result.company_name);
    result.job_title = oneLine(result.job_title);
    result.location = oneLine(result.location);
    result.jd_text = block(result.jd_text);
    if (result.jd_text.length > MAX_JD) result.jd_text = result.jd_text.slice(0, MAX_JD);
    result.jd_source = result.jd_text ? jdSource : "";
  } catch (err) {
    return blankResult();
  }

  return result;
})();
