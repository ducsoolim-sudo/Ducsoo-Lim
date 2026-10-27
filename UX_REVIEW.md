# Mobile play review: 13GO, GoQuest and Baduk 2.0

Reviewed on 2026-10-26. Baduk 2.0 means the Monomob app listed by Kakao Games.

## Evidence and limits

- GoQuest official 13x13 web UI: https://questgames.net/go13
  The page exposes Play Online / Watch / My Page, move navigation and Export.
  In the research browser its styling and interactive loading did not complete;
  tapping Watch did not open a usable game. This is a limitation of this inspection,
  not a conclusion that the native app is broken. No account was created or game played.
- GoQuest official help: https://d26termck8rp2x.cloudfront.net/static/questhelp/android_help_go9-ja.html
  Documents time controls, reconnecting, rating and friendly games.
- Baduk 2.0 official listing: https://play.google.com/store/apps/details?id=com.monomob.baduk2&hl=ko
  Official promotional screenshots were inspected. The game screenshot shows a
  large board, a conspicuous last-move marker, distinct action buttons and player
  clocks. The lobby screenshot puts names, ranks, moves and spectator counts in
  each game row. These are promotional screenshots, not a hands-on native session.

## Changes implemented in the pending v1.1 branch

1. A tap previews a move by default; a separate Place button confirms it. Selected
   coordinates use A-H, J-N columns and 1-13 rows. Board coordinates are drawn too.
2. The choice can be adjusted or cleared. Quick-play is an explicit saved opt-out;
   switching modes never places a pending stone.
3. No second move or pass is sent while the first awaits the server. Turn changes,
   reconnects, server errors and game changes clear stale previews.
4. Both player clocks are above the board. The confirmation and action controls
   are below it. The mobile logo and header use less vertical space, and action
   buttons have a minimum 46px height.
5. Arrow keys choose points in confirmation mode; Enter confirms and Escape clears.

These are improvements selected from the comparison and our own code review.
Do not claim the competitors have this exact confirmation implementation.

## Verification

32 Python tests pass. Frontend checks cover preview-adjust-confirm, duplicate
input, rejection recovery, stale turn, disconnection, spectator/opponent access,
saved quick-play preference, mode changes, alternating solo colors and keyboard
selection. Structural assertions verify clocks before the canvas and controls after.
The cloud browser cannot open local files, so actual mobile rendering and device
interaction still need verification after a preview or deployment is available.

## Next priorities

Connect and verify the existing PostgreSQL instance, deploy v1.1, then test on a
phone. Next: in-app replay, then rating-based matching as the active player pool grows.
Keep the installation-free entry and simple primary navigation. Do not add social
feeds or tournaments before matching and game completion are reliable.

## Menu-first redesign — 2026-10-27 (not deployed)

User direction: keep the first screen to Play, Watch and My Page, minimize text,
and hold public deployment until the new version is ready.

- New visitors see a centered three-button home screen with no board, statistics
  or introductory copy. Play opens a small matching/practice screen.
- Display name and rules are optional, inside a collapsed disclosure. Practice
  explicitly says Both colors so it is not mistaken for an AI opponent.
- Matching shows elapsed waiting time and Cancel without an empty board.
- An actual game or spectator session opens the board; setup/sidebar is hidden.
  Player cards keep names, stone colors and clocks; redundant labels are hidden.
- Primary color is reserved for placement, with Pass and Resign secondary.
  Contextual scoring/reconnect deadlines remain visible below the board.
- Home navigation preserves the socket and game. Return to game restores the
  board. Saved room links bypass Home on startup.
- Existing frontend tests and 32 Python tests pass. Added navigation regressions
  cover fresh entry, all three destinations, waiting/matched states, saved room
  startup and returning without abandoning a game.
- These are source and DOM/behavior checks, not a real phone visual verification.
  No public deployment, Render setting change or production merge was performed.

## Visual redesign and solo input — 2026-10-27

Design specialist review requested by the user recommended paper/ink/moss,
a primary Play card and two smaller Watch/My Page cards, coherent SVG icons,
quiet player cards and minimal board chrome. Replaced stacked CSS with one
stylesheet implementing that system. Existing brand artwork is retained.

Solo play now defaults to immediate one-tap placement. Confirmation is optional
and has its own preference, separate from online games. Quick play hides the
inactive placement buttons so tapping is not confused with an uncommitted preview.
Seat identity remains stable; permission checks explicitly allow the solo owner
to play either color. The current turn comes from authoritative server state.

Added frontend eight-turn regression and real websocket integration checks for
alternating black/white stones, reconnect, pass and subsequent white move.
35 Python tests and frontend checks pass before preview deployment.

## Graphite / porcelain identity — 2026-10-27

Second specialist review responded to the user's request for a wholly new, modern
premium logo and interface. Removed the old raster logo, navy/gold badge and
card-based home. Added a custom path-based 13GO SVG wordmark, graphite backdrop,
porcelain board, quiet hairlines, typographic menu rows and restrained pale accent.
Home has no playable board: the paired-stone artwork is decorative and hidden
from accessibility. Essential controls retain readable text and focus outlines.
The solo one-tap behavior and turn validation remain unchanged.

## Two-tap X placement — 2026-10-27

Replaces both quick placement and preview-with-separate-button for all playing
modes. First tap selects a snapped intersection with an X, without sending a
move. Tapping another intersection moves X only. Tapping the currently selected
intersection again sends exactly one move. Previous quick-play preferences no
longer bypass this rule. Pending confirmation clears after turn changes, errors,
reconnects and game changes. Keyboard selection/Enter and Clear remain available.
No translucent preview stone is shown, so a selection cannot resemble a placed
stone. Added coverage for a scaled phone canvas and ambiguous taps near adjacent
intersections, as well as fresh confirmation after rejection and alternating solo
turns under the new interaction.

## Kaya board and crosshair — 2026-10-27

Replaced the selection X with a thin four-arm crosshair and center point aligned
with the board grid. The same-intersection second-tap confirmation is unchanged.
Board colors now use warm kaya-inspired golden wood with fine longitudinal
procedural grain, restrained contrast and brown grid lines. This is a drawn
wood material inspired by kaya, not a photograph of a particular wood specimen.
