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

- Online: 5 minutes per player, plus 3 seconds for each legal move or pass.
- Clock begins when both players connect. Server time decides timeout results;
  the browser clock is only a display.
- Disconnected players have 90 seconds to return, while their game clock continues.
  Before a game starts, a missing player causes cancellation rather than a win.
- Both passes enter scoring and pause the game clock. Players have 120 seconds
  to accept the marked score or resume play. If exactly one accepts and the other
  never responds, the latter forfeits. If neither accepts, the game is cancelled.
- Solo practice has no clock and does not affect the win record.
- Server downtime does not stop an already running wall-clock deadline.

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
