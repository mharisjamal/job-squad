/*
 * JobSquad pairing content script.
 *
 * Runs only on {app}/connect (see the manifest match patterns). The app page
 * mints a long lived extension token and hands it over with postMessage. This
 * script is the only place that accepts it, and it accepts it only when all
 * four checks pass:
 *
 *   event.source === window        the message came from this page, not an iframe
 *   event.origin === location.origin   same origin as the page we are allowed on
 *   data.source === "jobsquad-app"     the shape the app promises to send
 *   data.type   === "extension-token"
 *
 * The token is forwarded straight to the service worker and never logged,
 * never stored here, and never echoed back to the page.
 */

(function jobsquadConnect() {
  "use strict";

  var ORIGIN = window.location.origin;

  function reply(payload) {
    try {
      window.postMessage(payload, ORIGIN);
    } catch (err) {
      // A page that tore itself down mid handshake is not worth reporting.
    }
  }

  window.addEventListener(
    "message",
    function (event) {
      if (event.source !== window) return;
      if (event.origin !== ORIGIN) return;

      var data = event.data;
      if (!data || typeof data !== "object") return;
      if (data.source !== "jobsquad-app") return;
      if (data.type !== "extension-token") return;

      var token = typeof data.token === "string" ? data.token.trim() : "";
      if (!token) {
        reply({
          source: "jobsquad-extension",
          type: "pair-failed",
          error: "The connect page sent no token."
        });
        return;
      }

      var apiBase =
        typeof data.api_base === "string" && data.api_base.trim() ? data.api_base.trim() : ORIGIN;

      // token_id is optional: an older app build simply will not send it, and
      // the handshake still succeeds without it.
      var tokenId =
        typeof data.token_id === "number" || typeof data.token_id === "string"
          ? data.token_id
          : null;

      try {
        chrome.runtime.sendMessage(
          { type: "pair", token: token, token_id: tokenId, api_base: apiBase },
          function (response) {
            if (chrome.runtime.lastError) {
              reply({
                source: "jobsquad-extension",
                type: "pair-failed",
                error: "The JobSquad extension is not responding. Reload the page and try again."
              });
              return;
            }
            if (response && response.ok) {
              // The token this one replaces, so the page can revoke it and stop
              // "Connected extensions" filling up with dead rows. Null when
              // there was no previous token, when it came from a different
              // deployment, or when it predates token_id tracking.
              reply({
                source: "jobsquad-extension",
                type: "paired",
                previous_token_id:
                  response.previous_token_id === undefined ? null : response.previous_token_id
              });
              return;
            }
            reply({
              source: "jobsquad-extension",
              type: "pair-failed",
              error:
                response && response.error
                  ? response.error
                  : "The extension could not store the connection."
            });
          }
        );
      } catch (err) {
        reply({
          source: "jobsquad-extension",
          type: "pair-failed",
          error: "The JobSquad extension is not responding. Reload the page and try again."
        });
      }
    },
    false
  );

  // Let the page know an extension is present, so it can tell "not installed"
  // apart from "installed but the handshake failed".
  reply({ source: "jobsquad-extension", type: "ready" });
})();
