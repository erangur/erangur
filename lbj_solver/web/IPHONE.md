# Running the Lightning Blackjack solver on an iPhone (fully local)

This is the **web front-end** for the solver (`lbj_solver/webserver.py` +
`lbj_solver/web/index.html`). It uses **only the Python standard library** and the
solved carry values ship cached in `lbj_solver/data/solution.json`, so there is
**nothing to `pip install`** and no ~minute solve on the phone.

The app runs *on the phone*: a small Python web server runs inside a Python host
app, binds to `localhost`, and Safari opens it. One catch — the server only runs
while the host app is open, so each session you start the server first, then open
the icon.

## One-time setup

1. **Install a Python host app** — [a-Shell](https://apps.apple.com/app/a-shell/id1473805438)
   (free) is recommended. (Pythonista 3 also works.)

2. **Get the code onto the phone.** In a-Shell (no `pip install` — there are no
   dependencies):
   ```
   git clone <your-repo-url> erangur
   cd erangur
   ```
   (Or copy the folder in via iCloud Drive / AirDrop and `cd` to it.)

## Each time you want to play

3. **Start the server** (from the repo root in a-Shell):
   ```
   python -m lbj_solver.webserver
   ```
   It prints `... serving at http://localhost:8000`.

4. **Open it**: switch to Safari and go to `http://localhost:8000`.

5. **Install the icon** (first time only): Share → **Add to Home Screen**.
   From then on, tap the icon *after* step 3 to open the app full-screen.

To stop the server, return to a-Shell and press `Ctrl-C` (or just close a-Shell).

## Options

```
python -m lbj_solver.webserver --port 8080      # different port
python -m lbj_solver.webserver --host 0.0.0.0   # also reachable from other devices on your wifi
```

`--host 0.0.0.0` is what you'd use if you later run this on an always-on box
(Raspberry Pi, home server, VPS) instead of the phone — then the home-screen icon
works without launching anything first. iOS may prompt for "Local Network" access
the first time you use `0.0.0.0`; the default `127.0.0.1` (this-device-only) avoids
that prompt.

## Notes

- **Histogram storage**: the header **Store** toggle records each dealt set to a
  CSV under `lbj_solver/data/histograms/`. On the phone that writes into the app's
  sandbox — fine to use, just not easy to pull back off the device.
- **Everything the tkinter GUI does is here**: auto-play (⚙ settings: toggle +
  conviction threshold + starting carry), the felt table, EV chips, the morphing
  dock, the 📊 multiplier histogram, and Reset.
