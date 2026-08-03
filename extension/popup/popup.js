/*
 * JobSquad capture popup.
 *
 * States:
 *   loading   reading the page and loading groups
 *   unpaired  explainer, Connect button, server switch
 *   capture   editable extracted fields, group picker, status, Save
 *   done      confirmation, then the popup closes itself
 *   expired   a 401 came back, so the token is gone and pairing must repeat
 *
 * Nothing is ever saved without the user pressing Save.
 */

"use strict";

var STATUSES = [
  ["saved", "Saved"],
  ["applied", "Applied"],
  ["assessment", "Assessment"],
  ["interview", "Interview"],
  ["offer", "Offer"],
  ["rejected", "Rejected"],
  ["ghosted", "Ghosted"]
];

var STATUS_COLORS = {
  saved: "#A9B0BA",
  applied: "#79A6F6",
  assessment: "#A98BF0",
  interview: "#E0A458",
  offer: "#5FBF8C",
  rejected: "#EC8080",
  ghosted: "#8E9199"
};

var SEP = " · ";
var DEFAULT_API_BASE = "https://jobsquad.dpdns.org";

// Mirrors the server side field limits (NAME_MAX, URL_MAX, JD_TEXT_MAX), so an
// over long scrape is trimmed here instead of coming back as a 422.
var LIMIT_NAME = 120;
var LIMIT_URL = 2000;
var LIMIT_JD = 50000;

function capped(value, limit) {
  var text = (value || "").trim();
  return text.length > limit ? text.slice(0, limit) : text;
}

var state = {
  apiBase: DEFAULT_API_BASE,
  lastGroupId: null,
  jdText: "",
  // Which extraction stage produced jdText: "jsonld", "site", "generic", "".
  jdSource: "",
  lookupSeq: 0
};

// A description only counts as a real job posting when JSON-LD or a site rule
// produced it. The generic fallback reads the main text block of whatever page
// is open, which may be an internal wiki, a webmail thread, or a private ATS
// screen, so that text stays out unless the user opts in.
function jdTrusted(source) {
  return source === "jsonld" || source === "site";
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test((value || "").trim());
}

/* ----------------------------------------------------------------- utils */

function $(id) {
  return document.getElementById(id);
}

function send(message) {
  return new Promise(function (resolve) {
    try {
      chrome.runtime.sendMessage(message, function (response) {
        if (chrome.runtime.lastError) {
          resolve({
            ok: false,
            status: 0,
            error: "The JobSquad background service is not responding. Reload the extension."
          });
          return;
        }
        resolve(response || { ok: false, status: 0, error: "No response from the extension." });
      });
    } catch (err) {
      resolve({ ok: false, status: 0, error: "The extension could not send that request." });
    }
  });
}

function api(method, path, options) {
  var request = { type: "api", method: method, path: path };
  if (options && options.query) request.query = options.query;
  if (options && options.body) request.body = options.body;
  return send(request);
}

function show(viewId) {
  ["view-loading", "view-unpaired", "view-capture", "view-done", "view-expired"].forEach(function (id) {
    var node = $(id);
    if (node) node.hidden = id !== viewId;
  });
}

function setText(id, text) {
  var node = $(id);
  if (node) node.textContent = text;
}

function setMessage(id, text) {
  var node = $(id);
  if (!node) return;
  node.textContent = text || "";
  node.hidden = !text;
}

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch (err) {
    return url;
  }
}

function statusLabel(value) {
  for (var i = 0; i < STATUSES.length; i++) {
    if (STATUSES[i][0] === value) return STATUSES[i][1];
  }
  return value ? String(value) : "";
}

/* ------------------------------------------------------------------ tabs */

function resolveTab() {
  var requested = null;
  try {
    requested = new URLSearchParams(window.location.search).get("tabId");
  } catch (err) {
    requested = null;
  }

  if (requested && /^\d+$/.test(requested)) {
    return new Promise(function (resolve) {
      chrome.tabs.get(Number(requested), function (tab) {
        if (chrome.runtime.lastError || !tab) {
          resolve(null);
          return;
        }
        resolve(tab);
      });
    });
  }

  return new Promise(function (resolve) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      if (chrome.runtime.lastError || !tabs || !tabs.length) {
        resolve(null);
        return;
      }
      resolve(tabs[0]);
    });
  });
}

function runExtraction(tab) {
  if (!tab || typeof tab.id !== "number") return Promise.resolve(null);
  if (tab.url && !/^https?:/i.test(tab.url)) return Promise.resolve(null);
  return new Promise(function (resolve) {
    try {
      chrome.scripting.executeScript(
        { target: { tabId: tab.id }, files: ["content/extract.js"] },
        function (results) {
          if (chrome.runtime.lastError || !results || !results.length) {
            resolve(null);
            return;
          }
          var value = results[0] ? results[0].result : null;
          resolve(value && typeof value === "object" ? value : null);
        }
      );
    } catch (err) {
      resolve(null);
    }
  });
}

/* --------------------------------------------------------------- rendering */

function buildStatusOptions() {
  var select = $("f-status");
  if (!select) return;
  select.innerHTML = "";
  STATUSES.forEach(function (entry) {
    var option = document.createElement("option");
    option.value = entry[0];
    option.textContent = entry[1];
    select.appendChild(option);
  });
  select.value = "saved";
  paintStatusDot();
}

function paintStatusDot() {
  var select = $("f-status");
  var dot = $("status-dot");
  if (!select || !dot) return;
  dot.style.background = STATUS_COLORS[select.value] || "#A9B0BA";
}

function setEnvLabel() {
  var host = hostOf(state.apiBase);
  setText("env-label", host);
  setText("footer-host", host);
}

function fillFields(fields) {
  $("f-company").value = fields.company_name || "";
  $("f-title").value = fields.job_title || "";
  $("f-location").value = fields.location || "";
  $("f-url").value = fields.posting_url || "";
  state.jdText = fields.jd_text || "";
  state.jdSource = fields.jd_source || "";

  $("f-jd").value = state.jdText;
  $("f-include-jd").checked = Boolean(state.jdText) && jdTrusted(state.jdSource);
  renderJdBlock();
}

// Collapsed by default: the count is always visible, the text is one click
// away, and nothing is published without the checkbox.
function renderJdBlock() {
  var block = $("jd-block");
  var include = $("f-include-jd").checked;

  block.hidden = !state.jdText;
  if (!state.jdText) {
    setMessage("jd-line", "");
    return;
  }

  var count = state.jdText.length.toLocaleString();
  if (include) {
    setMessage("jd-line", "Job description captured (" + count + " characters)");
  } else if (jdTrusted(state.jdSource)) {
    setMessage("jd-line", count + " characters captured. Not being saved.");
  } else {
    setMessage(
      "jd-line",
      count + " characters read from this page. Check it before you include it."
    );
  }

  if (include) {
    block.classList.remove("excluded");
  } else {
    block.classList.add("excluded");
  }
}

function toggleJdText() {
  var area = $("f-jd");
  var button = $("jd-toggle");
  var showing = area.hidden;
  area.hidden = !showing;
  button.textContent = showing ? "Hide" : "Show";
  button.setAttribute("aria-expanded", showing ? "true" : "false");
  if (showing) area.focus();
}

function renderGroups(groups) {
  var select = $("f-group");
  select.innerHTML = "";

  if (!groups.length) {
    var none = document.createElement("option");
    none.value = "";
    none.textContent = "No groups yet";
    select.appendChild(none);
    select.disabled = true;
    $("save-btn").disabled = true;
    setMessage("capture-error", "Create or join a group in JobSquad first, then capture this job.");
    return;
  }

  select.disabled = false;
  $("save-btn").disabled = false;

  groups.forEach(function (group) {
    var option = document.createElement("option");
    option.value = String(group.id);
    option.textContent = group.name || "Group " + group.id;
    select.appendChild(option);
  });

  var wanted = String(state.lastGroupId === null ? "" : state.lastGroupId);
  var found = false;
  for (var i = 0; i < select.options.length; i++) {
    if (select.options[i].value === wanted) found = true;
  }
  select.value = found ? wanted : String(groups[0].id);
}

function renderLookup(data) {
  if (!data) {
    setMessage("lookup-line", "");
    return;
  }

  var parts = [];
  if (data.my_status) parts.push("You: " + statusLabel(data.my_status).toLowerCase());
  if (Array.isArray(data.squad)) {
    data.squad.forEach(function (entry) {
      if (!entry || !entry.display_name) return;
      parts.push(entry.display_name + ": " + statusLabel(entry.status).toLowerCase());
    });
  }

  if (parts.length) {
    setMessage("lookup-line", parts.join(SEP));
    return;
  }
  if (data.company_id) {
    setMessage(
      "lookup-line",
      (data.company_name || "This company") + " is already tracked in this group."
    );
    return;
  }
  setMessage("lookup-line", "");
}

/* ------------------------------------------------------------------ flow */

function showUnpaired(message) {
  var select = $("api-base");
  if (select) select.value = state.apiBase;
  setMessage("unpaired-error", message || "");
  $("disconnect-btn").hidden = true;
  show("view-unpaired");
}

function showExpired() {
  $("disconnect-btn").hidden = true;
  show("view-expired");
}

function openConnectPage() {
  var url = state.apiBase.replace(/\/+$/, "") + "/connect";
  try {
    chrome.tabs.create({ url: url });
  } catch (err) {
    window.open(url, "_blank");
  }
  window.close();
}

function refreshLookup() {
  var groupId = $("f-group").value;
  var company = capped($("f-company").value, LIMIT_NAME);
  var url = capped($("f-url").value, LIMIT_URL);
  if (!groupId || (!company && !url)) {
    setMessage("lookup-line", "");
    return;
  }

  state.lookupSeq += 1;
  var seq = state.lookupSeq;

  // POST, not GET: the page the user is browsing would otherwise sit in the
  // server's access log as a query parameter on every popup open.
  api("POST", "/api/capture/lookup", {
    body: { group_id: Number(groupId), url: url, company_name: company }
  }).then(function (result) {
    if (seq !== state.lookupSeq) return;
    if (!result.ok) {
      if (result.status === 401) showExpired();
      // A failed lookup is informational only, so nothing else is surfaced.
      setMessage("lookup-line", "");
      return;
    }
    renderLookup(result.data);
  });
}

function saveCapture(payload) {
  return api("POST", "/api/capture", { body: payload }).then(function (result) {
    if (result.ok || result.status !== 422 || !("job_title" in payload)) return result;
    // job_title is not in the frozen E1 body shape. If this build of the API
    // rejects it, drop it and save the fields the contract does define.
    var trimmed = {};
    Object.keys(payload).forEach(function (key) {
      if (key !== "job_title") trimmed[key] = payload[key];
    });
    return api("POST", "/api/capture", { body: trimmed });
  });
}

function onSubmit(event) {
  event.preventDefault();
  setMessage("capture-error", "");

  var company = capped($("f-company").value, LIMIT_NAME);
  if (!company) {
    setMessage("capture-error", "Add a company name before saving.");
    $("f-company").focus();
    return;
  }

  var groupId = Number($("f-group").value);
  if (!Number.isFinite(groupId) || groupId <= 0) {
    setMessage("capture-error", "Pick a group before saving.");
    return;
  }

  var payload = {
    group_id: groupId,
    company_name: company,
    status: $("f-status").value || "saved"
  };
  var location = capped($("f-location").value, LIMIT_NAME);
  var url = capped($("f-url").value, LIMIT_URL);
  var title = capped($("f-title").value, LIMIT_NAME);

  if (url && !isHttpUrl(url)) {
    setMessage("capture-error", "The posting URL must start with http:// or https://.");
    $("f-url").focus();
    return;
  }

  if (location) payload.location = location;
  if (url) payload.posting_url = url;
  // job_title is not part of the frozen E1 body shape. The API ignores unknown
  // fields today, and saveCapture drops it if a build ever rejects it.
  if (title) payload.job_title = title;

  // The description is sent only when the user has ticked the box. Unticked
  // means the field is absent from the body entirely, not blanked.
  var jd = capped($("f-jd").value, LIMIT_JD);
  if (jd && $("f-include-jd").checked) payload.jd_text = jd;

  var button = $("save-btn");
  button.disabled = true;
  button.textContent = "Saving";

  send({ type: "set-last-group", group_id: groupId });

  saveCapture(payload).then(function (result) {
    if (!result.ok) {
      button.disabled = false;
      button.textContent = "Save to JobSquad";
      if (result.status === 401) {
        showExpired();
        return;
      }
      setMessage("capture-error", result.error || "Could not save this job.");
      return;
    }

    var data = result.data || {};
    var name = data.company_name || company;
    setText("done-text", data.created_company ? "Added " + name : "Updated your application at " + name);
    show("view-done");
    setTimeout(function () {
      window.close();
    }, 1400);
  });
}

function wireEvents() {
  $("connect-btn").addEventListener("click", openConnectPage);
  $("reconnect-btn").addEventListener("click", openConnectPage);

  $("api-base").addEventListener("change", function () {
    var chosen = $("api-base").value;
    send({ type: "set-api-base", api_base: chosen }).then(function (result) {
      state.apiBase = (result && result.api_base) || chosen;
      setEnvLabel();
      // A token minted by one deployment is worthless, and unsafe, on the
      // other. The worker drops it on a switch, so the popup goes back to the
      // unpaired state rather than pretending the old connection still works.
      showUnpaired(
        result && result.cleared
          ? "Switched server. Connect again to " + hostOf(state.apiBase) + "."
          : ""
      );
    });
  });

  $("disconnect-btn").addEventListener("click", function () {
    send({ type: "unpair" }).then(function () {
      showUnpaired("Disconnected. Connect again when you are ready.");
    });
  });

  $("capture-form").addEventListener("submit", onSubmit);
  $("f-status").addEventListener("change", paintStatusDot);
  $("jd-toggle").addEventListener("click", toggleJdText);
  $("f-include-jd").addEventListener("change", renderJdBlock);
  $("f-jd").addEventListener("input", function () {
    state.jdText = $("f-jd").value;
    renderJdBlock();
  });
  $("f-group").addEventListener("change", function () {
    var groupId = Number($("f-group").value);
    if (Number.isFinite(groupId)) send({ type: "set-last-group", group_id: groupId });
    refreshLookup();
  });
  $("f-company").addEventListener("change", refreshLookup);
}

function startCapture() {
  show("view-loading");
  $("disconnect-btn").hidden = false;

  var tabPromise = resolveTab();
  var pendingPromise = send({ type: "take-pending" });

  Promise.all([tabPromise, pendingPromise])
    .then(function (values) {
      var tab = values[0];
      var pending = values[1] && values[1].fields ? values[1].fields : null;

      return runExtraction(tab).then(function (extracted) {
        var fields = {
          company_name: "",
          job_title: "",
          location: "",
          posting_url: "",
          jd_text: ""
        };

        if (extracted) {
          Object.keys(fields).forEach(function (key) {
            if (typeof extracted[key] === "string") fields[key] = extracted[key];
          });
        }
        if (pending) {
          Object.keys(fields).forEach(function (key) {
            if (!fields[key] && typeof pending[key] === "string") fields[key] = pending[key];
          });
        }
        if (!fields.posting_url && tab && tab.url && isHttpUrl(tab.url)) {
          fields.posting_url = tab.url;
        }
        fields.jd_source = extracted && typeof extracted.jd_source === "string" ? extracted.jd_source : "";

        fillFields(fields);

        if (!extracted) {
          setMessage(
            "capture-note",
            "Could not read this page automatically. Fill in the details before saving."
          );
        } else {
          setMessage("capture-note", "");
        }

        show("view-capture");
        return loadGroups();
      });
    })
    .catch(function () {
      show("view-capture");
      setMessage("capture-error", "Something went wrong while reading this page.");
    });
}

function loadGroups() {
  return api("GET", "/api/groups").then(function (result) {
    if (!result.ok) {
      if (result.status === 401) {
        showExpired();
        return;
      }
      renderGroups([]);
      setMessage("capture-error", result.error || "Could not load your groups.");
      return;
    }
    var groups = Array.isArray(result.data) ? result.data : [];
    renderGroups(groups);
    if (groups.length) refreshLookup();
  });
}

function init() {
  buildStatusOptions();
  wireEvents();

  send({ type: "get-state" }).then(function (result) {
    if (result && result.api_base) state.apiBase = result.api_base;
    state.lastGroupId =
      result && typeof result.last_group_id === "number" ? result.last_group_id : null;
    setEnvLabel();

    if (!result || !result.ok) {
      showUnpaired("The extension background is not responding. Reload the extension.");
      return;
    }
    if (!result.paired) {
      showUnpaired("");
      return;
    }
    startCapture();
  });
}

document.addEventListener("DOMContentLoaded", init);
