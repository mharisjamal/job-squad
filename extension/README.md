# JobSquad browser extension (Phase E1)

Capture a job posting into your JobSquad group in one click, from the page you are already
looking at. No build step, no bundler, no npm dependencies: this folder loads directly into
Chrome as an unpacked extension.

The extension is free for every JobSquad user. It is not a paid tier.

## What it does

- **Capture the current page.** Click the toolbar icon or press **Ctrl+Shift+J** (Cmd+Shift+J on
  macOS). The popup reads the page, shows what it found, and waits for you to press Save.
- **Capture a link.** Right-click a job link and choose **Save this job to JobSquad**. The posting
  opens in a new tab so you can see what you are saving.
- **Squad awareness before you save.** If someone in your group already tracked that company, the
  popup shows a quiet line such as `You: saved` or `Ali: rejected`.
- **Never saves silently.** Every capture shows editable fields and needs one confirming click.
  Wrong data destroys trust faster than a little friction does.
- **You decide whether the job description goes in.** It is shown, editable, and opt-in whenever
  the page did not clearly identify itself as a job posting. See below.

## The job description, and who can read it

The captured job description is the one field that can be long, and **everyone in your group can
read it**. So the popup never publishes it behind your back:

- The description appears in its own box with a character count and the line
  **"Your squad can read this."**
- It is **collapsed by default**. Press **Show** to expand it into a text area you can read and
  edit. What you leave in the box is exactly what gets saved.
- An **Include job description** checkbox controls whether it is sent at all. Unticked means the
  field is left out of the request entirely, not saved as blank.
- The checkbox is **ticked by default only when the page identified itself as a job posting**,
  through `schema.org/JobPosting` JSON-LD or one of the built-in site rules (LinkedIn, Indeed,
  Workday, Greenhouse, Lever).
- It is **unticked by default when the text came from the generic fallback**, because that path
  reads the main text block of whatever page is open. If you press Ctrl+Shift+J on an internal
  wiki, a webmail thread, or a private ATS screen, that page's text is shown to you but is not
  published to your group unless you tick the box yourself.

Everything else on the card (company, job title, location, posting URL) is editable in the same
way, and nothing is sent until you press Save.

## Load it unpacked

1. Open `chrome://extensions` in Chrome (or Edge at `edge://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick this `extension/` folder.
4. Pin the JobSquad icon to the toolbar so the capture button is one click away.

Nothing needs to be built or installed first. After editing any file here, press the reload arrow
on the extension card in `chrome://extensions`.

## Pair it with your account

The extension never asks for your password. It receives a long lived extension token from the web
app, which works the same way whether you signed in with a password, Google, GitHub, or LinkedIn.

1. Sign in to JobSquad in the same browser.
2. Open the extension popup and press **Connect to JobSquad**. It opens `{server}/connect`.
3. On that page press **Connect extension**. The page mints a token and hands it to the extension
   with `postMessage`; the extension stores it and the page shows the connected state.
4. The popup now opens straight into the capture card.

The handshake is accepted only when the message comes from the page itself (`event.source ===
window`), from the page's own origin (`event.origin === location.origin`), and carries
`{source: "jobsquad-app", type: "extension-token"}`. Anything else is ignored, so a hostile page
cannot hand the extension a token. The token is never logged and never sent back to any page.

Re-connecting replaces the old token rather than piling up dead ones: the extension reports the
token it is replacing back to the page, which revokes it server side. That only happens when both
tokens came from the same server.

To disconnect, use **Disconnect** at the bottom of the popup, or revoke the token from the
JobSquad settings page (that kills it server side, which is the stronger option if you think it
leaked).

## Switch to a local backend for development

The popup's unpaired view has a **JobSquad server** picker with two entries:

- `https://jobsquad.dpdns.org` (production, the default)
- `http://localhost:8100` (local development)

Pick localhost, press **Connect to JobSquad**, and pair against your local app. Both origins are
declared in `host_permissions`, so no other server can be reached. The choice is remembered in
`chrome.storage.local`.

**Switching servers signs you out.** A token belongs to the deployment that minted it, so changing
this setting deletes the stored token (and the remembered group) and returns the popup to the
unpaired state. That is deliberate: a production token must never be sent to `http://localhost`
over plaintext.

## Permissions and why each one is needed

| Permission | Why |
|---|---|
| `storage` | Keeps the extension token, the chosen server, and the last used group. |
| `activeTab` | Lets the extension read the page **you invoked it on**, and only then. |
| `scripting` | Runs `content/extract.js` on demand on that tab. |
| `contextMenus` | Adds the right-click "Save this job to JobSquad" item. |
| host: the two app origins | Talking to the JobSquad API. Nothing else. |

There are no job board host permissions. The extension cannot read LinkedIn, Indeed, or anything
else in the background: extraction happens only in the moment you ask for it. Adding board hosts
is an E2 decision, not an E1 one.

The service worker holds your token, so it is not a general purpose proxy. It answers only its own
extension's popup and content scripts, and only for the three calls the extension actually makes
(`GET /api/groups`, `POST /api/capture`, `POST /api/capture/lookup`). Any other method or path is
refused locally, before a request leaves the browser. The lookup is a POST so the page you are
browsing does not end up in the server's access log.

## Files

```
manifest.json          Manifest V3: permissions, action, command, context menu, content script
background.js          service worker: state, entry points, every API call
content/extract.js     injected on demand, returns the extracted fields, never throws
content/connect.js     pairing handshake, runs only on {app}/connect
popup/popup.html       capture card markup
popup/popup.css        Worklight dark palette, written as plain hex
popup/popup.js         popup states, extraction, group picker, lookup, save
icons/16|32|48|128.png the app mark: white dot in a green ring on a dark tile
```

## How extraction works

In order, each step filling only the fields the previous one left empty:

1. **schema.org JobPosting JSON-LD.** Every `<script type="application/ld+json">` is parsed,
   including arrays and `@graph` wrappers. Title, `hiringOrganization.name`, the job location
   address, the description, and the canonical URL come from here when a board emits it, which
   most do because Google Jobs requires it.
2. **Site rules** for LinkedIn, Indeed, Workday (`*.myworkdayjobs.com`), Greenhouse
   (`boards.greenhouse.io`, `job-boards.greenhouse.io`), and Lever (`jobs.lever.co`).
3. **Generic fallback:** `og:title` or a cleaned `document.title` (the trailing site name is
   dropped), `og:site_name` for the company, and the largest `main`/`article` text block for the
   job description.

Script and style content is stripped, whitespace is normalized, and the job description is capped
at 50,000 characters. Everything is editable before you save, and the fields are always strings,
never null.

Two details worth knowing:

- The extractor also reports **which** of the three stages produced the description. That is what
  decides whether "Include job description" starts ticked, as described above.
- A posting URL is only accepted when its scheme is `http` or `https`. A page that puts a
  `javascript:` or `data:` URL in its JSON-LD gets it thrown away, and the live page URL is used
  instead. The same rule applies to anything you type into the field yourself.

## Roadmap (not built yet)

**E2:** squad awareness injected into LinkedIn and Indeed result lists, so you see who already
applied before you open a posting, plus quick status updates from the popup. This is the point
where job board host permissions become necessary.

**E3:** detecting that you actually submitted an application, and periodically re-checking whether
a saved posting is still live.

**Explicitly out of scope:** ATS autofill (a maintenance treadmill, and effectively a separate
product) and email parsing.
