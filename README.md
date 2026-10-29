# 13GO v1.1

A single-worker 13×13 Go service with live spectators and SGF downloads.

## Run and verify

Use Python 3.12. Install `requirements.txt`, then run `python server.py`.
For development only, SQLite stores games in `go13.sqlite3` (or `ROOM_DB_PATH`).
Run `python -m unittest -q` and `node test_profile.cjs`.

## Production storage and deployment

Set `DATABASE_URL` as a secret on the existing Render web service. Use an existing
available PostgreSQL instance in the same region and workspace, with its internal
connection URL. Do not put the URL in source control or logs. Verify the instance's
expiry and plan before using it; no paid upgrade is authorized by this release.
The server refuses to start on Render without PostgreSQL so an ephemeral local
file cannot be mistaken for durable storage.

The app creates only its own `go13_rooms` and `go13_games` tables. Rooms contain
private seat tokens; completed-game archives exclude tokens. Saves are transactional
and use revision checks to reject stale writers during a deployment. A failed save
is not acknowledged as a successful move. `/health` checks database connectivity
and returns the running version and storage backend.

Use one instance / one Python worker. This is not a multi-worker real-time service.
The revision guard protects against stale writes during rollout but does not replace
cross-instance live messaging. During a rollout, reconnect clients after closing the
old server; confirm restoration and health on the new instance.

## Rules and time

- New online games: 5 minutes plus three 30-second Japanese overtime periods;
  no per-move increment. Saved older games retain their Fischer clock policy.
- The opening action must arrive within 30 seconds after both players connect.
- During main time, warn at 60 seconds and forfeit after 90 seconds without an
  action. Once overtime begins, its period rules apply instead.
- Reconnecting preserves the active turn deadline, departure count, and cumulative
  offline time. A >=10-second outage counts once; three episodes forfeit. The
  10-second threshold and 90-second cumulative return budget are implementation
  defaults pending final operational approval, distinct from the agreed three-
  departure rule. Explicit leave UI/events are not yet implemented.
- Prepared automatic scores have a 30-second review deadline. Analysis errors or
  unresolved scoring do not start a review-forfeit deadline. One acceptance and
  one nonresponse forfeits; neither accepting cancels (operational default).
- Solo practice has no clock and does not affect the win record.
- Restored games freeze at the durable checkpoint until both seats reconnect.
  Hosted persistence acceptance still requires a separate durable test store.
- Rules are versioned in `rules_policy.py`; `test_manners.py` exercises boundary,
  overtime, repeated-reconnect, persistence, and scoring timeout behavior.
- Product decisions and status are maintained in the separately saved **13GO
  운영·개발 매뉴얼**, version 0.1. Proposed rating/temperature formulas remain
  unimplemented; this change does not activate Google sign-in or deploy.

Waiting searches can be cancelled. If matching wins the cancellation race, the
server rejects cancellation and keeps the matched game intact. The guest's last
room link and seat token stay in the same browser for reconnecting after a reload.
Guest identity and win summaries are not synced across devices in v1.1.

Finished room links are kept for 30 days, inactive active rooms for 7 days, and
unused waiting/cancelled rooms for 3 minutes. Completed game archives remain in
the database; backups and long-term retention depend on the database operator.

## Release status

v1.0 is deployed at https://thirteen-go-online.onrender.com/.
v1.1 is implemented and locally tested. Production database connection,
Deployment and live restart verification remain pending the Render database connection.
See UX_REVIEW.md for the mobile comparison, implemented changes and verification limits.

## Isolated interface preview

The `test-menu-v11` branch is deployed to a separate free web service. Only that
service sets `GO13_PREVIEW=true` and `ROOM_DB_PATH=/tmp/go13-preview.sqlite3`.
This explicitly allows disposable SQLite storage on Render, without connecting
to production Postgres. Rooms can reset on sleep, restart or redeploy. Production
still refuses to start without `DATABASE_URL`. The preview HTML is marked Test
and noindex. This is a functional game preview, not durability acceptance testing.

### Google account sign-in

Guest play remains available. My Page uses Google's official sign-in button only
when `GOOGLE_CLIENT_ID` is configured. The server verifies the signed Google ID
token, audience, issuer, expiry, verified email, and nonce before issuing an
HttpOnly session cookie. Google access/refresh tokens and email addresses are not
stored. Sessions are revocable; game results come from the server, never from a
client-uploaded win count. Existing guest history remains local and is not imported
as verified account results.

To activate on the isolated test service:

1. In Google Cloud Console, configure Google Auth Platform branding/audience and
   create an OAuth client of type **Web application**.
2. Add authorized JavaScript origin `https://thirteen-go-test.onrender.com`.
   This implementation uses Google Identity Services' JavaScript callback;
   no redirect URI or client secret is required.
3. Set `GOOGLE_CLIENT_ID` to that client's public ID and set
   `PUBLIC_ORIGIN=https://thirteen-go-test.onrender.com` on the test service.
4. Redeploy only `test-menu-v11`. Verify a real Google login, sign-out, and
   cross-device results before enabling production. If Google's project is in
   Testing mode, add the participating Google accounts as test users.

The test service still uses disposable SQLite. Account sessions and results can
reset on sleep/redeploy; production account persistence requires PostgreSQL via
`DATABASE_URL`. Do not attach the test service to the production database.

Checks: `node test_profile.cjs` and `python -m unittest discover -q`.

### Territory scoring work in progress

New rooms use Japanese-style territory plus prisoners, 6.5 komi, and simple ko.
Existing room snapshots without a rules field retain their Chinese scoring.
SGF records carry the room's rules. Shared dame excludes the bordering groups'
eyes from territory; players must finish dame before accepting the result.

On two passes, Benson's pass-alive test identifies safe enclosing groups. A
bounded local search checks pockets of at most nine points, with the defender
moving first, and automatically marks only forced captures found within its
budget. Large fights, ko cycles, and uncertain life/death remain unmarked and
produce a review notice. Corrections clear both players' prior approvals.

This is **not a full Japanese life/death adjudicator**. In particular, rare ko,
seki, bent-four, and replacement-life cases require specialist-engine validation.
Do not advertise fully automatic dead-stone handling or release this as finished
Japanese rules until that validation/integration is complete. This implementation
has not yet been uploaded to the test service.

### KataGo-assisted adjudication (development, not yet deployed)

`adjudicator.py` runs KataGo locally as a subprocess; game data is not sent to an
external analysis provider. Two searches (256 and 1024 visits) use the actual move
history, Japanese rules, and Black's perspective. Ownership/deviation arrays are
validated, whole groups must agree across both searches, neutral points stay
neutral, and the calculated territory/prisoner score must agree with the engine.
Low confidence, disagreement, invalid output, and engine failure block automatic
confirmation. The opponent can resume play; manual marking remains an explicit
fallback. Analysis runs outside the global room lock, with one engine at a time,
a 60-second queue-plus-runtime limit, process cleanup, and stale-result rejection.
Analysis is rescheduled after server restart. Failures do not cause review-time
forfeits.

Set `KATAGO_BINARY` and `KATAGO_MODEL` to local absolute paths; optionally set
`KATAGO_TIMEOUT`. `python install_engine.py /absolute/runtime/path` downloads
checksum-pinned KataGo 1.16.3 Eigen and a **small upstream regression-test model**.
It is for development smoke tests only, not production adjudication. A stronger,
validated model and adequate CPU/RAM are required before deployment. Engine
binaries/models are runtime dependencies, not committed to the application repo.
Keep upstream license notices with any redistributed binaries/models.

Run `KATAGO_BINARY=... KATAGO_MODEL=... python check_engine.py` for real-engine
checks. The current small-model run identified the enclosed dead stone and kept
the shared-liberty groups, but all three fixtures remained `review`, including an
unfinished double-pass position. This verifies the uncertainty guard, **not** full
automatic scoring accuracy. A stronger model is now available through the checksum-pinned upstream GitHub
release (`install_engine.py PATH --strong`). Initial CPU validation did not pass
the automatic-acceptance gate; no release deployment has been completed.

Outstanding release gates: curated Japanese bent-four/ko/seki/replacement-life and
no-result fixtures, a stronger-model regression run, ordinary completed-game
acceptance rate, latency/memory load tests, and an explicit policy for exceptional
unresolved positions. KataGo's Japanese-like rules are not a mathematical oracle
for every official Japanese ruling; do not advertise a guaranteed all-position
fully automatic referee.

### One-person online testing (preview only)

On the test service, choose **Play → Play test opponent**. A separate lightweight
opponent joins through the same WebSocket handler as a real player, so server
clocks, turn permissions, reconnect, resign and rematch can be tested by one
person. This is not a strength-rated AI. Its rooms are private and excluded from
account and browser results. The endpoint returns 404 unless `GO13_PREVIEW=true`;
it does not add bots to the ordinary Find a match queue. Finished bots wait up to
two minutes for rematch before disconnecting. Server shutdown cancels bot clients.

Home buttons contain only their names. Settings & rules live in My Page.
Original company/app identity concepts are in `BRAND_REVIEW.md` and
`brand-directions.svg`; no company name or replacement app logo is final.

### Unsettled score safeguard (2026-10-28)
A Japanese position with unresolved groups cannot be confirmed or exposed as a
provisional winner/score. With no configured engine, two passes in such a position
automatically continue play, preserve the board/clock and show a short notice.
This avoids treating zero enclosed territory plus komi as a finished result.
It is a conservative fallback, not complete automatic Japanese adjudication.

### Current automatic adjudication policy (2026-10-29)
For Japanese rooms, final confirmation requires a verified `ready` verdict.
The ordinary finish fast path requires all original groups to be Benson
pass-alive and every empty region single-color bounded; dead stones, dame,
seki, ko-dependent, empty and unfinished positions cannot use it. Neural engine
estimates retain all existing confidence gates. Public manual dead-stone changes
are rejected. Without a configured engine, or on an uncertain/failed analysis,
the game continues with its board and remaining time preserved. Only verified
results start the 30-second confirmation timer. During checking, no preliminary
score or confirm control is shown. This current policy supersedes the older
manual-fallback development descriptions above; full Japanese adjudication is
not yet a completed release feature.


## Restart recovery validation (2026-10-29)
Restored online games freeze at the durable checkpoint until both seats reconnect. First-action, idle, overtime, review and absence timers exclude server downtime and recovery waiting. Pre-existing absence remains chargeable. Unsettled adjudication waits for both seats before resuming. See `test_recovery.py` and run `python verify_restart_process.py` for a real killed-process restart check (31-second one-seat wait, board/token recovery and a legal next move). The latter uses a temporary local database. The disposable hosted preview cannot establish durable deployment recovery; a separate persistent test database remains required.


## Preview opponent tactics (2026-10-29)
The unrated preview opponent now prioritizes captures, escaping atari, connecting groups, preserving eyes and third/fourth-line development. A bounded ten-candidate tactical reply check penalizes immediate captures and atari. It honors the previous-position ko restriction and only answers a human pass with a pass when the ordinary settled-position proof succeeds (otherwise it keeps playing). Move selection runs in a thread so it does not block the server event loop. This improves basic tactics; it is not a KataGo-strength opponent or a certified kyu/dan level. Seven tactical regression cases and the actual socket/rematch checks cover this change.


## Stable identity and profile policy (2026-10-29)
`/api/profile` owns the saved display name and declared initial rank. A profile ID is immutable. The first display-name setup is allowed once; subsequent changes are separated by 30 days and blocked while matching/playing/scoring. An initial rank from18kyu through5dan is required for a new human online seat; practice/test-opponent play is exempt. The declared rank locks when the first human match starts. It is self-reported, not a verified rating; automatic promotions/demotions remain unimplemented. Room names come from the stored profile and cannot be overridden by client payloads. Google accounts use a stable account identity; guests use an HttpOnly cookie and can become a new guest by clearing browser data. Hosted preview storage is still disposable. No new Google credentials or durable hosted storage are activated by this change.
