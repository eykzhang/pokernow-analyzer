# PokerNow Analyzer

A Python tool that turns PokerNow hand history logs into a queryable SQLite database
and HTML reports, so a player can spot recurring strategic mistakes instead of
judging individual hands by their outcome.

PokerNow logs the full history of a session but doesn't do much with it. This project
parses those logs into structured hand data, stores them, and generates reports on
tendencies over time.

## Features

- Parses PokerNow hand history logs into structured hand data
- Stores parsed hands and player stats in SQLite
- Generates HTML reports summarizing performance and tendencies
- Modular pipeline (parsing, analysis, and reporting are separate stages), built to
  support replay analysis and deeper stats later

## How it works

```
PokerNow log files → parser.py → structured hand data → analysis.py → SQLite
                                                                          │
                                                                          ▼
                                                              report.py → HTML report
```

```
src/
├── parser.py     # raw log -> structured hand data
├── analysis.py   # stats and trend analysis
├── database.py   # SQLite persistence
├── models.py     # data models
└── report.py     # HTML report generation
```

## Stack

Python, SQLite, pandas, HTML/CSS for report output.

## Running it

```bash
git clone https://github.com/eykzhang/pokernow-analyzer.git
cd pokernow-analyzer
pip install -r requirements.txt
python src/main.py
```

## Status

Feature-complete for its original scope; not under active development. Ideas for a
follow-up: an interactive replay browser, EV analysis, leak-detection heuristics, and
a web upload flow instead of local log files.

## License

MIT
