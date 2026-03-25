from parser import parse_log
from analysis import analyse_session
from report import generate_report
from db.database import Database
from pathlib import Path

# BASE_DIR = Path(__file__).resolve().parent.parent


# 🔹 CONFIG
DATA_FILE = "data/sample_log.csv"
HERO_ID = "PFiA37ihL9"  # change this to match your logs


def run_pipeline(file_path: str, hero_name: str):
    """
    Full pipeline:
    parse → analyze → store → report
    """

    print("📥 Parsing hands...")
    hands = parse_log(file_path, hero_id=HERO_ID)

    print(f"✅ Parsed {len(hands)} hands")

    print("🧠 Running analysis...")
    session_analysis = analyse_session(hands, hero_id=HERO_ID)

    print("💾 Storing in database...")
    db = Database()

    # Create session
    session_id = db.create_session(
        session_analysis.stats,
        total_hands=len(session_analysis.hand_analyses),
        hero_id=HERO_ID,
    )

    for hand_analysis in session_analysis.hand_analyses:
        hand = hand_analysis.hand

        # Insert hand
        hand_id = db.insert_hand(session_id, hand)

        # Insert all actions
        for i, action in enumerate(hand.actions):
            db.insert_action(hand_id, action, i)

        # Insert hero decisions
        for action_analysis in hand_analysis.action_analyses:
            db.insert_decision(hand_id, hand, action_analysis)

    db.commit()
    db.close()

    print("📊 Generating HTML report...")
    generate_report(session_analysis, "report.html")

    print("🎉 Done! Open report.html in your browser.")


def main():
    run_pipeline(DATA_FILE, HERO_ID)


if __name__ == "__main__":
    main()