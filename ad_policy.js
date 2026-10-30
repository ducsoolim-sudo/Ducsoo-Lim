/* Trial between-game ad policy. This module never loads an SDK or displays UI.
 * Integrators must recheck eligibility immediately before invoking an ad SDK,
 * before joining a queue/room. Never pause a running online game for an ad.
 * Call recordDisplayed only from an SDK callback confirming actual display;
 * a request, no-fill, timeout or SDK failure must not consume the frequency cap.
 * A future integration must persist state per local profile and treat missing
 * SDK/disabled policy as an immediate continuation of the New game action.
 */
(function (root) {
  'use strict';
  const TEN_MINUTES = 10 * 60 * 1000;
  class BetweenGameAdPolicy {
    constructor({enabled = false} = {}) {
      this.enabled = enabled === true;
      this.completed = new Set();
      this.gamesSinceDisplay = 0;
      this.lastDisplayedAt = null;
      this.pendingGameId = null;
    }

    static humanFinished(game, role) {
      return !!(game && typeof game.gameId === 'string' && game.gameId
        && game.status === 'finished'
        && ['score', 'resign'].includes(game.result?.reason)
        && !game.solo && !game.testBot
        && (role === 'black' || role === 'white')
        && game.players?.black && game.players?.white);
    }

    recordCompleted(game, role) {
      if (!BetweenGameAdPolicy.humanFinished(game, role)
          || this.completed.has(game.gameId)) return false;
      this.completed.add(game.gameId);
      this.gamesSinceDisplay += 1;
      return true;
    }

    eligible(context, now) {
      const {game, role, action, resultConfirmed, matching, recovering,
        connectedToActiveGame, rematchRequested} = context || {};
      return this.enabled && Number.isFinite(now) && now >= 0
        && this.pendingGameId === null
        && BetweenGameAdPolicy.humanFinished(game, role)
        && this.completed.has(game.gameId)
        && action === 'new-game' && resultConfirmed === true
        && matching === false && recovering === false
        && connectedToActiveGame === false && rematchRequested === false
        && !(game.clock?.recovering)
        && !(game.rematch?.length)
        && this.gamesSinceDisplay >= 2
        && (this.lastDisplayedAt === null
          || now - this.lastDisplayedAt >= TEN_MINUTES);
    }

    begin(context, now) {
      if (!this.eligible(context, now)) return false;
      this.pendingGameId = context.game.gameId;
      return true;
    }

    recordDisplayed(gameId, now) {
      if (!this.enabled || typeof gameId !== 'string' || !gameId
          || this.pendingGameId === null || this.pendingGameId !== gameId
          || !Number.isFinite(now) || now < 0
          || (this.lastDisplayedAt !== null && now < this.lastDisplayedAt)) return false;
      this.lastDisplayedAt = now;
      this.gamesSinceDisplay = 0;
      this.pendingGameId = null;
      return true;
    }

    cancel() {
      this.pendingGameId = null;
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = BetweenGameAdPolicy;
  else root.BetweenGameAdPolicy = BetweenGameAdPolicy;
})(typeof globalThis !== 'undefined' ? globalThis : this);
