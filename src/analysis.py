"""
analysis.py
Analyses a list of Hand objects and produces structured results for both
the per-session HTML report and the persistent SQLite profile database.

A hand is included in deep analysis if the hero faced at least one
voluntary decision beyond simply posting a blind (e.g. folding to a
raise, calling, betting, or raising).

7-2 Bounty EV:
  When a bounty is active and hero holds 7-2 offsuit, every call/bet/raise
  has hidden EV from the potential bounty payout. We add an expected bounty
  value to the EV calculation:

      bounty_ev = equity * total_bounty_available

  where total_bounty_available = bounty_per_player * (num_players_at_table - 1)
  This is added to the raw poker EV so the verdict correctly reflects that
  playing 7-2 aggressively can be +EV even with weak raw equity.

Usage:
    from parser import parse_log
    from analysis import analyse_session

    hands   = parse_log("my_session.csv", hero_id="PFiA37ihL9")
    session = analyse_session(hands, hero_id="PFiA37ihL9")
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations
from typing import Optional

from models import Action, ActionType, GameState, Hand, Position, Street


# ---------------------------------------------------------------------------
# Card utilities  (no external dependencies)
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "♠♥♦♣"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

def _card_to_int(card: str) -> int:
    rank, suit = card[0], card[1]
    return RANK_VAL[rank] * 4 + SUITS.index(suit)

FULL_DECK = list(range(52))


# ---------------------------------------------------------------------------
# Hand evaluator  (5-card → comparable tuple, higher = better)
# ---------------------------------------------------------------------------

def _hand_rank(cards: list[int]) -> tuple:
    best = None
    for combo in combinations(cards, 5):
        score = _eval5(combo)
        if best is None or score > best:
            best = score
    return best


def _eval5(cards: tuple[int, ...]) -> tuple:
    from collections import Counter
    ranks = sorted([c // 4 for c in cards], reverse=True)
    suits = [c % 4 for c in cards]
    is_flush = len(set(suits)) == 1

    is_straight = False
    straight_high = 0
    if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
        is_straight = True
        straight_high = ranks[0]
    elif ranks == [12, 3, 2, 1, 0]:  # wheel
        is_straight = True
        straight_high = 3

    counts = Counter(ranks)
    freq   = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda r: (counts[r], r), reverse=True)

    if is_straight and is_flush: return (8, straight_high)
    if freq[0] == 4:             return (7, groups[0], groups[1])
    if freq[0] == 3 and freq[1] == 2: return (6, groups[0], groups[1])
    if is_flush:                 return (5, ranks)
    if is_straight:              return (4, straight_high)
    if freq[0] == 3:             return (3, groups[0], groups[1:])
    if freq[0] == 2 and freq[1] == 2: return (2, groups[0], groups[1], groups[2])
    if freq[0] == 2:             return (1, groups[0], groups[1:])
    return (0, ranks)


def monte_carlo_equity(
    hole_cards: tuple[str, ...],
    board: list[str],
    num_opponents: int,
    num_simulations: int = 1000,
) -> float:
    """
    Estimate hero's equity via Monte Carlo simulation.

    Returns a float in [0, 1] representing win + tie/2 probability.
    """
    if not hole_cards or len(hole_cards) < 2:
        return 0.0

    hero_ints  = [_card_to_int(c) for c in hole_cards]
    board_ints = [_card_to_int(c) for c in board]
    known      = set(hero_ints + board_ints)
    deck       = [c for c in FULL_DECK if c not in known]

    cards_needed_on_board = 5 - len(board_ints)
    cards_per_opponent    = 2

    wins = 0.0
    for _ in range(num_simulations):
        sample = random.sample(deck, cards_needed_on_board + cards_per_opponent * num_opponents)
        runout_board = board_ints + sample[:cards_needed_on_board]
        opp_hands    = [
            sample[cards_needed_on_board + i * 2 : cards_needed_on_board + (i + 1) * 2]
            for i in range(num_opponents)
        ]
        hero_score = _hand_rank(hero_ints + runout_board)
        best_opp   = max(_hand_rank(h + runout_board) for h in opp_hands)

        if hero_score > best_opp:
            wins += 1.0
        elif hero_score == best_opp:
            wins += 0.5
    return wins / num_simulations


# ---------------------------------------------------------------------------
# Bounty EV helper
# ---------------------------------------------------------------------------

def _bounty_ev(
    equity: float,
    hand: Hand,
    state_before: GameState,
) -> float:
    """
    Expected bounty value in cents for a hero action on a 7-2 hand.

    If the bounty is active and hero holds 7-2, every chip hero puts in
    has a chance of winning the bounty. The expected value is:
        equity * bounty_per_player * (num_players_who_would_pay)

    We conservatively count only players currently in the hand as payers
    (folded players still pay in practice, but we can't know who folded
    preflop before this action).

    Returns 0 if the bounty is not active or hero doesn't hold 7-2.
    """
    if not hand.hero_has_72:
        return 0.0
    if not hand.bounty_config:
        return 0.0
    # Players at the table minus hero
    num_payers = len(hand.players) - 1
    total_bounty = hand.bounty_config.amount_per_player * num_payers
    return equity * total_bounty


# ---------------------------------------------------------------------------
# Decision verdict
# ---------------------------------------------------------------------------

class Verdict(Enum):
    GOOD     = "good"
    MARGINAL = "marginal"
    MISTAKE  = "mistake"
    NO_DATA  = "no_data"


@dataclass
class ActionAnalysis:
    """Analysis of a single hero action."""
    action: Action

    equity: Optional[float] = None
    pot_odds: Optional[float] = None
    ev_estimate: Optional[float] = None      # in BB (poker EV only)
    ev_with_bounty: Optional[float] = None   # in BB (including bounty EV)
    bounty_ev_bb: Optional[float] = None     # bounty component in BB

    bet_size_pct: Optional[float] = None
    spr: Optional[float] = None

    verdict: Verdict = Verdict.NO_DATA
    notes: list[str] = field(default_factory=list)

    @property
    def is_hero_bet_or_raise(self) -> bool:
        return self.action.action_type in {
            ActionType.BET, ActionType.RAISE, ActionType.ALL_IN
        }

    @property
    def is_hero_call(self) -> bool:
        return self.action.action_type == ActionType.CALL

    @property
    def is_hero_fold(self) -> bool:
        return self.action.action_type == ActionType.FOLD


@dataclass
class HandAnalysis:
    """Full analysis of a single hand."""
    hand: Hand
    action_analyses: list[ActionAnalysis] = field(default_factory=list)
    is_analysis_worthy: bool = False

    went_to_showdown: bool = False
    streets_reached: list[Street] = field(default_factory=list)
    net_bb: float = 0.0
    net_bb_excl_bounty: float = 0.0
    bounty_net_bb: float = 0.0
    peak_equity: Optional[float] = None
    worst_call_ev: Optional[float] = None

    @property
    def has_mistakes(self) -> bool:
        return any(a.verdict == Verdict.MISTAKE for a in self.action_analyses)

    @property
    def key_decisions(self) -> list[ActionAnalysis]:
        return [
            a for a in self.action_analyses
            if a.verdict in {Verdict.MISTAKE, Verdict.MARGINAL}
        ]

    @property
    def is_bounty_hand(self) -> bool:
        return self.hand.has_bounty()

    @property
    def hero_had_72(self) -> bool:
        return self.hand.hero_has_72


@dataclass
class SessionStats:
    """Aggregate statistics across all hands in a session."""

    total_hands: int = 0
    hands_analysed: int = 0
    bomb_pot_hands_skipped: int = 0   # PLO/bomb pot hands excluded from analysis

    vpip_hands: int = 0
    pfr_hands: int = 0
    three_bet_opps: int = 0
    three_bets: int = 0

    total_bets_raises: int = 0
    total_calls: int = 0

    total_ev_bb: float = 0.0
    negative_ev_calls: int = 0
    positive_ev_calls: int = 0

    # Bounty tracking
    bounty_hands_won: int = 0       # hands where hero won the bounty
    bounty_hands_paid: int = 0      # hands where hero paid bounty to someone
    bounty_total_won_bb: float = 0.0
    bounty_total_paid_bb: float = 0.0
    hero_72_hands: int = 0          # hands hero was dealt 7-2

    net_bb: float = 0.0
    net_bb_excl_bounty: float = 0.0
    showdown_hands: int = 0
    showdown_wins: int = 0

    net_bb_by_position: dict[str, float] = field(default_factory=dict)

    cbet_opportunities: int = 0
    cbets_made: int = 0

    @property
    def vpip(self) -> Optional[float]:
        return self.vpip_hands / self.total_hands if self.total_hands else None

    @property
    def pfr(self) -> Optional[float]:
        return self.pfr_hands / self.total_hands if self.total_hands else None

    @property
    def aggression_factor(self) -> Optional[float]:
        return self.total_bets_raises / self.total_calls if self.total_calls else None

    @property
    def three_bet_pct(self) -> Optional[float]:
        return self.three_bets / self.three_bet_opps if self.three_bet_opps else None

    @property
    def showdown_win_pct(self) -> Optional[float]:
        return self.showdown_wins / self.showdown_hands if self.showdown_hands else None

    @property
    def ev_per_hand(self) -> Optional[float]:
        return self.total_ev_bb / self.hands_analysed if self.hands_analysed else None

    @property
    def cbet_pct(self) -> Optional[float]:
        return self.cbets_made / self.cbet_opportunities if self.cbet_opportunities else None


@dataclass
class SessionAnalysis:
    """Top-level result of analysing a full session."""
    hand_analyses: list[HandAnalysis]
    stats: SessionStats
    hero_id: str
    big_blind_cents: int

    @property
    def worthy_hands(self) -> list[HandAnalysis]:
        return [h for h in self.hand_analyses if h.is_analysis_worthy]

    @property
    def mistake_hands(self) -> list[HandAnalysis]:
        return [h for h in self.worthy_hands if h.has_mistakes]

    @property
    def bounty_hands(self) -> list[HandAnalysis]:
        return [h for h in self.hand_analyses if h.is_bounty_hand]


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def _compute_verdict(
    aa: ActionAnalysis,
    hand: Hand,
    use_bounty_ev: bool = True,
) -> tuple[Verdict, list[str]]:
    """
    Apply heuristic rules to produce a verdict and notes.
    When use_bounty_ev is True and a bounty EV exists, the verdict uses
    the combined EV rather than raw poker EV.
    """
    notes: list[str] = []
    action = aa.action

    # Effective equity threshold adjusted by bounty when applicable
    # For 7-2 hands: raw equity threshold is lowered by the bounty contribution
    effective_required_eq = aa.pot_odds  # may be None

    bounty_note = ""
    if hand.hero_has_72 and hand.bounty_config and aa.bounty_ev_bb is not None:
        bounty_note = f" [+{aa.bounty_ev_bb:.2f}bb bounty EV included]"

    # ---- Folds ---------------------------------------------------------
    if action.action_type == ActionType.FOLD:
        if aa.equity is None:
            return Verdict.NO_DATA, notes
        if aa.pot_odds is None:
            return Verdict.GOOD, notes

        required_eq = aa.pot_odds

        # If bounty active and hero has 7-2, a fold loses future bounty EV
        # We lower the effective required equity by the bounty contribution
        effective_required = required_eq
        if aa.bounty_ev_bb is not None and aa.pot_odds is not None:
            # Convert bounty_ev_bb back to an equity-equivalent reduction
            # bounty_ev reduces the threshold by bounty_ev / (pot_after_call_in_bb)
            pot_after_bb = hand.to_bb(action.pot_before + action.amount) if action.amount else None
            if pot_after_bb and pot_after_bb > 0:
                effective_required = max(0, required_eq - aa.bounty_ev_bb / pot_after_bb)

        margin = aa.equity - effective_required

        if margin > 0.05:
            notes.append(
                f"Folded with {aa.equity:.1%} equity vs {effective_required:.1%} "
                f"required — calling was +EV.{bounty_note}"
            )
            return Verdict.MISTAKE, notes
        elif margin > -0.03:
            notes.append(
                f"Marginal fold: {aa.equity:.1%} equity vs {effective_required:.1%} required."
                f"{bounty_note}"
            )
            return Verdict.MARGINAL, notes
        else:
            notes.append(
                f"Correct fold: {aa.equity:.1%} equity vs {effective_required:.1%} required."
            )
            return Verdict.GOOD, notes

    # ---- Calls ---------------------------------------------------------
    if action.action_type == ActionType.CALL:
        if aa.equity is None or aa.pot_odds is None:
            return Verdict.NO_DATA, notes

        # Use bounty-adjusted EV if available
        ev = aa.ev_with_bounty if (use_bounty_ev and aa.ev_with_bounty is not None) else aa.ev_estimate
        required_eq = aa.pot_odds
        margin = aa.equity - required_eq

        if ev is not None and ev > 0:
            notes.append(
                f"Good call: {aa.equity:.1%} equity vs {required_eq:.1%} required "
                f"(EV: +{ev:.2f}bb).{bounty_note}"
            )
            return Verdict.GOOD, notes
        elif margin >= -0.03:
            notes.append(
                f"Marginal call: {aa.equity:.1%} equity vs {required_eq:.1%} required."
                f"{bounty_note}"
            )
            return Verdict.MARGINAL, notes
        else:
            notes.append(
                f"Negative EV call: {aa.equity:.1%} equity vs {required_eq:.1%} required "
                f"({margin:.1%} edge).{bounty_note}"
            )
            return Verdict.MISTAKE, notes

    # ---- Bets and raises -----------------------------------------------
    if action.action_type in {ActionType.BET, ActionType.RAISE, ActionType.ALL_IN}:
        if aa.equity is None:
            return Verdict.NO_DATA, notes

        # For 7-2 hands, effective equity is boosted by bounty expectation
        effective_equity = aa.equity
        if aa.bounty_ev_bb is not None and action.pot_before > 0:
            # Express bounty EV as an equity-equivalent boost
            pot_bb = hand.to_bb(action.pot_before)
            if pot_bb > 0:
                effective_equity = min(1.0, aa.equity + aa.bounty_ev_bb / pot_bb)

        if aa.bet_size_pct is not None:
            if aa.bet_size_pct > 1.5:
                notes.append(
                    f"Large sizing: {aa.bet_size_pct:.0%} of pot. "
                    "Consider whether this is appropriate for your range."
                )

        if hand.hero_has_72 and hand.bounty_config:
            notes.append(
                f"7-2 hand with bounty active: raw equity {aa.equity:.1%}, "
                f"effective equity ~{effective_equity:.1%} after bounty.{bounty_note}"
            )

        if effective_equity >= 0.55:
            notes.append(f"Betting/raising with strong equity ({effective_equity:.1%}).")
            return Verdict.GOOD, notes
        elif effective_equity >= 0.35:
            notes.append(f"Betting/raising with marginal equity ({effective_equity:.1%}).")
            return Verdict.MARGINAL, notes
        else:
            notes.append(
                f"Betting/raising with weak equity ({effective_equity:.1%}). "
                "If not a planned bluff, this may be a mistake."
            )
            return Verdict.MISTAKE, notes

    # ---- Check ---------------------------------------------------------
    if action.action_type == ActionType.CHECK:
        if aa.equity is not None and aa.equity > 0.75:
            notes.append(
                f"Checked with high equity ({aa.equity:.1%}). "
                "May be leaving value on the table."
            )
            return Verdict.MARGINAL, notes
        return Verdict.NO_DATA, notes

    return Verdict.NO_DATA, notes


# ---------------------------------------------------------------------------
# Core analysis logic
# ---------------------------------------------------------------------------

def _is_analysis_worthy(hand: Hand) -> bool:
    if not hand.hero_id:
        return False
    voluntary = [
        a for a in hand.actions
        if a.player_id == hand.hero_id and a.is_voluntary
    ]
    if not voluntary:
        return False
    # Single preflop fold with no prior raise → exclude
    if len(voluntary) == 1 and voluntary[0].action_type == ActionType.FOLD:
        fold = voluntary[0]
        state = hand.state_before(fold.sequence_index)
        if state and state.current_bet <= hand.big_blind:
            return False
    return True


def _analyse_hand(hand: Hand, num_simulations: int = 800) -> HandAnalysis:
    ha = HandAnalysis(hand=hand)
    ha.is_analysis_worthy = _is_analysis_worthy(hand)
    ha.net_bb              = hand.hero_net_bb()
    ha.net_bb_excl_bounty  = hand.hero_net_excl_bounty_bb()
    ha.bounty_net_bb       = hand.bounty_net_bb(hand.hero_id) if hand.hero_id else 0.0

    if not hand.hero_id or not hand.hero:
        return ha

    ha.streets_reached = [s for s in Street if hand.actions_on_street(s)]

    # Showdown detection: hero was still in on the river
    ha.went_to_showdown = any(
        a.player_id == hand.hero_id and a.street == Street.RIVER
        and a.action_type in {
            ActionType.CALL, ActionType.CHECK, ActionType.BET,
            ActionType.RAISE, ActionType.ALL_IN
        }
        for a in hand.actions
    ) and bool(hand.board)

    if not ha.is_analysis_worthy:
        return ha

    hero = hand.hero
    if not hero.hole_cards or len(hero.hole_cards) < 2:
        return ha

    peak_equity   = 0.0
    worst_call_ev = 0.0

    for action in hand.actions:
        if action.player_id != hand.hero_id or not action.is_voluntary:
            continue

        state_before = hand.state_before(action.sequence_index)
        if not state_before:
            continue

        board_at_action = list(state_before.board)
        num_opponents   = max(1, state_before.num_players_remaining - 1)

        equity = monte_carlo_equity(
            hole_cards=hero.hole_cards,
            board=board_at_action,
            num_opponents=num_opponents,
            num_simulations=num_simulations,
        )

        if equity > peak_equity:
            peak_equity = equity

        call_amount = action.amount if action.action_type in {
            ActionType.CALL, ActionType.ALL_IN
        } else 0
        pot_odds = None
        if call_amount > 0:
            pot_odds = call_amount / (state_before.pot.total + call_amount)

        spr      = state_before.spr(hand.hero_id)
        bet_pct  = action.bet_size_pct()

        aa = ActionAnalysis(
            action=action,
            equity=equity,
            pot_odds=pot_odds,
            spr=spr,
            bet_size_pct=bet_pct,
        )

        # Bounty EV (cents → BB)
        b_ev_cents = _bounty_ev(equity, hand, state_before)
        if b_ev_cents > 0:
            aa.bounty_ev_bb = hand.to_bb(int(b_ev_cents))

        # Poker EV on calls
        if action.action_type == ActionType.CALL and pot_odds is not None:
            pot_after    = state_before.pot.total + call_amount
            ev_cents     = equity * pot_after - (1 - equity) * call_amount
            aa.ev_estimate = hand.to_bb(int(ev_cents))
            if aa.bounty_ev_bb is not None:
                aa.ev_with_bounty = aa.ev_estimate + aa.bounty_ev_bb
            else:
                aa.ev_with_bounty = aa.ev_estimate
            if (aa.ev_with_bounty or aa.ev_estimate or 0) < worst_call_ev:
                worst_call_ev = aa.ev_with_bounty or aa.ev_estimate

        aa.verdict, aa.notes = _compute_verdict(aa, hand)
        ha.action_analyses.append(aa)

    ha.peak_equity   = peak_equity if peak_equity > 0 else None
    ha.worst_call_ev = worst_call_ev if worst_call_ev < 0 else None
    return ha


def _build_session_stats(
    hand_analyses: list[HandAnalysis],
    hero_id: str,
) -> SessionStats:
    stats = SessionStats()

    for ha in hand_analyses:
        hand = ha.hand
        if hand.hero_id != hero_id:
            continue

        stats.total_hands        += 1
        stats.net_bb             += ha.net_bb
        stats.net_bb_excl_bounty += ha.net_bb_excl_bounty

        # Bounty tracking
        if hand.hero_id in hand.bounty_won:
            stats.bounty_hands_won    += 1
            stats.bounty_total_won_bb += ha.bounty_net_bb
        if hand.hero_id in hand.bounty_paid:
            stats.bounty_hands_paid   += 1
            stats.bounty_total_paid_bb += ha.bounty_net_bb  # negative for paid
        if hand.hero_has_72:
            stats.hero_72_hands += 1

        # Positional net BB
        if hand.hero and hand.hero.position:
            pos = hand.hero.position.value
            stats.net_bb_by_position[pos] = (
                stats.net_bb_by_position.get(pos, 0.0) + ha.net_bb
            )

        if ha.went_to_showdown:
            stats.showdown_hands += 1
            if ha.net_bb > 0:
                stats.showdown_wins += 1

        if not ha.is_analysis_worthy:
            continue

        stats.hands_analysed += 1

        # VPIP
        preflop_actions = hand.hero_actions_on_street(Street.PREFLOP)
        voluntary_preflop = [
            a for a in preflop_actions
            if a.action_type not in {
                ActionType.FOLD, ActionType.POST_BB, ActionType.POST_SB,
                ActionType.POST_STRADDLE,
            }
        ]
        if voluntary_preflop:
            stats.vpip_hands += 1

        # PFR
        if any(
            a.action_type in {ActionType.RAISE, ActionType.BET, ActionType.ALL_IN}
            for a in preflop_actions
        ):
            stats.pfr_hands += 1

        # 3bet opportunities
        first_hero_pf = next(
            (a for a in preflop_actions if a.is_voluntary), None
        )
        if first_hero_pf:
            sb = hand.state_before(first_hero_pf.sequence_index)
            if sb and sb.current_bet > hand.big_blind:
                stats.three_bet_opps += 1
                if first_hero_pf.action_type in {
                    ActionType.RAISE, ActionType.BET, ActionType.ALL_IN
                }:
                    stats.three_bets += 1

        # Aggression factor
        for aa in ha.action_analyses:
            if aa.action.action_type in {
                ActionType.BET, ActionType.RAISE, ActionType.ALL_IN
            }:
                stats.total_bets_raises += 1
            elif aa.action.action_type == ActionType.CALL:
                stats.total_calls += 1

        # EV tracking — use bounty-adjusted EV where available
        for aa in ha.action_analyses:
            if aa.action.action_type == ActionType.CALL:
                ev = aa.ev_with_bounty if aa.ev_with_bounty is not None else aa.ev_estimate
                if ev is not None:
                    stats.total_ev_bb += ev
                    if ev < 0:
                        stats.negative_ev_calls += 1
                    else:
                        stats.positive_ev_calls += 1

        # C-bet
        pf_raises = [
            a for a in preflop_actions
            if a.action_type in {ActionType.RAISE, ActionType.BET, ActionType.ALL_IN}
        ]
        flop_actions = hand.hero_actions_on_street(Street.FLOP)
        if pf_raises and flop_actions:
            stats.cbet_opportunities += 1
            if any(
                a.action_type in {ActionType.BET, ActionType.RAISE, ActionType.ALL_IN}
                for a in flop_actions
            ):
                stats.cbets_made += 1

    return stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_session(
    hands: list[Hand],
    hero_id: str,
    num_simulations: int = 800,
) -> SessionAnalysis:
    """
    Analyse a full session of hands.

    Args:
        hands:           Parsed Hand objects from parse_log().
        hero_id:         Stable PokerNow player hash for the hero.
        num_simulations: Monte Carlo iterations per equity calculation.
                         800 gives ~2% accuracy at good speed.

    Returns:
        SessionAnalysis with per-hand and aggregate results.
    """
    hand_analyses = []
    bomb_pots_skipped = 0
    for hand in hands:
        if hand.hero_id == hero_id:
            if hand.is_bomb_pot:
                bomb_pots_skipped += 1
                continue
            ha = _analyse_hand(hand, num_simulations=num_simulations)
            hand_analyses.append(ha)

    stats = _build_session_stats(hand_analyses, hero_id)
    stats.bomb_pot_hands_skipped = bomb_pots_skipped

    bbs = [h.hand.big_blind for h in hand_analyses if h.hand.big_blind]
    most_common_bb = max(set(bbs), key=bbs.count) if bbs else 50

    return SessionAnalysis(
        hand_analyses=hand_analyses,
        stats=stats,
        hero_id=hero_id,
        big_blind_cents=most_common_bb,
    )