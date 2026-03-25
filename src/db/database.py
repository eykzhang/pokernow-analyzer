from pathlib import Path
import sqlite3
from datetime import datetime


# ---------------------------------------------------------------------------
# Paths (robust)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent          # src/db/
PROJECT_ROOT = BASE_DIR.parent.parent               # project root

DB_PATH = PROJECT_ROOT / "data" / "poker.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        schema = SCHEMA_PATH.read_text()
        self.conn.executescript(schema)
        self.conn.commit()

    # -----------------------------------------------------------------------
    # Session
    # -----------------------------------------------------------------------

    def create_session(self, stats, total_hands, hero_id):
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO sessions (
                timestamp,
                total_hands,
                vpip,
                pfr,
                af,
                three_bet_pct,
                cbet_pct,
                ev_per_hand,
                net_bb,
                hero_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                total_hands,
                stats.vpip or 0,
                stats.pfr or 0,
                stats.aggression_factor or 0,
                stats.three_bet_pct or 0,
                stats.cbet_pct or 0,
                stats.ev_per_hand or 0,
                stats.net_bb or 0,
                hero_id,
            ),
        )

        self.conn.commit()
        return cursor.lastrowid

    # -----------------------------------------------------------------------
    # Hand
    # -----------------------------------------------------------------------

    def insert_hand(self, session_id, hand):
        cursor = self.conn.cursor()

        hero = hand.hero

        hero_cards = None
        if hero and hero.hole_cards:
            hero_cards = ",".join(hero.hole_cards)

        hero_position = None
        if hero and hero.position:
            hero_position = hero.position.value

        cursor.execute(
            """
            INSERT INTO hands (
                session_id,
                hand_number,
                hero_position,
                hero_cards,
                net_bb,
                net_bb_excl_bounty,
                bounty_net_bb
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                hand.hand_id,
                hero_position,
                hero_cards,
                hand.hero_net_bb(),
                hand.hero_net_excl_bounty_bb(),
                hand.bounty_net_bb(hand.hero_id) if hand.hero_id else 0,
            ),
        )

        self.conn.commit()
        return cursor.lastrowid

    # -----------------------------------------------------------------------
    # Actions (raw log)
    # -----------------------------------------------------------------------

    def insert_action(self, hand_id, action, index):
        self.conn.execute(
            """
            INSERT INTO actions (
                hand_id,
                player_id,
                action_type,
                amount,
                street,
                action_index
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                hand_id,
                action.player_id,
                action.action_type.value,
                action.amount,
                action.street.value,
                index,
            ),
        )

    # -----------------------------------------------------------------------
    # Decisions (THIS IS THE IMPORTANT TABLE)
    # -----------------------------------------------------------------------

    def insert_decision(self, hand_id, hand, action_analysis):
        action = action_analysis.action

        # --- reconstruct state properly ---
        state = hand.state_before(action.sequence_index)
        if state is None:
            return  # skip invalid state

        hero = hand.hero
        if not hero:
            return

        # --- hero features ---
        hero_cards = ",".join(hero.hole_cards) if hero.hole_cards else None
        position = hero.position.value if hero.position else None

        # --- state features ---
        pot = state.pot.total
        board = ",".join(state.board)
        num_players = state.num_players_remaining
        spr = state.spr(hand.hero_id)

        # --- action features ---
        action_taken = action.action_type.value
        bet_size = action.amount

        # --- analysis features ---
        equity = action_analysis.equity
        pot_odds = action_analysis.pot_odds
        ev_estimate = action_analysis.ev_estimate
        ev_with_bounty = action_analysis.ev_with_bounty
        bounty_ev = action_analysis.bounty_ev_bb
        bet_size_pct = action_analysis.bet_size_pct

        verdict = action_analysis.verdict.value if action_analysis.verdict else None

        self.conn.execute(
            """
            INSERT INTO decisions (
                hand_id,

                street,
                position,
                num_players,

                pot,
                spr,

                hero_cards,
                board,

                equity,
                pot_odds,

                ev_estimate,
                ev_with_bounty,
                bounty_ev,

                action_taken,
                bet_size,
                bet_size_pct,

                verdict,
                action_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hand_id,

                action.street.value,
                position,
                num_players,

                pot,
                spr,

                hero_cards,
                board,

                equity,
                pot_odds,

                ev_estimate,
                ev_with_bounty,
                bounty_ev,

                action_taken,
                bet_size,
                bet_size_pct,

                verdict,
                action.sequence_index,
            ),
        )

    # -----------------------------------------------------------------------
    # Finalize
    # -----------------------------------------------------------------------

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()