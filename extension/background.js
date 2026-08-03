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
 * call. That keeps the blast radius small when E2 adds content scripts to job
 * board pages.
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
  { method: "POST", path: "/api/capture/lookup" }
];

const MENU_ID = "jobsquad-save-job";
const PENDING_TTL_MS = 5 * 60 * 1000;
const TAB_LOAD_TIMEOUT_MS = 8000;

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

async function setPending(prefill) {
  await storageSet({
    [KEY_PENDING]: { fields: prefill, saved_at: Date.now() }
  });
}

async function takePending() {
  const items = await storageGet([KEY_PENDING]);
  const entry = items[KEY_PENDING];
  await storageRemove([KEY_PENDING]);
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.saved_at !== "number") return null;
  if (Date.now() - entry.saved_at > PENDING_TTL_MS) return null;
  return entry.fields && typeof entry.fields === "object" ? entry.fields : null;
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

function waitForTabLoad(tabId) {
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      try {
        chrome.tabs.onUpdated.removeListener(onUpdated);
      } catch (err) {
        // The listener was already gone.
      }
      resolve();
    };
    const onUpdated = (updatedId, changeInfo) => {
      if (updatedId === tabId && changeInfo && changeInfo.status === "complete") done();
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    setTimeout(done, TAB_LOAD_TIMEOUT_MS);
  });
}

chrome.runtime.onInstalled.addListener(() => {
  createMenu();
});

chrome.runtime.onStartup.addListener(() => {
  createMenu();
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!info || info.menuItemId !== MENU_ID) return;

  const linkUrl = typeof info.linkUrl === "string" ? info.linkUrl : "";
  const isForeignLink = linkUrl && linkUrl !== info.pageUrl && /^https?:/i.test(linkUrl);

  if (!isForeignLink) {
    // Page context: the popup reads the tab the user invoked us on.
    openCapturePopup(tab && typeof tab.id === "number" ? tab.id : undefined);
    return;
  }

  // Link context: open the posting so the user can see what they are saving,
  // and carry the link through as a prefill in case on-demand extraction is
  // not available on that tab yet.
  const prefill = { posting_url: linkUrl };
  const selection = typeof info.selectionText === "string" ? info.selectionText.trim() : "";
  if (selection) prefill.job_title = selection;

  setPending(prefill)
    .then(() => chrome.tabs.create({ url: linkUrl, active: true }))
    .then((created) => {
      const newId = created && typeof created.id === "number" ? created.id : undefined;
      if (newId === undefined) return openCapturePopup(undefined);
      return waitForTabLoad(newId).then(() => openCapturePopup(newId));
    })
    .catch(() => {
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

async function handlePair(message) {
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

async function handleMessage(message) {
  const type = message && message.type;

  if (type === "pair") {
    // Sent by content/connect.js after it has validated the page message.
    return handlePair(message);
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
    const fields = await takePending();
    return { ok: true, fields: fields };
  }

  if (type === "api") {
    const result = await apiRequest(message);
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

  handleMessage(message)
    .then((result) => sendResponse(result))
    .catch(() => sendResponse({ ok: false, error: "The extension hit an unexpected error." }));
  return true;
});
