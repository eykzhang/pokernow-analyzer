CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    total_hands INTEGER,

    vpip REAL,
    pfr REAL,
    af REAL,

    three_bet_pct REAL,
    cbet_pct REAL,
    ev_per_hand REAL,
    net_bb REAL,

    hero_id TEXT
);

CREATE TABLE IF NOT EXISTS hands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    hand_number INTEGER,

    hero_position TEXT,
    hero_cards TEXT,

    net_bb REAL,
    net_bb_excl_bounty REAL,
    bounty_net_bb REAL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id INTEGER,
    player_id TEXT,
    action_type TEXT,
    amount REAL,
    street TEXT,
    action_index INTEGER
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id INTEGER,

    street TEXT,
    position TEXT,
    num_players INTEGER,

    pot REAL,
    spr REAL,

    hero_cards TEXT,
    board TEXT,

    equity REAL,
    pot_odds REAL,

    ev_estimate REAL,
    ev_with_bounty REAL,
    bounty_ev REAL,

    action_taken TEXT,
    bet_size REAL,
    bet_size_pct REAL,

    verdict TEXT,
    action_index INTEGER
);