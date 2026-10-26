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
