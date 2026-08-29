# lolq — project rules

**Always `git push` to GitHub on task completion.** Remote: `origin` →
`https://github.com/imoutonokoibito/lolq.git`, branch `master`. This repo is
NOT under the clod GitHub-push ban — that ban is `xXhackerlordXx/clod/` only.

## Stack

- `main.py` — bot, uses `lcu-driver` (aiohttp wrapper around the League
  Client's local LCU API). Runs on Windows, built to exe via
  `.github/workflows/build.yml` (pyinstaller, windows-latest runner).
- `static/app.js` + `server.py` — local web config editor for `config.json`
  (layouts/roles/bans/fallback). Pure vanilla JS, no build step.
- No test suite. No local League client available for live testing — verify
  logic changes by reading LCU API docs/community scripts, not by running.

## LCU API — undocumented, verify via community sources

Riot does not officially document the LCU API. It can change without notice.
When touching `main.py`'s LCU calls, verify against:
- Swagger dump (most reliable, kept current by community reverse-engineering):
  `https://raw.githubusercontent.com/dysolix/hasagi-types/main/swagger.json`
  (huge file, `python3 -c "import json; ..."` grep it, don't try to read whole)
- `https://swagger.dysolix.dev/lcu/` — browsable version of the same
- `https://hextechdocs.dev/` — LCU getting-started + FAQ
- Community bot scripts on GitHub (search `lcu-driver`, `lcu-api`,
  `LCU-Instalock-Champion`) for real request/response shapes and observed
  error formats, since Riot's LCU has no official error spec.

**Ownership check**: `/lol-champions/v1/owned-champions-minimal` (GET, no
params) returns the logged-in account's owned champions only (list of
`{id, alias, name, active, ownership: {owned, rental, ...}, ...}`). Distinct
from `/lol-champions/v1/inventories/{summonerId}/champions-minimal`, which
returns the FULL roster regardless of ownership. Always check ownership
against the `owned-champions-minimal` set before PATCHing a pick — the LCU
does not reliably reject an unowned-champion pick at the HTTP layer in every
client version, so silently trusting a 2xx response is not safe. Check
`resp.status >= 400` on pick/pre-pick PATCH responses too and treat as a
rejected pick (fall through to the next configured layout), never assume
success from lack-of-exception alone.

## Known-fixed bugs (don't reintroduce)

- **Rune-picker shard mis-render on reopen** (`static/app.js`
  `openRunePicker`): the Defense stat-shard row has both `health` (5011) and
  `health scaling` (5001). Reverse-matching a stored config value with
  substring/`includes()` matches `health` before `health scaling` reaches
  its turn (`"healthscaling".includes("health")` is true), so opening the
  picker again visually shows the wrong shard selected even though the
  saved config is correct. Fix: exact normalized-string match only, never
  substring, for shard reverse-lookup.
- **False "Successfully picked" for unowned champions** (`main.py`
  `champ_select_changed`): the pick loop treated any non-exception PATCH as
  success and never checked LCU response status or actual champion
  ownership, so an account without a configured champion would pick it,
  "succeed" per the logs, and never fall through to the next layout. Fixed
  by fetching owned-champion IDs on connect and checking both ownership and
  response status before declaring a pick successful.
