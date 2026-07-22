# Running the Lightning Blackjack solver on an iPhone (fully local, no server)

The web app (`lbj_solver/web/index.html`) is **one self-contained page that runs
entirely in the browser**. The whole solver is ported to JavaScript (verified
against the Python engine — identical EVs and identical play), so once the page
is loaded there is **nothing to talk to**: no server, no network, no Python.

Why this matters on iOS: the earlier version ran a Python server in a-Shell and
the page called it for every move. But iOS **suspends a background app**, so the
moment you looked at Safari, the a-Shell server stopped answering — that's why
the UI froze until you switched back to a-Shell. Now the page does all the work
itself, so that whole problem is gone.

## One-time setup

1. **Install [a-Shell](https://apps.apple.com/app/a-shell/id1473805438)** (free).
   It's used *only to hand the page to Safari the first time* — after that you
   don't need it.

2. **Get the code onto the phone** (a-Shell uses `lg2`, not `git`):
   ```
   lg2 clone <your-repo-url> erangur
   cd erangur
   ```

3. **Serve the page once:**
   ```
   python -m lbj_solver.webserver
   ```
   It prints `serving the app at http://127.0.0.1:8000`.

4. **Open it in Safari** at **`http://127.0.0.1:8000`** (type the numeric
   address — not `localhost`).

5. **Share -> Add to Home Screen.** This installs it as a full-screen app and
   caches it offline (via a service worker).

## After that

- **Tap the home-screen icon.** It opens full-screen and plays entirely offline
  — no a-Shell, no server, nothing to start. Deal / hit / split / stats all run
  instantly in the page.
- You only need to repeat step 3 (`python -m lbj_solver.webserver`) if you want
  to load a **new version** of the page after an `lg2 pull`. (Open
  `http://127.0.0.1:8000` in Safari again; the icon then picks up the update.)

## If something misbehaves

- Tap the **🐞** button in the header. It shows the in-page activity log — every
  action, its timing, and any error — and the build string at the top. Since
  everything runs in the page, this is the whole story now (there's no separate
  server log to check).

## Notes

- **Multiplier histogram (Store toggle + 📊):** now saved in the browser's local
  storage on the device (it used to be CSV files on disk). "All" is everything
  ever recorded on this device; "This run" is the current app session.
- **Options** (`⚙`): auto-play toggle + conviction threshold + starting carry —
  all exactly as before.
- The `python -m lbj_solver.webserver` loader is a tiny static file server. You
  can also serve the page from any always-on machine, or host the single
  `index.html` on any static host, and open that URL instead — it behaves the
  same because the page is self-contained.
