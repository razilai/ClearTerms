# ClearTerms Chrome extension

Thin MV3 extension: auto-detects Terms-of-Service pages, and on **Analyze**
scrapes the page text and POSTs it to the ClearTerms backend `POST /analyze` —
the result lands in your web-app history just like a pasted TOS.

It has no login of its own. It reads the session the web app stores in
`localStorage`, so you must be logged into the ClearTerms web app for Analyze to
work; otherwise the popup shows a **Log in** button that opens the web app.

## Architecture

- `src/background.ts` — service worker. The **only** context that calls the
  backend: MV3 background `fetch` bypasses CORS for `host_permissions` origins,
  so no backend CORS config is needed. Keeps all state in `chrome.storage.local`
  (the worker is ephemeral).
- `src/content-token.ts` — runs only on the web-app origin; reads the JWT from
  the page `localStorage` and relays it to the worker.
- `src/content-detector.ts` — runs on every page. Detects either (a) the page
  itself is a TOS, or (b) an "I agree to <terms>" checkbox whose label links to a
  **same-origin** terms doc. In case (b), Analyze fetches + parses those linked
  docs (via `DOMParser`, no extra permission) instead of scraping the page.
  Cross-origin agreement links are skipped.
- `src/popup.ts` — UI: logged-out / idle / analyzing / result / error.

## Build & load

```bash
cd extension
npm install
npm run build          # or: npm run watch
```

Then in Chrome: `chrome://extensions` → enable **Developer mode** → **Load
unpacked** → select `extension/dist`. Reload the unpacked extension after each
rebuild.

## Config / origins

Dev origins live in two places that **must stay in sync** (the manifest can't
read JS constants):

- `src/config.ts` — `BACKEND_ORIGIN`, `WEB_ORIGIN`, etc.
- `public/manifest.json` — `host_permissions` + `content_scripts[].matches`.

Defaults: backend `http://localhost:8000`, web app `http://localhost:5173`. Add
production origins to **both** when deploying.
