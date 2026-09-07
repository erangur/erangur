# Lightning Blackjack on iPhone (via GitHub Pages)

The web app (`docs/index.html`) is **one self-contained page that runs entirely
in your browser** — the whole solver is ported to JavaScript (verified against
the Python engine). There is no server and no network use once the page loads,
so it works offline and never freezes waiting on anything.

We serve the single file from **GitHub Pages**. "Hosting" here just means handing
your browser the file once; all the game logic runs locally on your phone.

## One-time: turn on GitHub Pages (you must do this part)

1. On github.com, open the **`erangur/erangur`** repo → **Settings** → **Pages**.
2. Under **Build and deployment**:
   - **Source:** *Deploy from a branch*
   - **Branch:** `iphone-webapp`  •  **Folder:** `/docs`  → **Save**.
3. Wait ~1 minute. The Pages panel then shows your live URL, which will be:
   **`https://erangur.github.io/erangur/`**

   > If the repo is **private** on a free plan, Pages won't publish — make the
   > repo public (Settings → General → Danger Zone → Change visibility), or tell
   > me and we'll pick another host.

## On the phone

1. Open **`https://erangur.github.io/erangur/`** in Safari. The app loads.
2. **Share → Add to Home Screen.** This installs it full-screen and a service
   worker caches it for offline use.
3. From now on, **tap the icon** — it opens instantly, works offline, and needs
   nothing running. Deal / hit / split / stats all happen in the page.

## Updating it later

When new changes land on `iphone-webapp`, GitHub re-publishes automatically.

The app checks for itself: on every start (and whenever you bring it back to
the foreground) it fetches `version.json` and compares the build number there
with its own. If a newer build is out you get **"New version available"** with
that build's release notes and two buttons — **Update now** (clears the caches
and reloads into the new build) or **Later** (asks again next time you start
it; the 🐞 button keeps a gold dot in the meantime). Offline, the check fails
quietly and the app carries on.

Shipping a release means bumping four things together — `BUILD_NO`/`BUILD` in
`index.html`, `CACHE` in `sw.js`, `version.json`, and an entry in
`RELEASES.md`. `python tests/test_solver.py` checks they agree.

## If something looks wrong

Tap the **🐞** button in the header: it shows the in-page activity log (every
action, timing, any error) and the build string. Since everything runs in the
page, that's the whole story.

---

### Optional: run it locally instead (no GitHub)

`python -m lbj_solver.webserver` is a tiny static file server for the same
`docs/` folder — handy on a computer (`http://127.0.0.1:8000`). It's **not**
reliable on the phone itself: iOS suspends the a-Shell process the moment you
switch to Safari, so the loader dies before the page can load. That's exactly
why we use Pages for the phone.
