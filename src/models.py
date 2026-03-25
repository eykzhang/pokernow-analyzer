"""
models.py
Core data model for PokerNow Hand Analyzer.

Chip amounts are stored as raw integers (smallest chip unit = 1 cent).
  e.g. $0.50 big blind  → big_blind = 50
       $1.75 bet        → amount    = 175
Use Hand.to_bb(amount) or the per-object _bb() helpers for BB-unit display.
The parser is responsible for converting PokerNow dollar strings to cents
by multiplying by 100 and rounding to int.

All GameState objects are immutable snapshots — one is created eagerly
after each Action is processed during parsing.

7-2 Bounty:
  When a 7-2 bounty is active, Hand.bounty_config holds the per-player
  payment amount (cents). Hand.bounty_won and Hand.bounty_paid record
  the net bounty result for each player in that hand.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Position(Enum):
    UTG   = "UTG"
    UTG1  = "UTG+1"
    UTG2  = "UTG+2"
    HJ    = "HJ"
    CO    = "CO"
    BTN   = "BTN"
    SB    = "SB"
    BB    = "BB"
    STR   = "STR"    # Straddle

class Street(Enum):
    PREFLOP = "preflop"
    FLOP    = "flop"
    TURN    = "turn"
    RIVER   = "river"

    def next(self) -> Optional[Street]:
        order = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]
        idx = order.index(self)
        return order[idx + 1] if idx < len(order) - 1 else None

class ActionType(Enum):
    POST_SB       = "post_sb"
    POST_BB       = "post_bb"
    POST_STRADDLE = "post_straddle"
    FOLD          = "fold"
    CHECK         = "check"
    CALL          = "call"
    BET           = "bet"
    RAISE         = "raise"
    ALL_IN        = "all_in"


# ---------------------------------------------------------------------------
# Bounty config
# ---------------------------------------------------------------------------

@dataclass
class BountyConfig:
    """Configuration for a 7-2 (or similar) bounty game."""
    amount_per_player: int    # cents each player pays the winner
    name: str = "7-2"

    def __repr__(self) -> str:
        return f"<BountyConfig {self.name} ${self.amount_per_player/100:.2f}/player>"


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

@dataclass
class Player:
    """
    Immutable identity information for a seat in a single hand.
    Stack sizes that change during the hand live in GameState, not here.
    """
    player_id: str
    display_name: str
    position: Position
    starting_stack: int             # cents
    hole_cards: Optional[tuple[str, ...]] = None
    is_hero: bool = False

    def starting_stack_bb(self, big_blind: int) -> float:
        return self.starting_stack / big_blind

    def __repr__(self) -> str:
        hero_tag = " [HERO]" if self.is_hero else ""
        cards = f" {self.hole_cards}" if self.hole_cards else ""
        return f"<Player {self.display_name}{hero_tag} | {self.position.value} | {self.starting_stack}c{cards}>"


# ---------------------------------------------------------------------------
# Pot
# ---------------------------------------------------------------------------

@dataclass
class SidePot:
    amount: int
    eligible_player_ids: list[str]

    def to_bb(self, big_blind: int) -> float:
        return self.amount / big_blind

    def __repr__(self) -> str:
        return f"<SidePot {self.amount}c | eligible: {self.eligible_player_ids}>"


@dataclass
class Pot:
    """
    Tracks the main pot and any side pots.
    All mutations return a new Pot instance to preserve GameState immutability.
    """
    main: int = 0
    side_pots: list[SidePot] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.main + sum(sp.amount for sp in self.side_pots)

    def total_bb(self, big_blind: int) -> float:
        return self.total / big_blind

    def main_bb(self, big_blind: int) -> float:
        return self.main / big_blind

    def add_to_main(self, amount: int) -> Pot:
        return Pot(main=self.main + amount, side_pots=list(self.side_pots))

    def add_side_pot(self, side_pot: SidePot) -> Pot:
        return Pot(main=self.main, side_pots=self.side_pots + [side_pot])

    def __repr__(self) -> str:
        if self.side_pots:
            return f"<Pot main={self.main} sides={self.side_pots}>"
        return f"<Pot {self.main}c>"


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    """A single discrete action taken by a player. Frozen for immutability."""
    player_id: str
    action_type: ActionType
    street: Street
    sequence_index: int
    amount: int = 0
    stack_before: int = 0
    pot_before: int = 0
    is_all_in: bool = False

    @property
    def is_aggressive(self) -> bool:
        return self.action_type in {ActionType.BET, ActionType.RAISE, ActionType.ALL_IN}

    @property
    def is_voluntary(self) -> bool:
        return self.action_type not in {
            ActionType.POST_SB,
            ActionType.POST_BB,
            ActionType.POST_STRADDLE,
        }

    def pot_odds(self) -> Optional[float]:
        """
        Pot odds faced when calling — the fraction of the final pot the
        player must risk. Returns None for non-call actions.
        """
        if self.action_type not in {ActionType.CALL, ActionType.ALL_IN}:
            return None
        if self.pot_before + self.amount == 0:
            return None
        return self.amount / (self.pot_before + self.amount)

    def bet_size_pct(self) -> Optional[float]:
        """Bet/raise as a fraction of the pot before the action."""
        if not self.is_aggressive or self.pot_before == 0:
            return None
        return self.amount / self.pot_before

    def amount_bb(self, big_blind: int) -> float:
        return self.amount / big_blind

    def stack_before_bb(self, big_blind: int) -> float:
        return self.stack_before / big_blind

    def __repr__(self) -> str:
        base = f"<Action [{self.sequence_index}] {self.player_id} {self.action_type.value}"
        if self.amount:
            base += f" {self.amount}c"
        if self.is_all_in:
            base += " ALL-IN"
        return base + f" | {self.street.value}>"


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GameState:
    """
    A complete snapshot of the table after a single action.
    Frozen to enforce immutability — the parser builds new instances
    rather than mutating existing ones.
    """
    street: Street
    board: tuple[str, ...]
    pot: Pot
    stacks: dict[str, int]              # player_id → current stack (cents)
    players_in_hand: tuple[str, ...]
    current_bet: int
    action_index: int
    last_aggressor_id: Optional[str] = None

    def stack(self, player_id: str) -> int:
        return self.stacks[player_id]

    def stack_bb(self, player_id: str, big_blind: int) -> float:
        return self.stacks[player_id] / big_blind

    def spr(self, player_id: str) -> Optional[float]:
        if self.pot.total == 0:
            return None
        return self.stacks[player_id] / self.pot.total

    def pot_odds_to_call(self, call_amount: int) -> Optional[float]:
        if call_amount <= 0:
            return None
        return call_amount / (self.pot.total + call_amount)

    @property
    def is_heads_up(self) -> bool:
        return len(self.players_in_hand) == 2

    @property
    def num_players_remaining(self) -> int:
        return len(self.players_in_hand)

    def __repr__(self) -> str:
        board_str = " ".join(self.board) if self.board else "—"
        return (
            f"<GameState [{self.action_index}] {self.street.value} | "
            f"board: {board_str} | pot: {self.pot.total}c | "
            f"players: {len(self.players_in_hand)}>"
        )


# ---------------------------------------------------------------------------
# Hand
# ---------------------------------------------------------------------------

@dataclass
class Hand:
    """
    Complete record of a single poker hand, including bounty results.

    Bounty accounting:
        bounty_config   — active bounty rule (None if no bounty in this game)
        bounty_won      — player_id → cents received from bounty winners
        bounty_paid     — player_id → cents paid out to bounty winners
        hero_has_72     — True when hero held 7-2 offsuit (affects EV calculations)

    hero_net() includes bounty in/out. Use hero_net_excl_bounty() for
    pure poker result without bounty noise.
    """
    hand_id: str
    timestamp: datetime
    big_blind: int
    small_blind: int
    players: dict[str, Player]
    actions: list[Action] = field(default_factory=list)
    states: list[GameState] = field(default_factory=list)
    streets: dict[Street, list[Action]] = field(
        default_factory=lambda: {s: [] for s in Street}
    )
    board: list[str] = field(default_factory=list)
    winners: dict[str, int] = field(default_factory=dict)
    hero_id: Optional[str] = None
    straddle: Optional[int] = None
    straddle_player_id: Optional[str] = None

    # Bounty
    bounty_config: Optional[BountyConfig] = None
    bounty_won: dict[str, int] = field(default_factory=dict)
    bounty_paid: dict[str, int] = field(default_factory=dict)
    hero_has_72: bool = False

    # Bomb pot / PLO detection
    is_bomb_pot: bool = False   # True if this hand is PLO or a bomb pot format

    # ------------------------------------------------------------------
    # BB helpers
    # ------------------------------------------------------------------

    def to_bb(self, amount: int) -> float:
        return amount / self.big_blind

    def from_bb(self, bb_amount: float) -> int:
        return round(bb_amount * self.big_blind)

    def effective_bb(self) -> int:
        return self.straddle if self.straddle else self.big_blind

    def to_eff_bb(self, amount: int) -> float:
        return amount / self.effective_bb()

    # ------------------------------------------------------------------
    # Action / state access
    # ------------------------------------------------------------------

    def state_before(self, action_index: int) -> Optional[GameState]:
        if action_index == 0:
            return None
        return self.states[action_index - 1]

    def state_after(self, action_index: int) -> GameState:
        return self.states[action_index]

    def actions_on_street(self, street: Street) -> list[Action]:
        return self.streets[street]

    def actions_by_player(self, player_id: str) -> list[Action]:
        return [a for a in self.actions if a.player_id == player_id]

    # ------------------------------------------------------------------
    # Hero helpers
    # ------------------------------------------------------------------

    @property
    def hero(self) -> Optional[Player]:
        return self.players.get(self.hero_id) if self.hero_id else None

    def hero_actions(self) -> list[Action]:
        if not self.hero_id:
            return []
        return [a for a in self.actions if a.player_id == self.hero_id and a.is_voluntary]

    def hero_actions_on_street(self, street: Street) -> list[Action]:
        return [a for a in self.hero_actions() if a.street == street]

    def hero_net(self) -> int:
        """Net chips for hero this hand (cents), including bounty."""
        if not self.hero_id:
            return 0
        won   = self.winners.get(self.hero_id, 0)
        spent = sum(a.amount for a in self.actions if a.player_id == self.hero_id)
        b_won  = self.bounty_won.get(self.hero_id, 0)
        b_paid = self.bounty_paid.get(self.hero_id, 0)
        return won - spent + b_won - b_paid

    def hero_net_bb(self) -> float:
        return self.to_bb(self.hero_net())

    def hero_net_excl_bounty(self) -> int:
        """Pure poker result for hero, excluding bounty payments."""
        if not self.hero_id:
            return 0
        won   = self.winners.get(self.hero_id, 0)
        spent = sum(a.amount for a in self.actions if a.player_id == self.hero_id)
        return won - spent

    def hero_net_excl_bounty_bb(self) -> float:
        return self.to_bb(self.hero_net_excl_bounty())

    # ------------------------------------------------------------------
    # Bounty helpers
    # ------------------------------------------------------------------

    def has_bounty(self) -> bool:
        """True if a bounty was triggered this hand."""
        return bool(self.bounty_won or self.bounty_paid)

    def bounty_net(self, player_id: str) -> int:
        """Net bounty result for a player (positive = received, negative = paid)."""
        return self.bounty_won.get(player_id, 0) - self.bounty_paid.get(player_id, 0)

    def bounty_net_bb(self, player_id: str) -> float:
        return self.to_bb(self.bounty_net(player_id))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        hero = self.hero
        net_str = f" | hero: {hero.display_name} ({self.hero_net_bb():+.1f}bb)" if hero else ""
        board_str = " ".join(self.board) if self.board else "no board"
        winners_str = ", ".join(
            f"{pid} +{self.to_bb(amt):.1f}bb" for pid, amt in self.winners.items()
        )
        bounty_str = " | BOUNTY" if self.has_bounty() else ""
        return (
            f"Hand {self.hand_id} @ {self.timestamp:%Y-%m-%d %H:%M} | "
            f"{board_str} | {len(self.actions)} actions{net_str}{bounty_str} | won: {winners_str}"
        )

    def __repr__(self) -> str:
        return f"<Hand {self.hand_id} | {len(self.players)} players | {len(self.actions)} actions>"