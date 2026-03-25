"""
parser.py
Parses a PokerNow CSV log file into a list of Hand objects.

PokerNow CSV format:
  - Three columns: entry, at, order
  - Rows are ordered NEWEST first — must be reversed before processing
  - A session file may contain multiple blind levels and config changes
  - Chip amounts are dollar strings (e.g. "1.75") — converted to cents (int)
  - Player identity format: "Display Name @ HASH" — hash is the stable ID

Chip storage: all amounts stored as integer cents (1 unit = $0.01)
  e.g. "$0.50" → 50,  "$1.75" → 175

7-2 Bounty:
  Bounty payments appear in the log AFTER the ending hand marker for the
  hand that triggered them. The grouper attaches them as suffix lines to
  the correct (previous) hand rather than prefix lines to the next hand.
  The parser then reads those suffix lines and populates Hand.bounty_won
  and Hand.bounty_paid accordingly.

Usage:
    from parser import parse_log
    hands = parse_log("data/my_session.csv", hero_id="hL2HOafVVY")
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import (
    Action, ActionType, BountyConfig, GameState, Hand, Player,
    Position, Pot, SidePot, Street,
)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_HAND_START = re.compile(
    r"-- starting hand #(\d+) \(id: ([a-z0-9]+)\)\s+"
    r"No Limit Texas Hold'em \((dealer: \"(.+?) @ ([A-Za-z0-9_\-]+)\"|dead button)\) --"
)
RE_HAND_END = re.compile(r"-- ending hand #(\d+) --")

RE_PLAYER_STACKS = re.compile(r"Player stacks: (.+)")
RE_SINGLE_STACK  = re.compile(r'#(\d+) "(.+?) @ ([A-Za-z0-9_\-]+)" \(([0-9.]+)\)')

RE_YOUR_HAND = re.compile(
    r"Your hand is ([2-9TJQKA][♠♥♦♣])"
    r"(?:, ([2-9TJQKA][♠♥♦♣]))"
    r"(?:, ([2-9TJQKA][♠♥♦♣]))?"
    r"(?:, ([2-9TJQKA][♠♥♦♣]))?"
)

RE_FLOP  = re.compile(r"Flop:\s+\[([2-9TJQKA][♠♥♦♣]), ([2-9TJQKA][♠♥♦♣]), ([2-9TJQKA][♠♥♦♣])\]")
RE_TURN  = re.compile(r"Turn: .+\[([2-9TJQKA][♠♥♦♣])\]")
RE_RIVER = re.compile(r"River: .+\[([2-9TJQKA][♠♥♦♣])\]")

RE_PLAYER  = r'"(.+?) @ ([A-Za-z0-9_\-]+)"'
RE_AMOUNT  = r"([0-9]+(?:\.[0-9]+)?)"

RE_POST_SB         = re.compile(RE_PLAYER + r" posts a small blind of "        + RE_AMOUNT)
RE_POST_BB         = re.compile(RE_PLAYER + r" posts a big blind of "          + RE_AMOUNT)
RE_POST_MISSED_BB  = re.compile(RE_PLAYER + r" posts a missed big blind of "   + RE_AMOUNT)
RE_POST_MISSING_SB = re.compile(RE_PLAYER + r" posts a missing small blind of "+ RE_AMOUNT)
RE_POST_STR        = re.compile(RE_PLAYER + r" posts a straddle of "           + RE_AMOUNT)
RE_FOLD            = re.compile(RE_PLAYER + r" folds")
RE_CHECK           = re.compile(RE_PLAYER + r" checks")
RE_CALL            = re.compile(RE_PLAYER + r" calls "                         + RE_AMOUNT)
RE_BET             = re.compile(RE_PLAYER + r" bets "                          + RE_AMOUNT)
RE_RAISE           = re.compile(RE_PLAYER + r" raises to "                     + RE_AMOUNT)
RE_ALL_IN_BET      = re.compile(RE_PLAYER + r" bets "   + RE_AMOUNT + r" and go all in")
RE_ALL_IN_RAISE    = re.compile(RE_PLAYER + r" raises to " + RE_AMOUNT + r" and go all in")
RE_ALL_IN_CALL     = re.compile(RE_PLAYER + r" calls "  + RE_AMOUNT + r" and go all in")

RE_UNCALLED  = re.compile(r"Uncalled bet of " + RE_AMOUNT + r' returned to ' + RE_PLAYER)
RE_COLLECTED = re.compile(RE_PLAYER + r" collected " + RE_AMOUNT + r" from pot")
RE_SHOWS     = re.compile(RE_PLAYER + r" shows a ([2-9TJQKA][♠♥♦♣])(?:, ([2-9TJQKA][♠♥♦♣]))?")

RE_SB_CHANGE = re.compile(r"The game's small blind was changed from [0-9.]+ to ([0-9.]+)\.")
RE_BB_CHANGE = re.compile(r"The game's big blind was changed from [0-9.]+ to ([0-9.]+)\.")

# Game type — PokerNow logs a config change when switching to/from PLO
# e.g. "* Game Type: NLH » PLO" or "* Game Type: PLO » NLH"
RE_GAME_TYPE = re.compile(r"\* Game Type: \w+ » (\w+)", re.IGNORECASE)

# Ante post — every player posts before a bomb pot
RE_POST_ANTE = re.compile(RE_PLAYER + r" posts an ante of " + RE_AMOUNT)

RE_DEAD_SB = re.compile(r"^Dead Small Blind$")

# Bounty patterns
RE_BOUNTY_CONFIG  = re.compile(r"\* 7-2 bounty: off » ([0-9]+)")
RE_BOUNTY_PAID    = re.compile(RE_PLAYER + r" paid " + RE_AMOUNT + r" for the .+? bounty to " + RE_PLAYER)
RE_BOUNTY_WON     = re.compile(RE_PLAYER + r" collected " + RE_AMOUNT + r" from the .+? bounty")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_cents(amount_str: str) -> int:
    return round(float(amount_str) * 100)

def _parse_player_ref(name: str, hash_: str) -> tuple[str, str]:
    return hash_.strip(), name.strip()

def _parse_timestamp(at_str: str) -> datetime:
    return datetime.fromisoformat(at_str.replace("Z", "+00:00"))

def _parse_card(card_str: str) -> str:
    return card_str.strip()

def _is_72_offsuit(hole_cards: tuple[str, ...]) -> bool:
    """Return True if the two hole cards are 7 and 2 of different suits."""
    if len(hole_cards) != 2:
        return False
    ranks = {c[0] for c in hole_cards}
    suits = {c[1] for c in hole_cards}
    return ranks == {'7', '2'} and len(suits) == 2


# ---------------------------------------------------------------------------
# Hand block grouping
# ---------------------------------------------------------------------------

@dataclass
class _RawHand:
    """
    A raw hand block. Lines are split into:
      prefix_lines  — between-hand lines that arrived before the start marker
                      (blind changes, player joins, etc.)
      lines         — lines that belong to the hand itself (start → end inclusive)
      suffix_lines  — lines that arrived after the ending marker for THIS hand
                      (bounty payments belong here, not as prefix to the next hand)
    """
    start_entry: str
    timestamp: datetime
    prefix_lines: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    suffix_lines: list[str] = field(default_factory=list)


def _group_hands(rows: list[tuple[str, str]]) -> list[_RawHand]:
    """
    Split chronologically-ordered (entry, at) rows into per-hand blocks.

    Key behaviour:
    - Lines between hands that precede the NEXT start marker are stored as
      prefix_lines on the new hand (blind changes etc. need to update session
      state before parsing that hand).
    - Lines that follow the ending marker of a hand — before the next start
      marker — are stored as suffix_lines on the PREVIOUS hand (bounty lines
      live here).
    """
    hands: list[_RawHand] = []
    pending_prefix: list[str] = []
    current: Optional[_RawHand] = None
    hand_ended: bool = False   # True after we see an ending marker

    for entry, at in rows:
        if RE_HAND_START.match(entry):
            # Flush any suffix lines accumulated since the last end marker
            # into the completed previous hand, then start new hand.
            if current is not None:
                hands.append(current)
            ts = _parse_timestamp(at)
            current = _RawHand(
                start_entry=entry,
                timestamp=ts,
                prefix_lines=pending_prefix,
            )
            pending_prefix = []
            hand_ended = False

        elif RE_HAND_END.match(entry):
            if current is not None:
                current.lines.append(entry)
                hand_ended = True
            # Don't append to hands yet — suffix lines may follow

        else:
            if current is None:
                # Before any hand starts
                pending_prefix.append(entry)
            elif hand_ended:
                # After the ending marker — these belong to the current hand as suffix
                current.suffix_lines.append(entry)
            else:
                current.lines.append(entry)

    # Don't forget the last hand
    if current is not None:
        hands.append(current)

    return hands


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class _SessionState:
    small_blind: int = 0
    big_blind:   int = 0
    bounty_config: Optional[BountyConfig] = None
    game_type: str = "NLH"   # "NLH" or "PLO" — updated by config change lines


def _apply_session_updates(line: str, state: _SessionState) -> None:
    m = RE_SB_CHANGE.search(line)
    if m:
        state.small_blind = _to_cents(m.group(1))
    m = RE_BB_CHANGE.search(line)
    if m:
        state.big_blind = _to_cents(m.group(1))
    m = RE_BOUNTY_CONFIG.search(line)
    if m:
        amount = int(m.group(1))
        state.bounty_config = BountyConfig(amount_per_player=amount)
    m = RE_GAME_TYPE.search(line)
    if m:
        state.game_type = m.group(1).upper()


# ---------------------------------------------------------------------------
# Bounty suffix parser
# ---------------------------------------------------------------------------

def _parse_bounty_suffix(suffix_lines: list[str], hand: Hand) -> None:
    """
    Parse the post-hand bounty lines and populate hand.bounty_won / bounty_paid.
    Also sets hand.hero_has_72 if hero won the bounty and held 7-2.
    """
    for line in suffix_lines:
        # "PLAYER paid AMT for the 7-2 bounty to WINNER"
        m = RE_BOUNTY_PAID.match(line)
        if m:
            payer_id = m.group(2).strip()
            amount   = _to_cents(m.group(3))
            # winner_id is group 5 (second player match)
            winner_id = m.group(5).strip()
            hand.bounty_paid[payer_id] = hand.bounty_paid.get(payer_id, 0) + amount
            # Cross-check: winner gets credited via the collected line below,
            # but we track who the winner is here too.
            continue

        # "WINNER collected AMT from the 7-2 bounty"
        m = RE_BOUNTY_WON.match(line)
        if m:
            winner_id = m.group(2).strip()
            amount    = _to_cents(m.group(3))
            hand.bounty_won[winner_id] = hand.bounty_won.get(winner_id, 0) + amount

            # If hero won the bounty, check if they held 7-2
            if winner_id == hand.hero_id and hand.hero and hand.hero.hole_cards:
                hand.hero_has_72 = _is_72_offsuit(hand.hero.hole_cards)
            continue

    # If hero paid into a bounty, flag whether they held 7-2 this hand
    # (useful for analysis even when they didn't win)
    if hand.hero_id and hand.hero and hand.hero.hole_cards:
        if _is_72_offsuit(hand.hero.hole_cards):
            hand.hero_has_72 = True


# ---------------------------------------------------------------------------
# Core hand parser
# ---------------------------------------------------------------------------

def _parse_hand(raw: _RawHand, session: _SessionState,
                hero_id: Optional[str]) -> Optional[Hand]:
    """Parse a single raw hand block into a Hand object."""

    # Apply session updates from prefix lines (blind changes etc.)
    for line in raw.prefix_lines:
        _apply_session_updates(line, session)

    # Also scan the hand lines themselves for mid-hand config changes
    for line in raw.lines:
        _apply_session_updates(line, session)

    m = RE_HAND_START.match(raw.start_entry)
    if not m:
        return None

    hand_id      = m.group(2)
    dealer_hash  = m.group(5)   # None for dead button
    is_dead_btn  = "dead button" in raw.start_entry

    # ---- Player roster from stacks line --------------------------------
    players: dict[str, Player] = {}
    seat_order: list[tuple[int, str]] = []
    stacks: dict[str, int] = {}

    stacks_line = next((l for l in raw.lines if l.startswith("Player stacks:")), None)
    if not stacks_line:
        return None

    for sm in RE_SINGLE_STACK.finditer(stacks_line):
        seat_num    = int(sm.group(1))
        disp_name   = sm.group(2).strip()
        pid         = sm.group(3).strip()
        start_stack = _to_cents(sm.group(4))
        players[pid] = Player(
            player_id=pid,
            display_name=disp_name,
            position=Position.BB,   # placeholder — assigned below
            starting_stack=start_stack,
            is_hero=(pid == hero_id),
        )
        stacks[pid] = start_stack
        seat_order.append((seat_num, pid))

    seat_order.sort(key=lambda x: x[0])
    ordered_pids = [pid for _, pid in seat_order]

    # ---- Assign positions ----------------------------------------------
    dealer_idx = None
    if not is_dead_btn and dealer_hash and dealer_hash in players:
        dealer_idx = ordered_pids.index(dealer_hash)

    n = len(ordered_pids)
    POSITION_NAMES = [
        Position.BTN, Position.SB, Position.BB,
        Position.UTG, Position.UTG1, Position.UTG2,
        Position.HJ, Position.CO,
    ]
    if dealer_idx is not None:
        for pid in ordered_pids:
            offset   = (ordered_pids.index(pid) - dealer_idx) % n
            pos      = POSITION_NAMES[offset] if offset < len(POSITION_NAMES) else Position.UTG
            players[pid] = Player(
                player_id=players[pid].player_id,
                display_name=players[pid].display_name,
                position=pos,
                starting_stack=players[pid].starting_stack,
                is_hero=players[pid].is_hero,
            )

    # ---- Pre-scan for hero hole cards (appear before stacks line) ------
    # Also detect PLO/bomb pot hands from 4-card deals.
    pending_hero_cards: Optional[tuple[str, ...]] = None
    for line in raw.lines:
        mm = RE_YOUR_HAND.match(line)
        if mm:
            cards = tuple(
                _parse_card(mm.group(i))
                for i in range(1, 5)
                if mm.group(i) is not None
            )
            pending_hero_cards = cards
            break

    if pending_hero_cards and hero_id and hero_id in players:
        p = players[hero_id]
        players[hero_id] = Player(
            player_id=p.player_id, display_name=p.display_name,
            position=p.position, starting_stack=p.starting_stack,
            hole_cards=pending_hero_cards, is_hero=True,
        )
        # 4 hole cards = PLO/bomb pot regardless of game type config
        if len(pending_hero_cards) == 4:
            hand.is_bomb_pot = True

    # ---- Initialise Hand object ----------------------------------------
    hand = Hand(
        hand_id=hand_id,
        timestamp=raw.timestamp,
        big_blind=session.big_blind,
        small_blind=session.small_blind,
        players=players,
        hero_id=hero_id if hero_id in players else None,
        bounty_config=session.bounty_config,
        is_bomb_pot=(session.game_type != "NLH"),
    )

    # ---- Walk lines and build actions + states -------------------------
    current_street  = Street.PREFLOP
    pot             = Pot()
    players_in_hand = list(ordered_pids)
    current_bet     = 0
    last_aggressor  = None
    sequence_index  = 0
    board: list[str] = []
    street_contrib: dict[str, int] = {pid: 0 for pid in ordered_pids}

    def _commit_action(action: Action) -> None:
        hand.actions.append(action)
        hand.streets[action.street].append(action)
        snap = GameState(
            street=current_street,
            board=tuple(board),
            pot=Pot(main=pot.main, side_pots=list(pot.side_pots)),
            stacks=dict(stacks),
            players_in_hand=tuple(players_in_hand),
            current_bet=current_bet,
            action_index=action.sequence_index,
            last_aggressor_id=last_aggressor,
        )
        hand.states.append(snap)

    def _new_street(street: Street, new_cards: list[str]) -> None:
        nonlocal current_street, current_bet, street_contrib
        current_street = street
        current_bet    = 0
        street_contrib = {pid: 0 for pid in ordered_pids}
        board.extend(new_cards)

    def _make_action(pid: str, atype: ActionType,
                     amount_cents: int = 0, is_all_in: bool = False) -> Action:
        nonlocal sequence_index
        a = Action(
            player_id=pid,
            action_type=atype,
            street=current_street,
            sequence_index=sequence_index,
            amount=amount_cents,
            stack_before=stacks.get(pid, 0),
            pot_before=pot.total,
            is_all_in=is_all_in,
        )
        sequence_index += 1
        return a

    for line in raw.lines:
        # Skip administrative lines
        if (RE_HAND_END.match(line)
                or line.startswith("Player stacks:")
                or line.startswith("Game Config ")
                or line.startswith("WARNING:")
                or line.startswith("The admin")
                or line.startswith("The game's")
                or line.startswith("The player")
                or RE_DEAD_SB.match(line)):
            continue

        # Hero hole cards (already pre-scanned, skip here)
        if RE_YOUR_HAND.match(line):
            continue

        # Showdown — other players' cards
        m = RE_SHOWS.match(line)
        if m:
            pid = m.group(2).strip()
            if pid in players and players[pid].hole_cards is None:
                c1 = _parse_card(m.group(3))
                c2 = _parse_card(m.group(4)) if m.group(4) else None
                p  = players[pid]
                players[pid] = Player(
                    player_id=p.player_id, display_name=p.display_name,
                    position=p.position, starting_stack=p.starting_stack,
                    hole_cards=(c1, c2) if c2 else (c1,), is_hero=p.is_hero,
                )
            continue

        # Community cards
        m = RE_FLOP.match(line)
        if m:
            _new_street(Street.FLOP, [_parse_card(m.group(i)) for i in (1, 2, 3)])
            continue

        m = RE_TURN.match(line)
        if m:
            _new_street(Street.TURN, [_parse_card(m.group(1))])
            continue

        m = RE_RIVER.match(line)
        if m:
            _new_street(Street.RIVER, [_parse_card(m.group(1))])
            continue

        # Uncalled bet returned
        m = RE_UNCALLED.match(line)
        if m:
            amount = _to_cents(m.group(1))
            pid    = m.group(3).strip()
            stacks[pid]  = stacks.get(pid, 0) + amount
            pot = Pot(main=max(0, pot.main - amount), side_pots=list(pot.side_pots))
            continue

        # Winner collection
        m = RE_COLLECTED.match(line)
        if m:
            pid    = m.group(2).strip()
            amount = _to_cents(m.group(3))
            hand.winners[pid] = hand.winners.get(pid, 0) + amount
            stacks[pid] = stacks.get(pid, 0) + amount
            continue

        # ---- Action lines ----------------------------------------------

        # Small blind
        m = RE_POST_SB.match(line) or RE_POST_MISSING_SB.match(line)
        if m:
            pid, _  = _parse_player_ref(m.group(1), m.group(2))
            amount  = _to_cents(m.group(3))
            stacks[pid]         = stacks.get(pid, 0) - amount
            pot                 = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            current_bet         = max(current_bet, amount)
            _commit_action(_make_action(pid, ActionType.POST_SB, amount))
            continue

        # Big blind
        m = RE_POST_BB.match(line) or RE_POST_MISSED_BB.match(line)
        if m:
            pid, _  = _parse_player_ref(m.group(1), m.group(2))
            amount  = _to_cents(m.group(3))
            stacks[pid]         = stacks.get(pid, 0) - amount
            pot                 = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            current_bet         = max(current_bet, amount)
            _commit_action(_make_action(pid, ActionType.POST_BB, amount))
            continue

        # Straddle
        m = RE_POST_STR.match(line)
        if m:
            pid, _  = _parse_player_ref(m.group(1), m.group(2))
            amount  = _to_cents(m.group(3))
            stacks[pid]             = stacks.get(pid, 0) - amount
            pot                     = pot.add_to_main(amount)
            street_contrib[pid]     = street_contrib.get(pid, 0) + amount
            current_bet             = max(current_bet, amount)
            hand.straddle           = amount
            hand.straddle_player_id = pid
            last_aggressor          = pid
            _commit_action(_make_action(pid, ActionType.POST_STRADDLE, amount))
            continue

        # Fold
        m = RE_FOLD.match(line)
        if m:
            pid, _ = _parse_player_ref(m.group(1), m.group(2))
            if pid in players_in_hand:
                players_in_hand.remove(pid)
            _commit_action(_make_action(pid, ActionType.FOLD))
            continue

        # Check
        m = RE_CHECK.match(line)
        if m:
            pid, _ = _parse_player_ref(m.group(1), m.group(2))
            _commit_action(_make_action(pid, ActionType.CHECK))
            continue

        # Call (regular)
        m = RE_CALL.match(line)
        if m and "all in" not in line:
            pid, _  = _parse_player_ref(m.group(1), m.group(2))
            amount  = _to_cents(m.group(3))
            stacks[pid]         = stacks.get(pid, 0) - amount
            pot                 = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            _commit_action(_make_action(pid, ActionType.CALL, amount))
            continue

        # All-in call
        m = RE_ALL_IN_CALL.match(line)
        if m:
            pid, _  = _parse_player_ref(m.group(1), m.group(2))
            amount  = _to_cents(m.group(3))
            stacks[pid]         = 0
            pot                 = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            _commit_action(_make_action(pid, ActionType.ALL_IN, amount, is_all_in=True))
            continue

        # Bet (regular)
        m = RE_BET.match(line)
        if m and "all in" not in line:
            pid, _      = _parse_player_ref(m.group(1), m.group(2))
            amount      = _to_cents(m.group(3))
            stacks[pid] = stacks.get(pid, 0) - amount
            pot         = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            current_bet         = street_contrib[pid]
            last_aggressor      = pid
            _commit_action(_make_action(pid, ActionType.BET, amount))
            continue

        # All-in bet
        m = RE_ALL_IN_BET.match(line)
        if m:
            pid, _      = _parse_player_ref(m.group(1), m.group(2))
            amount      = _to_cents(m.group(3))
            stacks[pid] = 0
            pot         = pot.add_to_main(amount)
            street_contrib[pid] = street_contrib.get(pid, 0) + amount
            current_bet         = street_contrib[pid]
            last_aggressor      = pid
            _commit_action(_make_action(pid, ActionType.ALL_IN, amount, is_all_in=True))
            continue

        # Raise (regular)
        m = RE_RAISE.match(line)
        if m and "all in" not in line:
            pid, _    = _parse_player_ref(m.group(1), m.group(2))
            raise_to  = _to_cents(m.group(3))
            already   = street_contrib.get(pid, 0)
            chips_in  = raise_to - already
            stacks[pid] = stacks.get(pid, 0) - chips_in
            pot         = pot.add_to_main(chips_in)
            street_contrib[pid] = raise_to
            current_bet         = raise_to
            last_aggressor      = pid
            _commit_action(_make_action(pid, ActionType.RAISE, chips_in))
            continue

        # All-in raise
        m = RE_ALL_IN_RAISE.match(line)
        if m:
            pid, _    = _parse_player_ref(m.group(1), m.group(2))
            raise_to  = _to_cents(m.group(3))
            already   = street_contrib.get(pid, 0)
            chips_in  = raise_to - already
            stacks[pid] = 0
            pot         = pot.add_to_main(chips_in)
            street_contrib[pid] = raise_to
            current_bet         = raise_to
            last_aggressor      = pid
            _commit_action(_make_action(pid, ActionType.ALL_IN, chips_in, is_all_in=True))
            continue

    # ---- Finalise ------------------------------------------------------
    hand.board = board

    # Parse bounty suffix lines (after ending hand marker)
    if raw.suffix_lines and hand.bounty_config:
        _parse_bounty_suffix(raw.suffix_lines, hand)

    return hand


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_log(filepath: str | Path,
              hero_id: Optional[str] = None) -> list[Hand]:
    """
    Parse a PokerNow CSV log file and return a list of Hand objects
    in chronological order.

    Args:
        filepath: Path to the PokerNow .csv log file.
        hero_id:  Stable PokerNow hash of the player to analyse
                  (the part after '@' in their name, e.g. 'hL2HOafVVY').

    Returns:
        List of Hand objects, oldest hand first.
    """
    filepath = Path(filepath)
    rows: list[tuple[str, str]] = []

    with filepath.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((row["entry"], row["at"]))

    # Reverse to chronological order (PokerNow CSV is newest-first)
    rows.reverse()

    raw_hands = _group_hands(rows)

    session = _SessionState()
    hands: list[Hand] = []

    for raw in raw_hands:
        hand = _parse_hand(raw, session, hero_id)
        if hand is not None:
            hands.append(hand)

    return hands