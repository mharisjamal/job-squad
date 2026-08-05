/*
 * JobSquad squad-awareness badges (Phase E2).
 *
 * Runs on LinkedIn job pages and Indeed, and ONLY while the user has granted
 * those optional host permissions from the popup. The service worker registers
 * this script when the permission is granted and unregisters it when it is
 * revoked, so nothing here can run behind the user's back.
 *
 * What it does: read each result row's company name, ask the JobSquad API which
 * of them the squad already has a standing on, and add one small chip to the
 * rows that came back known. A row whose company means nothing to the squad
 * gets nothing at all: silence is the default, because a chip on every row is
 * noise, not information.
 *
 * Rules it holds to:
 *   - Never calls the API directly. Every request goes through the service
 *     worker, so the extension token never exists in a page's process.
 *   - Never uses innerHTML with API data. Chips are built with textContent.
 *   - The chip lives in a CLOSED shadow root, so the page cannot read the
 *     display names and statuses of the user's squad out of the DOM. If a
 *     browser will not give us a closed root, nothing is rendered at all:
 *     showing squadmates' names in page-readable text is worse than showing
 *     nothing.
 *   - Processed rows are tracked in a WeakSet, not a DOM attribute, so the
 *     known/unknown bit is not published to the page as markup. A re-scan
 *     still never double-injects.
 *   - A hard per-document ceiling on how many distinct company names will ever
 *     be resolved, because the page supplies the rows and therefore controls
 *     what we would otherwise look up.
 *   - Re-scans on DOM mutation behind a debounce, because both boards are SPAs
 *     that swap the whole results list without a page load.
 *   - Adds nodes; never removes, reorders, rewrites or blocks anything the page
 *     put there.
 *
 * Residual limit, stated honestly: a chip is a visible box in the page's own
 * layout, so the page can still detect that a row got one, and roughly how wide
 * it is, by measuring layout. The known/unknown bit is therefore NOT fully
 * hidden from a determined page. What the closed shadow root protects is the
 * contents: squadmates' display names and their statuses, which is the part
 * that is nobody's business but the user's.
 *
 * The IIFE returns its internals so the jsdom test harness can exercise the
 * pure parts (row discovery, company extraction, chip text) directly. Nothing
 * in the extension reads that value.
 */

(function jobsquadBadges() {
  "use strict";

  var CHIP_CLASS = "jobsquad-chip";

  var DEBOUNCE_MS = 400;
  // Matches the server's LOOKUP_BATCH_MAX; a longer list would be a 422.
  var MAX_NAMES_PER_CALL = 50;
  var MAX_ROWS_PER_SCAN = 120;
  // Bounds the de-nesting walk. Board markup nests deeply, but not this deeply,
  // and a bound means a pathological tree cannot turn one scan into a hang.
  var MAX_ANCESTOR_STEPS = 40;
  // The whole document's budget, not one scan's. The page decides which rows
  // exist and what company text they carry, so without a ceiling it could walk
  // us through a dictionary one mutation at a time.
  var MAX_COMPANIES_PER_DOC = 300;
  var MAX_FAILURES = 3;
  var NAME_MAX = 120;
  // Cut before any normalization. A 20 MB text node is a page's cheapest way to
  // make us allocate; the company name we are after is in the first few dozen
  // characters or it is not there at all.
  var RAW_TEXT_MAX = 512;
  var DISPLAY_MAX = 22;

  var KNOWN_STATUSES = [
    "saved",
    "applied",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "ghosted"
  ];

  // Lives inside each chip's shadow root, never in the page's own head. That
  // keeps the extension out of the page's stylesheet list (one less trivial
  // fingerprint) and keeps the page's cascade off the chip.
  var CHIP_CSS =
    ":host{display:inline-block;max-width:100%;vertical-align:middle;}" +
    "." +
    CHIP_CLASS +
    "{all:initial;display:inline-block;margin:4px 6px 0 0;padding:1px 6px;" +
    "border:1px solid #3fa875;border-radius:3px;background:#edf7f1;color:#14532d;" +
    'font:500 11px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;' +
    "white-space:nowrap;vertical-align:middle;max-width:100%;overflow:hidden;" +
    "text-overflow:ellipsis;}" +
    // Applied from the measured surface below, not from a
    // prefers-color-scheme media query. The query answers "is the OS dark",
    // and the boards carry their own theme: with the OS dark and LinkedIn
    // light, the media query paints a dark chip onto a white card. Measured
    // live on a real results page, which is the only way this shows up.
    // The variant rides a class INSIDE the shadow root rather than an
    // attribute on the host, so it stays unreadable to the page.
    "." +
    CHIP_CLASS +
    "-dark{background:#12241b;color:#8fd6b0;border-color:#2f7a57;}";

  /* ------------------------------------------------------------ site rules */

  var SITES = [
    {
      key: "linkedin",
      host: /(^|\.)linkedin\.com$/i,
      rows: [
        "div.job-card-container",
        "div.job-card-job-posting-card-wrapper",
        "li.jobs-search-results__list-item",
        "li.scaffold-layout__list-item",
        "div.base-search-card",
        "div.job-search-card"
      ],
      company: [
        ".job-card-container__primary-description",
        ".job-card-container__company-name",
        ".job-card-list__company-name",
        ".artdeco-entity-lockup__subtitle",
        "h4.base-search-card__subtitle a",
        ".base-search-card__subtitle",
        ".job-search-card__subtitle-primary-grouping a"
      ]
    },
    {
      key: "indeed",
      host: /(^|\.)indeed\.com$/i,
      rows: [
        "td.resultContent",
        "div.job_seen_beacon",
        "div.cardOutline",
        '[data-testid="slider_item"]'
      ],
      company: [
        '[data-testid="company-name"]',
        "span.companyName",
        "a.companyName",
        ".company_location [data-testid=\"company-name\"]"
      ]
    }
  ];

  function siteFor(host) {
    var name = String(host || "").toLowerCase();
    for (var i = 0; i < SITES.length; i++) {
      if (SITES[i].host.test(name)) return SITES[i];
    }
    return null;
  }

  /* ----------------------------------------------------------------- text */

  // Every string that comes off the page passes through here FIRST. Slicing
  // before normalizing is the whole point: a regex replace over a giant node
  // costs several copies of it, and we would pay that per selector, per row,
  // per scan.
  function clip(value) {
    if (value === null || value === undefined) return "";
    var text = typeof value === "string" ? value : String(value);
    return text.length > RAW_TEXT_MAX ? text.slice(0, RAW_TEXT_MAX) : text;
  }

  function oneLine(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/\s+/g, " ").trim();
  }

  function norm(value) {
    return oneLine(value).toLowerCase();
  }

  // Boards write "Company (dot) Location" or "Company (verified)" into the
  // same node, so the separators the boards actually use are cut off. A plain
  // hyphen is NOT one of them: real employers are called Hewlett-Packard. The
  // dashes are written as escapes so this file stays free of the character the
  // house style bans.
  function cleanCompany(raw) {
    var text = oneLine(clip(raw));
    if (!text) return "";
    text = oneLine(text.split(/[\u00b7\u2022|\u2013\u2014]/)[0]);
    text = text.replace(/\s*\((?:verified|with verification)\)\s*$/i, "");
    text = text.replace(/^[\s,-]+|[\s,-]+$/g, "");
    if (text.length > NAME_MAX) text = text.slice(0, NAME_MAX);
    if (text.length < 2) return "";
    if (/^\d+$/.test(text)) return "";
    return text;
  }

  function statusWord(value) {
    var text = norm(clip(value));
    if (!text) return "tracked";
    for (var i = 0; i < KNOWN_STATUSES.length; i++) {
      if (KNOWN_STATUSES[i] === text) return text;
    }
    return text.length > 16 ? text.slice(0, 16) : text;
  }

  function personName(value) {
    var text = oneLine(clip(value));
    if (text.length > DISPLAY_MAX) text = text.slice(0, DISPLAY_MAX - 1) + ".";
    return text;
  }

  /* ---------------------------------------------------------------- rows */

  // Both boards nest a card inside a list item, and both selector lists match
  // each. Keeping only the innermost match means one row per job, so one chip
  // per job.
  //
  // De-nesting walks each candidate's ancestors and drops any candidate found
  // among them, which costs one bounded walk per candidate. Comparing every
  // candidate against every other one was the same answer at up to 240x the
  // work, on the main thread of a page the user is trying to read.
  //
  // Candidates are collected up to twice the row cap because both selector
  // lists match the card AND its list item: it takes two candidates to yield
  // one row, so collecting only MAX_ROWS_PER_SCAN of them would halve how many
  // jobs on the page ever get looked at.
  function rowNodes(site, root) {
    var scope = root || document;
    var found = [];
    var candidates = new Set();
    var limit = MAX_ROWS_PER_SCAN * 2;
    var i;

    for (i = 0; i < site.rows.length; i++) {
      var nodes;
      try {
        nodes = scope.querySelectorAll(site.rows[i]);
      } catch (err) {
        nodes = [];
      }
      for (var j = 0; j < nodes.length; j++) {
        if (candidates.has(nodes[j])) continue;
        candidates.add(nodes[j]);
        found.push(nodes[j]);
        if (found.length >= limit) break;
      }
      if (found.length >= limit) break;
    }

    var wrappers = new Set();
    for (i = 0; i < found.length; i++) {
      var parent = found[i].parentNode;
      var steps = 0;
      while (parent && steps < MAX_ANCESTOR_STEPS) {
        if (candidates.has(parent)) wrappers.add(parent);
        parent = parent.parentNode;
        steps += 1;
      }
    }

    var kept = [];
    for (i = 0; i < found.length && kept.length < MAX_ROWS_PER_SCAN; i++) {
      if (!wrappers.has(found[i])) kept.push(found[i]);
    }
    return kept;
  }

  function companyFrom(row, site) {
    if (!row || !row.querySelector) return "";
    for (var i = 0; i < site.company.length; i++) {
      var node = null;
      try {
        node = row.querySelector(site.company[i]);
      } catch (err) {
        node = null;
      }
      if (!node) continue;
      var name = cleanCompany(node.textContent);
      if (name) return name;
    }
    return "";
  }

  /* ---------------------------------------------------------------- chips */

  // Mine first, then one squad member, then a count of the rest. Two names is
  // as much as fits beside a job title without becoming the loudest thing on
  // the row.
  function chipText(info) {
    if (!info || !info.company_id) return "";

    var squad = [];
    if (Array.isArray(info.squad)) {
      for (var i = 0; i < info.squad.length; i++) {
        var entry = info.squad[i];
        if (entry && oneLine(clip(entry.display_name))) squad.push(entry);
      }
    }

    var parts = [];
    if (info.my_status) parts.push("You - " + statusWord(info.my_status));

    var extra = 0;
    if (squad.length) {
      parts.push(personName(squad[0].display_name) + " - " + statusWord(squad[0].status));
      extra = squad.length - 1;
    }

    // Known to the group, but nobody has a standing on it yet.
    if (!parts.length) return "Tracked";

    var text = parts.join(" · ");
    if (extra > 0) text += " +" + extra;
    return text;
  }

  // Which variant to paint, decided by the surface the chip will actually sit
  // on rather than by the OS preference. Walks up for the first ancestor with
  // a mostly-opaque background and reads its luminance. If nothing opaque is
  // found the canvas shows through, and the canvas is white unless the
  // document declares a dark color-scheme.
  function surfaceIsDark(node) {
    var el = node;
    while (el && el.nodeType === 1) {
      var bg = "";
      try {
        bg = window.getComputedStyle(el).backgroundColor || "";
      } catch (err) {
        bg = "";
      }
      var m = /^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?/i.exec(bg);
      if (m) {
        var alpha = m[4] === undefined ? 1 : parseFloat(m[4]);
        if (alpha >= 0.5) {
          var lum = (0.2126 * Number(m[1]) + 0.7152 * Number(m[2]) + 0.0722 * Number(m[3])) / 255;
          return lum < 0.5;
        }
      }
      el = el.parentElement;
    }
    var scheme = "";
    try {
      scheme = window.getComputedStyle(document.documentElement).colorScheme || "";
    } catch (err) {
      scheme = "";
    }
    return /\bdark\b/i.test(scheme) && !/\blight\b/i.test(scheme);
  }

  // Rows we have already answered for, and the host spans we put in the page.
  // Both are WeakSets: nothing about them is readable as a DOM attribute, and
  // a row the SPA throws away takes its entry with it.
  var processed = new WeakSet();
  var hostNodes = new WeakSet();

  function paint(row, info) {
    if (processed.has(row)) return;
    processed.add(row);
    if (!info) return;

    var text = chipText(info);
    if (!text) return;

    var host = document.createElement("span");
    var shadow = null;
    try {
      if (typeof host.attachShadow !== "function") return;
      shadow = host.attachShadow({ mode: "closed" });
    } catch (err) {
      shadow = null;
    }
    // Fail closed. A chip rendered straight into the page would hand the
    // page every display name and status in it, which is the exact thing the
    // shadow root is here to prevent.
    if (!shadow) return;

    var style = document.createElement("style");
    style.textContent = CHIP_CSS;

    var chip = document.createElement("span");
    chip.className = surfaceIsDark(row) ? CHIP_CLASS + " " + CHIP_CLASS + "-dark" : CHIP_CLASS;
    // textContent, never innerHTML: display names and statuses come off the
    // API and must never be parsed as markup.
    chip.textContent = text;

    shadow.appendChild(style);
    shadow.appendChild(chip);

    hostNodes.add(host);
    row.appendChild(host);
  }

  /* -------------------------------------------------------------- lookups */

  var cache = Object.create(null);
  var cacheCount = 0;
  var inflight = Object.create(null);
  // Names asked for but not answered yet. Charged against the budget as if they
  // had already landed, so a batch in flight cannot let the next scan overshoot
  // the ceiling before the first one is absorbed.
  var pending = 0;
  var failures = 0;
  var paused = false;
  var site = null;
  var timer = null;

  function budgetLeft() {
    return MAX_COMPANIES_PER_DOC - cacheCount - pending;
  }

  // The only way a name enters the cache, so the ceiling holds for the cache's
  // size as well as for the number of lookups.
  function remember(key, value) {
    if (key in cache) {
      cache[key] = value;
      return true;
    }
    if (cacheCount >= MAX_COMPANIES_PER_DOC) {
      paused = true;
      return false;
    }
    cache[key] = value;
    cacheCount += 1;
    if (cacheCount >= MAX_COMPANIES_PER_DOC) paused = true;
    return true;
  }

  function ask(names) {
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage({ type: "board-lookup", companies: names }, function (response) {
          if (chrome.runtime.lastError) {
            resolve(null);
            return;
          }
          resolve(response || null);
        });
      } catch (err) {
        // The extension was reloaded underneath this page.
        resolve(null);
      }
    });
  }

  // The API answers one-to-one, in order, and echoes each query back. Pairing
  // on the echo first means a future change to that ordering cannot silently
  // put Ali's rejection on somebody else's job.
  function absorb(names, results) {
    var byQuery = Object.create(null);
    var i;
    for (i = 0; i < results.length; i++) {
      var row = results[i];
      if (!row || typeof row !== "object") continue;
      var key = typeof row.query === "string" ? norm(clip(row.query)) : "";
      if (key && !(key in byQuery)) byQuery[key] = row;
    }
    for (i = 0; i < names.length; i++) {
      var name = norm(names[i]);
      var match = byQuery[name] || results[i] || null;
      if (!remember(name, match && match.company_id ? match : null)) return;
    }
  }

  function scan() {
    if (!site) return;

    var rows = rowNodes(site);
    var missing = [];
    var asked = Object.create(null);
    var room = budgetLeft();

    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (processed.has(row)) continue;

      // No company name yet (a skeleton row mid render). Left unprocessed on
      // purpose, so the next mutation gets another look at it.
      var name = companyFrom(row, site);
      if (!name) continue;

      var key = norm(name);
      if (key in cache) {
        paint(row, cache[key]);
        continue;
      }

      // Painting from cache above is free and stays available; asking the
      // worker for anything new does not, once we are paused.
      if (paused) continue;
      if (inflight[key] || asked[key]) continue;
      if (missing.length >= MAX_NAMES_PER_CALL) continue;
      if (missing.length >= room) {
        // The document's whole budget is spoken for. Stop, and stay stopped.
        paused = true;
        continue;
      }
      asked[key] = true;
      missing.push(name);
    }

    if (!missing.length) return;

    for (var j = 0; j < missing.length; j++) inflight[norm(missing[j])] = true;
    pending += missing.length;

    ask(missing).then(function (response) {
      for (var k = 0; k < missing.length; k++) delete inflight[norm(missing[k])];
      pending -= missing.length;

      if (!response) {
        failures += 1;
        if (failures >= MAX_FAILURES) paused = true;
        return;
      }
      if (!response.ok) {
        // Not connected, or no group chosen yet. Neither is worth retrying on
        // every mutation, and neither is worth shouting about on a page the
        // user came to for something else.
        if (response.reason === "no-group" || response.reason === "unpaired") {
          paused = true;
          return;
        }
        failures += 1;
        if (failures >= MAX_FAILURES) paused = true;
        return;
      }

      failures = 0;
      var data = response.data || {};
      var results = Array.isArray(data.results) ? data.results : [];
      absorb(missing, results);
      scan();
    });
  }

  function schedule() {
    if (paused) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      timer = null;
      scan();
    }, DEBOUNCE_MS);
  }

  // Identity, not markup: the host spans we inserted are the ones we remember
  // inserting. Nothing on the node says "jobsquad" for a page to read.
  function ourNode(node) {
    if (!node || node.nodeType !== 1) return false;
    return hostNodes.has(node);
  }

  // Our own chip insertions come back through the observer. Ignoring them
  // keeps a scan from scheduling the next scan forever.
  function pageChanged(records) {
    for (var i = 0; i < records.length; i++) {
      var record = records[i];
      if (record.removedNodes && record.removedNodes.length) return true;
      var added = record.addedNodes || [];
      for (var j = 0; j < added.length; j++) {
        if (!ourNode(added[j])) return true;
      }
    }
    return false;
  }

  function start() {
    site = siteFor(window.location.hostname);
    if (!site) return;

    scan();

    try {
      var observer = new MutationObserver(function (records) {
        if (pageChanged(records)) schedule();
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    } catch (err) {
      // No observer: the first scan still stands, the page just will not be
      // re-scanned as the user pages through results.
    }
  }

  if (!window.__jobsquadBadges) {
    window.__jobsquadBadges = true;
    start();
  }

  return {
    siteFor: siteFor,
    cleanCompany: cleanCompany,
    rowNodes: rowNodes,
    companyFrom: companyFrom,
    chipText: chipText,
    absorb: absorb,
    scan: scan,
    cache: cache,
    stats: function () {
      return { cached: cacheCount, paused: paused, ceiling: MAX_COMPANIES_PER_DOC };
    }
  };
})();
