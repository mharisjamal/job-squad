/*
 * JobSquad submit detection (Phase E3).
 *
 * Runs on Greenhouse, Lever and Workday application pages, and ONLY while the
 * user has granted those optional host permissions from the popup. The service
 * worker registers this script when the permission is granted and unregisters
 * it when it is revoked.
 *
 * What it does: notice that an application confirmation is on screen, and offer
 * to move that company to Applied in JobSquad. What it does NOT do, ever:
 *
 *   - It never writes anything on its own. The API call happens on a click, on
 *     a prompt the user can dismiss, and nowhere else.
 *   - It never reads, fills, clears or submits a form field. The only thing it
 *     reads is heading text and the URL path.
 *   - It never presses a button on the page, and it never blocks one.
 *
 * Detection is deliberately narrow: a confirmation phrase in a heading, or a
 * confirmation fragment in the URL path. A false positive costs one dismissal;
 * an automatic write would cost the user's trust in their own board, so the
 * write stays behind the click.
 *
 * The click has to be the USER's click. A content script listener also receives
 * events the page dispatched at the button, and dispatchEvent ignores the
 * disabled attribute that a real click respects, so a hostile page on one of
 * these hosts could otherwise render a fake confirmation heading, name itself
 * whatever it liked, and script this button into filing an application that the
 * whole squad then sees. Every gate against that is in userDrove() and the two
 * module level write flags below.
 *
 * The IIFE returns its internals so the jsdom test harness can exercise the
 * matcher directly. Nothing in the extension reads that value.
 */

(function jobsquadSubmitted() {
  "use strict";

  var PROMPT_CLASS = "jobsquad-prompt";
  var STYLE_ID = "jobsquad-prompt-style";
  var HEADING_LIMIT = 60;
  var HEADING_TEXT_MAX = 200;
  var NAME_MAX = 120;
  // What is shown in the prompt, as opposed to what is sent. See displayName().
  var DISPLAY_MAX = 60;
  // Cut before any normalization: see clip().
  var RAW_TEXT_MAX = 512;
  var CHECK_DEBOUNCE_MS = 400;

  // Every phrase here means the application is already in: none of them can be
  // read as an invitation to apply. "submitted your application" is included
  // and "submit your application" is not, which is the whole difference between
  // a confirmation and a button label.
  var PHRASES = [
    "application submitted",
    "application received",
    "submitted your application",
    "your application has been received",
    "your application has been submitted",
    "we have received your application",
    "we've received your application",
    "thank you for applying",
    "thanks for applying"
  ];

  // Checked against the PATH only. A query string can carry anything, and
  // "?next=/confirmation" is not a confirmation.
  var PATH_MARKERS = [
    "/thanks",
    "/thank-you",
    "/thankyou",
    "/confirmation",
    "/application_confirmation",
    "/application-submitted",
    "/application-complete"
  ];

  /* ------------------------------------------------------------------ text */

  // Everything that comes off the page passes through here BEFORE it is
  // normalized. A page can put a 20 MB text node in a heading; running a
  // full-string regex replace and a trim over that first, once per heading,
  // once per scan, is a free tab freeze. A confirmation phrase lives in the
  // first line or it is not a heading.
  function clip(value) {
    if (value === null || value === undefined) return "";
    var text = typeof value === "string" ? value : String(value);
    return text.length > RAW_TEXT_MAX ? text.slice(0, RAW_TEXT_MAX) : text;
  }

  function oneLine(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/\s+/g, " ").trim();
  }

  // Curly apostrophes are folded so one phrase covers both spellings of
  // "we've", and everything is lowercased so the match is case-insensitive.
  function normalize(value) {
    return oneLine(clip(value))
      .replace(/[‘’ʼ]/g, "'")
      .toLowerCase();
  }

  function prettifySlug(slug) {
    var value = oneLine(clip(slug).replace(/[-_+]+/g, " "));
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

  /* -------------------------------------------------------------- matching */

  function phraseHit(text) {
    var value = normalize(text);
    if (!value || value.length > HEADING_TEXT_MAX) return false;
    for (var i = 0; i < PHRASES.length; i++) {
      if (value.indexOf(PHRASES[i]) !== -1) return true;
    }
    return false;
  }

  function pathHit(pathname) {
    var value = String(pathname || "").toLowerCase();
    for (var i = 0; i < PATH_MARKERS.length; i++) {
      if (value.indexOf(PATH_MARKERS[i]) !== -1) return true;
    }
    return false;
  }

  // Headings only. Scanning the whole page body would match a footer, a privacy
  // blurb, or the confirmation copy that some boards ship hidden in the DOM
  // before you have applied at all.
  function headingHit(root) {
    var scope = root || document;
    var nodes;
    try {
      nodes = scope.querySelectorAll(
        'h1, h2, h3, h4, [role="heading"], [data-automation-id*="onfirmation"]'
      );
    } catch (err) {
      return false;
    }
    var limit = Math.min(nodes.length, HEADING_LIMIT);
    for (var i = 0; i < limit; i++) {
      if (phraseHit(nodes[i].textContent)) return true;
    }
    return false;
  }

  function submitted(root, pathname) {
    return pathHit(pathname) || headingHit(root);
  }

  /* --------------------------------------------------------------- company */

  function metaContent(name) {
    var node = null;
    try {
      node =
        document.querySelector('meta[property="' + name + '"]') ||
        document.querySelector('meta[name="' + name + '"]');
    } catch (err) {
      node = null;
    }
    return node ? oneLine(clip(node.getAttribute("content"))) : "";
  }

  function pathParts(pathname) {
    return String(pathname || "")
      .split("/")
      .filter(function (part) {
        return part.length > 0;
      });
  }

  function firstText(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var node = null;
      try {
        node = document.querySelector(selectors[i]);
      } catch (err) {
        node = null;
      }
      if (node) {
        var value = oneLine(clip(node.textContent));
        if (value) return value;
      }
    }
    return "";
  }

  var GENERIC_NAMES = [
    "boards",
    "board",
    "jobs",
    "job boards",
    "careers",
    "apply",
    "www",
    "greenhouse",
    "lever",
    "workday",
    "my workday jobs"
  ];

  // Same host rules the E1 extractor uses, kept small: the employer is in the
  // URL on all three of these boards.
  function companyGuess(host, pathname) {
    var name = String(host || "").toLowerCase();
    var parts = pathParts(pathname);
    var value = "";

    if (/(^|\.)myworkdayjobs\.com$/.test(name) || /(^|\.)myworkdaysite\.com$/.test(name)) {
      var label = name.split(".")[0];
      if (label && label !== "www") value = prettifySlug(label);
    } else if (/(^|\.)greenhouse\.io$/.test(name)) {
      value = firstText([".company-name", ".job__company"]).replace(/^at\s+/i, "");
      if (!value && parts.length && parts[0] !== "embed") value = prettifySlug(parts[0]);
    } else if (/(^|\.)lever\.co$/.test(name)) {
      if (parts.length) value = prettifySlug(parts[0]);
    }

    if (!value) value = metaContent("og:site_name");

    // "Boards", "Jobs", "Greenhouse": the applicant tracking system, not the
    // employer. Filing an application under one of those would put a company
    // in the group that nobody applied to, so we say nothing instead and let
    // the user capture it from the popup.
    value = oneLine(value);
    if (GENERIC_NAMES.indexOf(value.toLowerCase()) !== -1) value = "";
    return value.length > NAME_MAX ? value.slice(0, NAME_MAX) : value;
  }

  // The company name is chosen by the page. This prompt is a JobSquad branded
  // box pinned to the corner of that page, so a 120 character attacker written
  // "company name" in it is a phishing line, not a label. What is DISPLAYED is
  // cut to something that reads as a name; what is SENT keeps the full value,
  // which the service worker caps again at the server's limit.
  function displayName(value) {
    var text = oneLine(value);
    if (text.length > DISPLAY_MAX) text = text.slice(0, DISPLAY_MAX - 1) + ".";
    return text;
  }

  // Confirmation URLs on these boards carry one time tokens and tracking
  // parameters (gh_src, gh_jid, session ids). None of that is needed to find
  // the posting again, and all of it would be stored on an application row the
  // whole group can read. Origin and path only.
  function pageUrlWithoutQuery() {
    try {
      var origin = window.location.origin;
      var path = window.location.pathname;
      if (!origin || origin === "null") return "";
      return origin + (path || "");
    } catch (err) {
      return "";
    }
  }

  /* ------------------------------------------------------------------ trust */

  // The gate on every write. A page dispatched MouseEvent reaches this
  // listener exactly like a real one and, unlike a real one, is not stopped by
  // the disabled attribute, so isTrusted is what separates the user from the
  // page. Transient activation is checked on top of it: a trusted event should
  // always come with one, and requiring it closes the gap for any replayed or
  // synthesized event that somehow carried isTrusted.
  //
  // navigator.userActivation is not in every browser this could run in. When it
  // is missing we fall back to isTrusted alone rather than refusing every real
  // click, because a feature that never works is not a security win.
  function userDrove(event) {
    if (!event || event.isTrusted !== true) return false;
    var activation = null;
    try {
      activation = navigator ? navigator.userActivation : null;
    } catch (err) {
      activation = null;
    }
    if (!activation || typeof activation.isActive !== "boolean") return true;
    return activation.isActive === true;
  }

  /* ---------------------------------------------------------------- prompt */

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var head = document.head || document.documentElement;
    if (!head) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent =
      "." +
      PROMPT_CLASS +
      "{all:initial;position:fixed;right:16px;bottom:16px;z-index:2147483000;" +
      "width:288px;max-width:calc(100vw - 32px);padding:12px 14px;box-sizing:border-box;" +
      "border:1px solid #292b2f;border-radius:6px;background:#141618;color:#f2f3f4;" +
      'font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;' +
      "box-shadow:0 8px 24px rgba(0,0,0,.28);}" +
      "." +
      PROMPT_CLASS +
      "-title{all:initial;display:block;margin:0 0 4px;color:#f2f3f4;font:600 13px/1.4 inherit;}" +
      "." +
      PROMPT_CLASS +
      "-note{all:initial;display:block;margin:0 0 10px;color:#9ca1a8;font:11.5px/1.45 inherit;}" +
      "." +
      PROMPT_CLASS +
      "-row{all:initial;display:flex;gap:8px;align-items:center;}" +
      "." +
      PROMPT_CLASS +
      "-btn{all:initial;display:inline-block;padding:6px 10px;border:1px solid #292b2f;" +
      "border-radius:4px;background:#1c1e21;color:#f2f3f4;font:600 12px/1.2 inherit;cursor:pointer;}" +
      "." +
      PROMPT_CLASS +
      "-btn-main{border-color:#3fa875;background:#3fa875;color:#0b0c0e;}";
    head.appendChild(style);
  }

  function button(label, extraClass) {
    var node = document.createElement("button");
    node.type = "button";
    node.className = PROMPT_CLASS + "-btn" + (extraClass ? " " + extraClass : "");
    node.textContent = label;
    return node;
  }

  function send(message) {
    return new Promise(function (resolve) {
      try {
        chrome.runtime.sendMessage(message, function (response) {
          if (chrome.runtime.lastError) {
            resolve({ ok: false, error: "The JobSquad extension is not responding." });
            return;
          }
          resolve(response || { ok: false, error: "No response from the extension." });
        });
      } catch (err) {
        resolve({ ok: false, error: "The JobSquad extension is not responding." });
      }
    });
  }

  var shown = false;
  var dismissed = false;
  // One capture in flight at a time, so a burst of clicks cannot stack writes.
  var writing = false;
  // One successful write per document, ever. A page can reload itself, which
  // resets shown/dismissed, but within a single document this can only land
  // once no matter how the prompt is driven.
  var written = false;

  function showPrompt(company, postingUrl) {
    if (shown || dismissed || written) return null;
    if (!document.body) return null;
    shown = true;
    ensureStyle();

    var box = document.createElement("div");
    box.className = PROMPT_CLASS;
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "JobSquad");

    var title = document.createElement("span");
    title.className = PROMPT_CLASS + "-title";
    // textContent: the company name came off this page and is never markup.
    title.textContent = "Mark " + displayName(company) + " as applied in JobSquad?";

    var note = document.createElement("span");
    note.className = PROMPT_CLASS + "-note";
    note.textContent = "Looks like you just submitted. Nothing is saved unless you choose to.";

    var row = document.createElement("div");
    row.className = PROMPT_CLASS + "-row";
    var yes = button("Mark as applied", PROMPT_CLASS + "-btn-main");
    var no = button("Not now");
    row.appendChild(yes);
    row.appendChild(no);

    box.appendChild(title);
    box.appendChild(note);
    box.appendChild(row);

    function remove() {
      if (box.parentNode) box.parentNode.removeChild(box);
    }

    function onDismiss(event) {
      if (!userDrove(event)) return;
      dismissed = true;
      remove();
    }

    function onConfirm(event) {
      // The three gates, in order of what they stop: a scripted event, a
      // second click landing on top of the first, and a second write from a
      // document that already produced one.
      if (!userDrove(event)) return;
      if (writing || written) return;
      writing = true;

      yes.disabled = true;
      no.disabled = true;
      yes.textContent = "Saving";
      send({
        type: "board-capture",
        company_name: company,
        posting_url: postingUrl
      }).then(function (result) {
        writing = false;
        if (result && result.ok) {
          written = true;
          var data = result.data || {};
          var saved = oneLine(data.company_name) || company;
          title.textContent = "Marked " + displayName(saved) + " as applied.";
          note.textContent = "";
          // The board may have re-rendered this subtree out from under us
          // between the click and the reply, and removeChild on a detached
          // node is a TypeError that would take the confirmation down with it.
          if (row.parentNode) row.parentNode.removeChild(row);
          setTimeout(remove, 2400);
          return;
        }
        yes.disabled = false;
        no.disabled = false;
        yes.textContent = "Try again";
        note.textContent =
          (result && result.error) || "Could not save that. Open the JobSquad popup instead.";
      });
    }

    no.addEventListener("click", onDismiss);
    yes.addEventListener("click", onConfirm);

    document.body.appendChild(box);
    // The handlers travel with the node for the jsdom harness, which cannot
    // produce a trusted event through the DOM at all. Nothing in the extension
    // reads this, and a page cannot reach it: the return value stays in the
    // content script's own world.
    return { node: box, confirm: onConfirm, dismiss: onDismiss };
  }

  /* ------------------------------------------------------------------- run */

  function check() {
    if (shown || dismissed || written) return;
    var pathname = window.location.pathname;
    if (!submitted(document, pathname)) return;

    var company = companyGuess(window.location.hostname, pathname);
    if (!company) return;

    // A confirmation URL is a bad posting URL, and capture overwrites the one
    // already saved. So the page URL travels only when the confirmation came
    // from the heading of the posting page itself, and even then without its
    // query string.
    var postingUrl = pathHit(pathname) ? "" : pageUrlWithoutQuery();
    showPrompt(company, postingUrl);
  }

  function start() {
    var timer = null;
    check();

    try {
      var observer = new MutationObserver(function () {
        if (shown || dismissed) {
          observer.disconnect();
          return;
        }
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () {
          timer = null;
          check();
          if (shown) observer.disconnect();
        }, CHECK_DEBOUNCE_MS);
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    } catch (err) {
      // No observer: a confirmation rendered after this point is simply missed,
      // which is the right way for this feature to fail.
    }
  }

  if (!window.__jobsquadSubmitted) {
    window.__jobsquadSubmitted = true;
    start();
  }

  return {
    phraseHit: phraseHit,
    pathHit: pathHit,
    headingHit: headingHit,
    submitted: submitted,
    companyGuess: companyGuess,
    displayName: displayName,
    userDrove: userDrove,
    pageUrlWithoutQuery: pageUrlWithoutQuery,
    showPrompt: showPrompt,
    state: function () {
      return { shown: shown, dismissed: dismissed, writing: writing, written: written };
    }
  };
})();
