import json
from pathlib import Path


def serialize_session(session_analysis):
    """Convert SessionAnalysis → JSON-serializable dict"""

    hands_data = []

    for hand_analysis in session_analysis.hand_analyses:
        hand = hand_analysis.hand

        actions_data = []
        for action_analysis in hand_analysis.action_analyses:
            state = hand.state_before(action_analysis.action.sequence_index)

            actions_data.append({
                "player": action_analysis.action.player_id,
                "action": str(action_analysis.action.action_type),
                "amount": action_analysis.action.amount,
                "street": str(action_analysis.action.street),
                "pot": state.pot.total,
                "board": state.board,
                "stacks": state.stacks,
                # "is_hero": True
                "equity": action_analysis.equity,
                "pot_odds": action_analysis.pot_odds,
                "ev": action_analysis.ev_with_bounty if action_analysis.ev_with_bounty is not None else action_analysis.ev_estimate,
                "verdict": action_analysis.verdict.value,
                "notes": action_analysis.notes,
            })

        hands_data.append({
            "hand_id": hand.hand_id,
            "actions": actions_data
        })

    return {
        "hands": hands_data,
        "stats": {
            "vpip": session_analysis.stats.vpip,
            "pfr": session_analysis.stats.pfr,
            "af": session_analysis.stats.aggression_factor,
        }
    }


def generate_html(data):
    """Generate HTML string with embedded JS"""

    json_data = json.dumps(data)

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Poker Analyzer</title>
    <style>
        body {{ font-family: Arial; padding: 20px; }}
        .container {{ max-width: 900px; margin: auto; }}
        .box {{ border: 1px solid #ccc; padding: 10px; margin-top: 10px; }}
        button {{ margin: 5px; padding: 10px; }}
    </style>
</head>
<body>

<div class="container">
    <h1>Poker Analysis</h1>

    <h2>Session Stats</h2>
    <div id="stats"></div>

    <h2>Hand</h2>
    <select id="handSelect"></select>

    <div class="box">
        <button onclick="prev()">Previous</button>
        <button onclick="next()">Next</button>
        <span id="index"></span>
    </div>

    <div class="box" id="state"></div>
    <div class="box" id="analysis"></div>
</div>

<script>
const data = {json_data};

let currentHandIndex = 0;
let currentActionIndex = 0;

function init() {{
    const select = document.getElementById("handSelect");

    data.hands.forEach((h, i) => {{
        const option = document.createElement("option");
        option.value = i;
        option.text = "Hand " + h.hand_id;
        select.appendChild(option);
    }});

    select.onchange = () => {{
        currentHandIndex = parseInt(select.value);
        currentActionIndex = 0;
        render();
    }};

    document.getElementById("stats").innerText =
        `VPIP: ${{data.stats.vpip.toFixed(2)}} | PFR: ${{data.stats.pfr.toFixed(2)}} | AF: ${{data.stats.af.toFixed(2)}}`;

    render();
}}

function render() {{
    const hand = data.hands[currentHandIndex];
    const action = hand.actions[currentActionIndex];

    document.getElementById("index").innerText =
        `Action ${{currentActionIndex + 1}} / ${{hand.actions.length}}`;

    document.getElementById("state").innerHTML = `
        <b>Player:</b> ${{action.player_id}} <br>
        <b>Action:</b> ${{action.action}} (${{action.amount || 0}}) <br>
        <b>Street:</b> ${{action.street}} <br>
        <b>Pot:</b> ${{action.pot}} <br>
        <b>Board:</b> ${{action.board.join(", ")}} <br>
        <b>Stacks:</b> ${{JSON.stringify(action.stacks)}}
    `;

    if (true) {{
        document.getElementById("analysis").innerHTML = `
            <b>Hero Analysis</b><br>
            Equity: ${{action.equity ?? "N/A"}} <br>
            Pot Odds: ${{action.pot_odds ?? "N/A"}} <br>
            EV: ${{action.ev ?? "N/A"}} <br>
            Verdict: ${{action.verdict ?? "N/A"}} <br>
            Notes: ${{(action.notes || []).join(", ")}}
        `;
    }} else {{
        document.getElementById("analysis").innerHTML = "Opponent action";
    }}
}}

function next() {{
    const hand = data.hands[currentHandIndex];
    if (currentActionIndex < hand.actions.length - 1) {{
        currentActionIndex++;
        render();
    }}
}}

function prev() {{
    if (currentActionIndex > 0) {{
        currentActionIndex--;
        render();
    }}
}}

init();
</script>

</body>
</html>
"""


def generate_report(session_analysis, output_path="report.html"):
    data = serialize_session(session_analysis)
    html = generate_html(data)

    Path(output_path).write_text(html)
    print(f"Report generated: {output_path}")