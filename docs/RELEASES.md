# Release notes

The web app checks `docs/version.json` on every start and offers the update
with the notes below. **When you ship a change, bump all four:**

1. `BUILD_NO` and the `BUILD` string in `docs/index.html`
2. `CACHE` in `docs/sw.js`
3. `build` / `name` / `date` / `notes` in `docs/version.json` (notes: 1-3 short
   lines, written for whoever is holding the phone, not for the diff)
4. an entry here

---

## build 25 — serverless 25 · 2026-09-07

- The app now checks for a new version each time you open it, and shows what
  changed.

## build 24 — serverless 24 · 2026-09-07

- The dealer upcard is its own screen: blue pad, its own title, and a pulsing
  slot on the felt showing exactly where the card goes.

## build 23 — serverless 23 · 2026-09-07

- Entering a hand is three single-purpose screens — multiplier set, your hand,
  then the dealer upcard — each filling the screen with big keys.
- DEAL only lights up once the set, both your cards and the upcard are in.

## build 22 — serverless 22 · 2026-09-07

- Tap the carry (top left) to set it; it left Settings.
- Histogram recording starts on, and a reset no longer switches it off.
