/*
 * JobSquad service worker.
 *
 * Owns three things:
 *   1. Local state: the paired extension token, its server side id, the API
 *      base, and the last used group.
 *   2. Entry points: the toolbar action, the Ctrl+Shift+J command, the context
 *      menu.
 *   3. Every call to the JobSquad API, so the popup never touches the token.
 *
 * The token is written to chrome.storage.local and read back only to build an
 * Authorization header. It is never logged, never put in a URL, and never sent
 * back to a page.
 *
 * Security posture of the message channel: this worker holds the user's token,
 * so the message handler is deliberately NOT a general purpose proxy. Every
 * request must come from this extension's own id, and the method plus path must
 * appear in API_ALLOWLIST. Anything else is refused here, without a network
 * call. That keeps the blast radius small now that E2 and E3 put content
 * scripts on job board pages.
 *
 * Those board scripts get their own narrow message types (board-lookup,
 * board-capture) with fixed paths and a body this worker builds itself. The
 * general "api" passthrough is refused unless the sender is an extension page,
 * so a bug in a script running on linkedin.com can never widen into "call any
 * allowlisted endpoint with any body".
 */

"use strict";

const DEFAULT_API_BASE = "https://jobsquad.dpdns.org";
const LOCAL_API_BASE = "http://localhost:8100";
const ALLOWED_API_BASES = [DEFAULT_API_BASE, LOCAL_API_BASE];

// The complete set of calls the extension makes. Exact matches only: no path
// parameters, no query strings, no caller supplied URLs.
const API_ALLOWLIST = [
  { method: "GET", path: "/api/groups" },
  { method: "POST", path: "/api/capture" },
  { method: "POST", path: "/api/capture/lookup" },
  { method: "POST", path: "/api/capture/lookup/batch" }
];

// Opt-in job board features (E2, E3). Neither origin set is in the install time
// manifest: they live in optional_host_permissions and are requested from the
// popup, by the user, one feature at a time. While a permission is held the
// matching content script is registered dynamically; when it is revoked the
// registration goes with it.
// LinkedIn is narrowed to /jobs/*. The feed, messaging, notifications and every
// profile page are not job results, and a script that has no business there
// should not be able to read them: the origin is what Chrome grants, so the
// smallest one that still does the job is the one to ask for.
const BOARD_FEATURES = [
  {
    key: "badges",
    script_id: "jobsquad-badges",
    origins: ["https://*.linkedin.com/jobs/*", "https://*.indeed.com/*"],
    js: ["content/badges.js"]
  },
  {
    key: "submitted",
    script_id: "jobsquad-submitted",
    origins: [
      "https://*.greenhouse.io/*",
      "https://*.lever.co/*",
      "https://*.myworkdayjobs.com/*"
    ],
    js: ["content/submitted.js"]
  }
];

// Mirrors the server side caps (LOOKUP_BATCH_MAX, NAME_MAX) so an oversized
// scan is trimmed here rather than coming back as a 422.
const LOOKUP_BATCH_MAX = 50;
const NAME_MAX = 120;
const URL_MAX = 2000;

const MENU_ID = "jobsquad-save-job";
const PENDING_TTL_MS = 5 * 60 * 1000;

const KEY_TOKEN = "token";
const KEY_TOKEN_ID = "token_id";
const KEY_API_BASE = "api_base";
const KEY_LAST_GROUP = "last_group_id";
const KEY_PENDING = "pending_capture";

/* ------------------------------------------------------------------ state */

function storageGet(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.get(keys, (items) => {
      if (chrome.runtime.lastError) {
        resolve({});
        return;
      }
      resolve(items || {});
    });
  });
}

function storageSet(items) {
  return new Promise((resolve) => {
    chrome.storage.local.set(items, () => {
      // lastError is read so Chrome does not log an unchecked error.
      const failed = chrome.runtime.lastError;
      resolve(!failed);
    });
  });
}

function storageRemove(keys) {
  return new Promise((resolve) => {
    chrome.storage.local.remove(keys, () => {
      const failed = chrome.runtime.lastError;
      resolve(!failed);
    });
  });
}

function normalizeApiBase(value) {
  const raw = typeof value === "string" ? value.trim().replace(/\/+$/, "") : "";
  if (!raw) return DEFAULT_API_BASE;
  if (ALLOWED_API_BASES.indexOf(raw) !== -1) return raw;
  // Anything outside the two declared host_permissions cannot be reached by
  // fetch anyway, so fall back rather than store an unusable base.
  return DEFAULT_API_BASE;
}

async function readState() {
  const items = await storageGet([KEY_TOKEN, KEY_TOKEN_ID, KEY_API_BASE, KEY_LAST_GROUP]);
  const token = typeof items[KEY_TOKEN] === "string" ? items[KEY_TOKEN] : "";
  return {
    paired: token.length > 0,
    token: token,
    token_id: items[KEY_TOKEN_ID] === undefined ? null : items[KEY_TOKEN_ID],
    api_base: normalizeApiBase(items[KEY_API_BASE]),
    last_group_id: typeof items[KEY_LAST_GROUP] === "number" ? items[KEY_LAST_GROUP] : null
  };
}

// A token belongs to the deployment that minted it, and so does every group id
// cached beside it. Switching servers therefore drops both, rather than risk a
// production token being sent to localhost over plaintext http.
async function clearPairing() {
  await storageRemove([KEY_TOKEN, KEY_TOKEN_ID, KEY_LAST_GROUP]);
}

/* -------------------------------------------------------------------- api */

function isAllowedCall(method, path) {
  for (let i = 0; i < API_ALLOWLIST.length; i++) {
    if (API_ALLOWLIST[i].method === method && API_ALLOWLIST[i].path === path) return true;
  }
  return false;
}

function detailToMessage(payload, status) {
  if (payload && typeof payload === "object") {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item.msg === "string") return item.msg;
          return "";
        })
        .filter(Boolean);
      if (parts.length) return parts.join(". ");
    }
    if (typeof payload.message === "string" && payload.message.trim()) {
      return payload.message.trim();
    }
  }
  if (status === 401) return "Your connection expired. Connect again.";
  if (status === 403) return "You do not have access to that.";
  if (status === 404) return "Not found.";
  if (status >= 500) return "JobSquad had a server error. Try again in a moment.";
  return "Request failed (" + status + ").";
}

async function apiRequest(request) {
  const method = typeof request.method === "string" ? request.method.toUpperCase() : "GET";
  const path = typeof request.path === "string" ? request.path : "";

  if (!isAllowedCall(method, path)) {
    // Refused locally: no token is attached and nothing leaves the browser.
    return { ok: false, status: 0, error: "That request is not allowed by the extension." };
  }

  const state = await readState();
  if (!state.paired) {
    return { ok: false, status: 401, error: "Connect to JobSquad first." };
  }

  const init = {
    method: method,
    headers: { Authorization: "Bearer " + state.token, Accept: "application/json" },
    credentials: "omit",
    cache: "no-store"
  };
  if (request.body !== undefined && request.body !== null) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(request.body);
  }

  let response;
  try {
    response = await fetch(state.api_base + path, init);
  } catch (err) {
    return {
      ok: false,
      status: 0,
      error: "Cannot reach JobSquad at " + state.api_base + ". Check that it is running."
    };
  }

  let payload = null;
  const text = await response.text().catch(() => "");
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (err) {
      payload = null;
    }
  }

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      error: detailToMessage(payload, response.status)
    };
  }
  return { ok: true, status: response.status, data: payload };
}

/* --------------------------------------------------------- board features */

// The live answer, from Chrome, not from anything this extension stored. A
// permission can be revoked from chrome://extensions at any time, so a
// remembered "on" would be a lie the popup then tells the user.
function hasOrigins(origins) {
  return new Promise((resolve) => {
    try {
      chrome.permissions.contains({ origins: origins }, (granted) => {
        if (chrome.runtime.lastError) {
          resolve(false);
          return;
        }
        resolve(Boolean(granted));
      });
    } catch (err) {
      resolve(false);
    }
  });
}

function registeredScriptIds() {
  return new Promise((resolve) => {
    try {
      chrome.scripting.getRegisteredContentScripts((scripts) => {
        if (chrome.runtime.lastError || !Array.isArray(scripts)) {
          resolve([]);
          return;
        }
        resolve(
          scripts
            .map((entry) => (entry && typeof entry.id === "string" ? entry.id : ""))
            .filter(Boolean)
        );
      });
    } catch (err) {
      resolve([]);
    }
  });
}

function registerBoardScript(feature) {
  return new Promise((resolve) => {
    try {
      chrome.scripting.registerContentScripts(
        [
          {
            id: feature.script_id,
            matches: feature.origins.slice(),
            js: feature.js.slice(),
            runAt: "document_idle",
            allFrames: false,
            persistAcrossSessions: true
          }
        ],
        () => {
          resolve(!chrome.runtime.lastError);
        }
      );
    } catch (err) {
      resolve(false);
    }
  });
}

function unregisterBoardScript(scriptId) {
  return new Promise((resolve) => {
    try {
      chrome.scripting.unregisterContentScripts({ ids: [scriptId] }, () => {
        resolve(!chrome.runtime.lastError);
      });
    } catch (err) {
      resolve(false);
    }
  });
}

function tabsMatching(patterns) {
  return new Promise((resolve) => {
    try {
      chrome.tabs.query({ url: patterns.slice() }, (tabs) => {
        if (chrome.runtime.lastError || !Array.isArray(tabs)) {
          resolve([]);
          return;
        }
        resolve(tabs);
      });
    } catch (err) {
      resolve([]);
    }
  });
}

// registerContentScripts only covers documents created AFTER it returns, so a
// freshly granted feature used to do nothing at all until the user reloaded the
// tab they were standing on, which reads as "the toggle is broken". Injecting
// into the tabs the permission now covers closes that gap. Both board scripts
// no-op on a second injection (window.__jobsquad* guard), so a tab that also
// gets the registered copy is not double-run. Failures are silent by design:
// a tab that closed mid call, or one Chrome will not inject into, is not
// something to interrupt the user about.
async function injectIntoOpenTabs(feature) {
  const tabs = await tabsMatching(feature.origins);
  for (let i = 0; i < tabs.length; i++) {
    const tabId = tabs[i] && typeof tabs[i].id === "number" ? tabs[i].id : null;
    if (tabId === null) continue;
    await new Promise((resolve) => {
      try {
        chrome.scripting.executeScript(
          { target: { tabId: tabId }, files: feature.js.slice() },
          () => {
            const failed = chrome.runtime.lastError;
            resolve(!failed);
          }
        );
      } catch (err) {
        resolve(false);
      }
    });
  }
}

// Single source of truth: whatever Chrome says about the permission decides
// whether the script is registered. Called on install, on startup, whenever a
// permission changes, and whenever the popup asks, so the two can never drift
// apart (a revoke from chrome://extensions unregisters on the next look).
async function syncBoardScripts() {
  const ids = await registeredScriptIds();
  const out = {};
  for (let i = 0; i < BOARD_FEATURES.length; i++) {
    const feature = BOARD_FEATURES[i];
    const granted = await hasOrigins(feature.origins);
    const registered = ids.indexOf(feature.script_id) !== -1;

    // What the popup is told is whether the feature is actually LIVE, not
    // whether the permission exists. A registration that failed used to be
    // reported as "on", which is the popup confidently describing a feature
    // that is not running.
    let live = granted && registered;
    if (granted && !registered) {
      live = await registerBoardScript(feature);
      if (live) await injectIntoOpenTabs(feature);
    }
    if (!granted && registered) await unregisterBoardScript(feature.script_id);
    out[feature.key] = live;
  }
  return out;
}

/* ------------------------------------------------------------ entry points */

function createMenu() {
  chrome.contextMenus.removeAll(() => {
    const failed = chrome.runtime.lastError;
    if (failed) {
      // Nothing to remove is not an error worth surfacing.
    }
    chrome.contextMenus.create(
      {
        id: MENU_ID,
        title: "Save this job to JobSquad",
        contexts: ["page", "link"]
      },
      () => {
        const createFailed = chrome.runtime.lastError;
        if (createFailed) {
          console.warn("JobSquad: could not create the context menu.");
        }
      }
    );
  });
}

async function setPending(prefill, linkOnly) {
  await storageSet({
    [KEY_PENDING]: {
      fields: prefill,
      link_only: Boolean(linkOnly),
      saved_at: Date.now()
    }
  });
}

// link_only travels with the prefill so the popup knows this capture came from
// a right-clicked link and must not present page-scraped fields as if they
// described that link.
async function takePending() {
  const items = await storageGet([KEY_PENDING]);
  const entry = items[KEY_PENDING];
  await storageRemove([KEY_PENDING]);
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.saved_at !== "number") return null;
  if (Date.now() - entry.saved_at > PENDING_TTL_MS) return null;
  if (!entry.fields || typeof entry.fields !== "object") return null;
  return { fields: entry.fields, link_only: Boolean(entry.link_only) };
}

async function openCapturePopup(tabId) {
  if (chrome.action && typeof chrome.action.openPopup === "function") {
    try {
      await chrome.action.openPopup();
      return;
    } catch (err) {
      // Older Chrome, or no focused window. Fall through to a detached window.
    }
  }
  let url = chrome.runtime.getURL("popup/popup.html");
  if (typeof tabId === "number") url += "?tabId=" + tabId;
  try {
    await chrome.windows.create({ url: url, type: "popup", width: 400, height: 640 });
  } catch (err) {
    console.warn("JobSquad: could not open the capture window.");
  }
}

// The sync is returned, not fired and forgotten, so the worker is kept alive
// until the reconciliation it just started has finished. A service worker that
// is torn down mid-await leaves the registration in whatever state it was in.
chrome.runtime.onInstalled.addListener(() => {
  createMenu();
  return syncBoardScripts();
});

chrome.runtime.onStartup.addListener(() => {
  createMenu();
  return syncBoardScripts();
});

// A permission can also be granted or revoked from chrome://extensions, with
// this worker asleep. Reconciling on the event keeps the registration honest
// without the popup having to be open.
if (chrome.permissions && chrome.permissions.onAdded) {
  chrome.permissions.onAdded.addListener(() => {
    return syncBoardScripts();
  });
}
if (chrome.permissions && chrome.permissions.onRemoved) {
  chrome.permissions.onRemoved.addListener(() => {
    return syncBoardScripts();
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!info || info.menuItemId !== MENU_ID) return;

  const linkUrl = typeof info.linkUrl === "string" ? info.linkUrl : "";
  const isForeignLink = linkUrl && linkUrl !== info.pageUrl && /^https?:/i.test(linkUrl);

  if (!isForeignLink) {
    // Page context: the popup reads the tab the user invoked us on.
    openCapturePopup(tab && typeof tab.id === "number" ? tab.id : undefined);
    return;
  }

  // Link context: the LINK is all we read. activeTab does not extend to a tab
  // the extension opened, so opening the posting and scraping it was never
  // going to work; pretending otherwise would fill the card with fields taken
  // from whatever page the user right-clicked ON. So the URL is prefilled, the
  // popup says plainly that only the link was read, and it points at
  // Ctrl+Shift+J on the posting itself for the full details.
  const prefill = { posting_url: linkUrl };
  const selection = typeof info.selectionText === "string" ? info.selectionText.trim() : "";
  if (selection) prefill.job_title = selection;

  setPending(prefill, true).finally(() => {
    openCapturePopup(undefined);
  });
});

chrome.commands.onCommand.addListener((command) => {
  if (command !== "capture-job") return;
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const failed = chrome.runtime.lastError;
    const tab = !failed && tabs && tabs.length ? tabs[0] : null;
    openCapturePopup(tab && typeof tab.id === "number" ? tab.id : undefined);
  });
});

/* --------------------------------------------------------------- messages */

function normalizeTokenId(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && /^\d+$/.test(value.trim())) return Number(value.trim());
  return null;
}

// The one message that WRITES the token, so it is the one that most needs to
// know who is asking. Only a page on a JobSquad deployment can mint a pairing:
// content/connect.js is match-limited to {app}/connect, but the manifest match
// is not what is enforced here, the sender's own origin is. Without this, any
// content script this extension runs could hand the worker a token of its
// choosing and point the extension at an attacker's session.
async function handlePair(message, sender) {
  if (ALLOWED_API_BASES.indexOf(senderOrigin(sender)) === -1) {
    return Object.assign({}, REFUSED);
  }

  const token = typeof message.token === "string" ? message.token.trim() : "";
  if (!token) return { ok: false, error: "The pairing message had no token." };

  const apiBase = normalizeApiBase(message.api_base);
  const previous = await readState();

  // Only report a previous token when the SAME deployment minted it. Ids are
  // per server, so handing a production id to a localhost page would revoke an
  // unrelated token there.
  let previousTokenId = null;
  if (previous.paired && previous.api_base === apiBase) {
    previousTokenId = normalizeTokenId(previous.token_id);
  } else if (previous.paired) {
    await storageRemove([KEY_LAST_GROUP]);
  }

  const stored = await storageSet({
    [KEY_TOKEN]: token,
    [KEY_TOKEN_ID]: normalizeTokenId(message.token_id),
    [KEY_API_BASE]: apiBase
  });
  if (!stored) return { ok: false, error: "The extension could not store the connection." };

  return { ok: true, previous_token_id: previousTokenId };
}

/* ------------------------------------------------------------ sender rules */

// Where a message actually came from. Content scripts report the page they run
// on; extension pages report the extension origin. Both are set by Chrome, not
// by the message, so neither can be spoofed by what is inside it.
function senderUrl(sender) {
  if (!sender) return "";
  if (typeof sender.url === "string" && sender.url) return sender.url;
  // No url (an older Chrome, or a sender without a document). An origin alone
  // still lets an origin-only rule answer.
  if (typeof sender.origin === "string" && sender.origin) return sender.origin + "/";
  return "";
}

function senderOrigin(sender) {
  if (!sender) return "";
  if (typeof sender.origin === "string" && sender.origin) {
    return sender.origin.replace(/\/+$/, "");
  }
  const url = typeof sender.url === "string" ? sender.url : "";
  if (!url) return "";
  try {
    return new URL(url).origin;
  } catch (err) {
    return "";
  }
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Chrome match pattern to RegExp, for the "https://*.host.tld/path*" shape this
// extension declares and nothing else. A pattern that does not parse returns
// null and therefore matches nothing: a typo must fail closed, never open.
function patternToRegExp(pattern) {
  const parts = /^(https?):\/\/(\*\.)?([a-z0-9.-]+)(\/.*)$/i.exec(String(pattern || ""));
  if (!parts) return null;
  // "*.linkedin.com" covers linkedin.com and any subdomain of it, which is what
  // Chrome means by it too.
  const host = (parts[2] ? "(?:[a-z0-9-]+\\.)*" : "") + escapeRegex(parts[3]);
  const path = escapeRegex(parts[4]).replace(/\\\*/g, "[^]*");
  return new RegExp("^" + parts[1] + "://" + host + path + "$", "i");
}

function urlMatchesAny(url, patterns) {
  if (typeof url !== "string" || !url) return false;
  for (let i = 0; i < patterns.length; i++) {
    const re = patternToRegExp(patterns[i]);
    if (re && re.test(url)) return true;
  }
  return false;
}

// The gate on both board message types. Two independent questions, and a "no"
// to either one is a refusal:
//
//   1. Is this sender one of the pages this feature is for? Every content
//      script in this extension shares one message channel and one extension
//      id, so without this check extract.js, which activeTab injects into
//      WHATEVER page the user invoked capture on, could send board messages
//      from any site on the web.
//   2. Does the user still hold the permission, right now? Asked of Chrome
//      every time, because unregisterContentScripts does NOT kill instances
//      already running in open tabs. Turning a feature off leaves those tabs
//      running until they navigate, and they would otherwise keep sending
//      company names to the API while the popup says "Off".
async function boardSenderAllowed(feature, sender) {
  if (!feature) return false;
  if (!urlMatchesAny(senderUrl(sender), feature.origins)) return false;
  return hasOrigins(feature.origins);
}

function featureByKey(key) {
  for (let i = 0; i < BOARD_FEATURES.length; i++) {
    if (BOARD_FEATURES[i].key === key) return BOARD_FEATURES[i];
  }
  return null;
}

const REFUSED = { ok: false, status: 0, error: "That request is not allowed by the extension." };

/* --------------------------------------------------------- board messages */

function cappedText(value, limit) {
  const text = typeof value === "string" ? value.trim() : "";
  return text.length > limit ? text.slice(0, limit) : text;
}

// The board scripts read company names off a page they do not control, so the
// list is normalized here: blanks dropped, each name capped at the server's
// NAME_MAX, duplicates folded case-insensitively, and the whole thing cut to
// one page's worth. What reaches the API is always a valid body.
function cleanCompanyList(value) {
  const out = [];
  if (!Array.isArray(value)) return out;
  const seen = Object.create(null);
  for (let i = 0; i < value.length && out.length < LOOKUP_BATCH_MAX; i++) {
    const name = cappedText(value[i], NAME_MAX);
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen[key]) continue;
    seen[key] = true;
    out.push(name);
  }
  return out;
}

async function groupScopedState() {
  const state = await readState();
  if (!state.paired) {
    return { error: { ok: false, status: 401, reason: "unpaired", error: "Connect to JobSquad first." } };
  }
  if (state.last_group_id === null) {
    return {
      error: {
        ok: false,
        status: 0,
        reason: "no-group",
        error: "Open the JobSquad popup once and pick a group first."
      }
    };
  }
  return { group_id: state.last_group_id };
}

async function handleBoardLookup(message, sender) {
  if (!(await boardSenderAllowed(featureByKey("badges"), sender))) {
    return Object.assign({}, REFUSED);
  }

  const companies = cleanCompanyList(message && message.companies);
  if (!companies.length) return { ok: true, status: 200, data: { results: [] } };

  const scope = await groupScopedState();
  if (scope.error) return scope.error;

  return apiRequest({
    method: "POST",
    path: "/api/capture/lookup/batch",
    body: { group_id: scope.group_id, companies: companies }
  });
}

// E3's only write. The body is assembled here, not accepted from the page: the
// status is hardcoded to "applied", the group comes from storage, and there is
// no path by which a board script can send a job description or any other
// field into the group.
async function handleBoardCapture(message, sender) {
  if (!(await boardSenderAllowed(featureByKey("submitted"), sender))) {
    return Object.assign({}, REFUSED);
  }

  const company = cappedText(message && message.company_name, NAME_MAX);
  if (!company) return { ok: false, status: 0, error: "No company name to save." };

  const scope = await groupScopedState();
  if (scope.error) return scope.error;

  const body = {
    group_id: scope.group_id,
    company_name: company,
    status: "applied"
  };
  const url = cappedText(message && message.posting_url, URL_MAX);
  if (/^https?:\/\//i.test(url)) body.posting_url = url;
  const title = cappedText(message && message.job_title, NAME_MAX);
  if (title) body.job_title = title;

  return apiRequest({ method: "POST", path: "/api/capture", body: body });
}

/* ---------------------------------------------------------------- routing */

const EXTENSION_ORIGIN = chrome.runtime.getURL("").replace(/\/+$/, "");

// True only for this extension's own pages (the popup). Content scripts always
// report the page they run on, so this is what keeps the general API
// passthrough out of reach of a script running on a job board.
function fromExtensionPage(sender) {
  if (!sender) return false;
  if (typeof sender.origin === "string" && sender.origin === EXTENSION_ORIGIN) return true;
  const url = typeof sender.url === "string" ? sender.url : "";
  return url.indexOf(EXTENSION_ORIGIN + "/") === 0;
}

async function handleMessage(message, sender) {
  const type = message && message.type;

  if (type === "pair") {
    // Sent by content/connect.js after it has validated the page message.
    return handlePair(message, sender);
  }

  if (type === "get-state") {
    const state = await readState();
    return {
      ok: true,
      paired: state.paired,
      api_base: state.api_base,
      last_group_id: state.last_group_id,
      default_api_base: DEFAULT_API_BASE,
      local_api_base: LOCAL_API_BASE
    };
  }

  if (type === "set-api-base") {
    const apiBase = normalizeApiBase(message.api_base);
    const current = await readState();
    const changed = current.api_base !== apiBase;
    if (changed) await clearPairing();
    await storageSet({ [KEY_API_BASE]: apiBase });
    return { ok: true, api_base: apiBase, cleared: changed && current.paired };
  }

  if (type === "set-last-group") {
    const groupId = Number(message.group_id);
    if (Number.isFinite(groupId)) await storageSet({ [KEY_LAST_GROUP]: groupId });
    return { ok: true };
  }

  if (type === "unpair") {
    await clearPairing();
    return { ok: true };
  }

  if (type === "take-pending") {
    const pending = await takePending();
    return {
      ok: true,
      fields: pending ? pending.fields : null,
      link_only: pending ? pending.link_only : false
    };
  }

  if (type === "board-features") {
    // Also repairs any drift between the permission and the registration.
    const features = await syncBoardScripts();
    return { ok: true, features: features };
  }

  if (type === "api" || type === "board-lookup" || type === "board-capture") {
    if (type === "api" && !fromExtensionPage(sender)) {
      return Object.assign({}, REFUSED);
    }
    let result;
    if (type === "board-lookup") {
      result = await handleBoardLookup(message, sender);
    } else if (type === "board-capture") {
      result = await handleBoardCapture(message, sender);
    } else {
      result = await apiRequest(message);
    }
    if (!result.ok && result.status === 401) {
      // A rejected token is a dead token. Drop it so the popup can re-pair.
      await clearPairing();
    }
    return result;
  }

  return { ok: false, error: "Unknown request." };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only this extension's own popup and content scripts may talk to the worker.
  // Anything else is refused before the message is even inspected.
  if (!sender || sender.id !== chrome.runtime.id) {
    sendResponse({ ok: false, status: 0, error: "Rejected." });
    return false;
  }

  handleMessage(message, sender)
    .then((result) => sendResponse(result))
    .catch(() => sendResponse({ ok: false, error: "The extension hit an unexpected error." }));
  return true;
});
