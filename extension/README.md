# JobSquad browser extension (Phases E1 to E3)

Capture a job posting into your JobSquad group in one click, from the page you are already
looking at. No build step, no bundler, no npm dependencies: this folder loads directly into
Chrome as an unpacked extension.

The extension is free for every JobSquad user. It is not a paid tier.

## What it does

- **Capture the current page.** Click the toolbar icon or press **Ctrl+Shift+J** (Cmd+Shift+J on
  macOS). The popup reads the page, shows what it found, and waits for you to press Save.
- **Capture a link.** Right-click a job link and choose **Save this job to JobSquad**. This reads
  the **link and nothing else**: the URL is prefilled and the card says so. To get the title,
  company and description, open the posting and press Ctrl+Shift+J there.
- **Squad awareness before you save.** If someone in your group already tracked that company, the
  popup shows a quiet line such as `You: saved` or `Ali: rejected`.
- **Squad status on job boards** (opt-in, off by default). Result rows on LinkedIn and Indeed get a
  small chip when your squad already has a standing on that employer. See "Job board add-ons".
- **An offer to mark applications as applied** (opt-in, off by default). After you submit on
  Greenhouse, Lever or Workday, a small prompt asks whether to move that company to Applied.
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

## Job board add-ons (both optional, both off by default)

Two toggles sit at the bottom of the capture card. **The extension ships asking for nothing on any
job board.** Access to those sites is requested only when you switch a toggle on, and handed back
to Chrome when you switch it off.

Each toggle shows the **live** answer from Chrome, not a remembered one: if you revoke the access
from `chrome://extensions`, the toggle is off the next time you open the popup, and the script that
needed it is unregistered.

Both add-ons use your **last used group**, the one the popup has selected. Until you have opened
the popup once and had a group selected, the toggles say so and nothing appears on any board.

### Show squad status on job boards

Asks for `https://*.linkedin.com/jobs/*` and `https://*.indeed.com/*`. LinkedIn access stops at the
jobs section: the feed, messaging, notifications and profile pages are not job results, so the
add-on never asks to read them.

On a results page it reads the company name out of each row, asks JobSquad which of those your
group already knows, and adds one small chip to the rows that came back known:

| What the chip says | What it means |
|---|---|
| `You - applied` | You already have an application at that company |
| `Ali - rejected` | One squad member's standing |
| `You - applied · Ali - rejected +2` | Yours, one squad member, and how many more there are |
| `Tracked` | The company is in your group, but nobody has a standing on it yet |
| (nothing) | Nobody has touched that company. Silence is the default |

The chips are added; nothing on the page is removed, reordered, restyled or blocked. Company names
never leave the page as anything other than a name: the lookup sends a list of company names and
gets standings back. The board page itself never sees your token, because the content script cannot
call the API at all: it asks the extension's background worker, which holds the token.

**The board cannot read the chip.** Each chip is rendered inside a **closed shadow root**, so your
squadmates' names and their statuses are not in the page's DOM, not in its text, and not reachable
by any script the board runs. If a browser will not give the extension a closed root, it renders
**nothing** rather than falling back to text the page could scrape. Honest about the limit: a chip
is still a visible box in the page's layout, so a determined board could measure that a row got one
and roughly how wide it is. The known/unknown bit is therefore not perfectly hidden. What is
protected is the part that matters, the names and the statuses.

Two more limits, because the page is the one supplying the rows and the company text in them:

- At most **300 distinct company names** are ever looked up for the lifetime of one tab's document.
  After that the add-on stops. A page cannot walk the extension through a dictionary.
- Text read off a row is cut to a safe length **before** it is cleaned up, so a giant hidden text
  node cannot cost the tab a wall of string work on every scan.

### Offer to mark applications as applied

Asks for `https://*.greenhouse.io/*`, `https://*.lever.co/*` and `https://*.myworkdayjobs.com/*`.

**What it does:** watches for a confirmation that you already submitted, either a confirmation
fragment in the page's URL path (`/thanks`, `/confirmation`, `/application_confirmation`, and a few
more) or a confirmation phrase in a heading ("Application submitted", "Thank you for applying",
"Your application has been received", and a handful of others). On a hit it shows a small prompt in
the corner offering to mark that company as **applied**, with a "Not now" that dismisses it.

**What it does not do, ever:**

- It never writes anything on its own. The `POST /api/capture` happens on your click and nowhere
  else.
- It never reads, fills, clears or submits a form field. The only things it reads are heading text
  and the URL path.
- It never presses a button on the page, and it never blocks one.
- It never sends a job description, or any field other than the company name and the posting URL.
  The status is fixed to `applied` by the extension's background worker, not by the page.

**It has to be your click.** A page can dispatch a click at a button just like a person can, and a
dispatched click ignores the disabled state a real one respects. So the prompt checks that the event
came from the browser and not from a script (`isTrusted`), and that you have actually interacted
with the page just now (transient user activation). On top of that, one save can be in flight at a
time, and a single page load can produce **one** save at most. A page that fakes a confirmation
heading and scripts the button gets nothing.

The company name in the prompt is shown at up to 60 characters. It is chosen by the page, and a long
one in a JobSquad-branded box is a place to write a phishing line, not a company name.

If the page's URL is a confirmation URL, that URL is **not** saved as the posting URL: a "thanks"
page is a bad link to keep, and it would overwrite the good one already on your application. When a
URL *is* saved, its **query string and fragment are stripped first**: confirmation links on these
boards carry one-time tokens and tracking parameters (`gh_src`, `gh_jid`, session ids), and none of
that belongs on an application row your whole group can read.

If the extension cannot work out which employer the confirmation belongs to (an embedded Greenhouse
form with no company in the URL, for instance), it shows nothing rather than inventing a company
name. Capture it from the popup instead.

## Permissions and why each one is needed

| Permission | Why |
|---|---|
| `storage` | Keeps the extension token, the chosen server, and the last used group. |
| `activeTab` | Lets the extension read the page **you invoked it on**, and only then. |
| `scripting` | Runs `content/extract.js` on demand on that tab, and registers a board add-on's content script while you have that add-on turned on. |
| `contextMenus` | Adds the right-click "Save this job to JobSquad" item. |
| host: the two app origins | Talking to the JobSquad API. Nothing else. |

**Nothing on this list mentions a job board.** The board origins live in
`optional_host_permissions`, which Chrome does not grant at install:

| Optional host | Requested by |
|---|---|
| `https://*.linkedin.com/jobs/*`, `https://*.indeed.com/*` | "Show squad status on job boards" |
| `https://*.greenhouse.io/*`, `https://*.lever.co/*`, `https://*.myworkdayjobs.com/*` | "Offer to mark applications as applied" |

They are requested when you turn a toggle on and removed when you turn it off. While a permission
is held, the matching content script is registered with `chrome.scripting.registerContentScripts`;
when it is revoked, by the toggle or from `chrome://extensions`, the registration is removed too.
With both toggles off the extension can read no job board at all, and capture still works
everywhere, because that path uses `activeTab` in the moment you ask for it.

Turning a toggle **on** also injects the script into the matching tabs you already have open, so the
feature works straight away instead of after a reload. Turning it **off** unregisters the script,
but Chrome does not terminate copies already running in open tabs, so the worker independently
re-checks the permission on **every** board message and refuses once it is gone. A tab left open
across a revoke can keep talking; it just stops being answered. The toggle also reports whether the
script actually registered, not merely whether the permission exists, so a failed registration reads
as "off" rather than a confident lie.

The service worker holds your token, so it is not a general purpose proxy:

- Every message must come from this extension's own id.
- The method and path must be one of the four calls the extension makes (`GET /api/groups`,
  `POST /api/capture`, `POST /api/capture/lookup`, `POST /api/capture/lookup/batch`). Anything else
  is refused locally, before a request leaves the browser.
- The **general passthrough is refused entirely for content scripts**. The board scripts get two
  narrow message types instead: one that looks companies up, and one that marks a company applied.
  Both bodies are assembled by the worker: the group comes from storage, the status is fixed to
  `applied`, and a page cannot influence either.
- Those two board messages are also checked against **where they came from**. Every content script
  in this extension shares one message channel and one extension id, including `content/extract.js`,
  which `activeTab` injects into whatever page you invoked capture on. So the worker requires the
  sender's own URL, which Chrome sets and the message cannot forge, to match that specific feature's
  sites, and requires the permission for them to be held right now. LinkedIn cannot file an
  application, Greenhouse cannot run a squad lookup, and no other site can do either.
- `pair`, the one message that writes your token, is accepted only from a JobSquad deployment
  origin. Nothing running on a job board can hand the extension a token.

The lookup is a POST so the page you are browsing does not end up in the server's access log.

## Files

```
manifest.json          Manifest V3: permissions, optional host permissions, action, command, menu
background.js          service worker: state, entry points, every API call, board script registration
content/extract.js     injected on demand, returns the extracted fields, never throws
content/connect.js     pairing handshake, runs only on {app}/connect
content/badges.js      opt-in: squad status chips on LinkedIn and Indeed result rows
content/submitted.js   opt-in: the "mark as applied" prompt after you submit on an ATS
popup/popup.html       capture card markup and the two add-on toggles
popup/popup.css        Worklight dark palette, written as plain hex
popup/popup.js         popup states, extraction, group picker, lookup, save, permission toggles
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

## Roadmap

**Built:** E1 (capture, pairing, the job description control), E2 (squad status chips on LinkedIn
and Indeed), E3 (the offer to mark an application applied after you submit).

**Not built yet:** periodically re-checking whether a saved posting is still live, and quick status
updates straight from the popup.

**Explicitly out of scope:** ATS autofill (a maintenance treadmill, and effectively a separate
product) and email parsing.
