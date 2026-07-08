# PokerNow Analyzer

A Python application for parsing, analyzing, and visualizing **PokerNow** hand histories. PokerNow Analyzer aggregates raw game logs into a SQLite database and generates actionable statistics and reports to help players identify long-term strategic leaks and improve their decision-making.

> **Status:** Active Development

---

## Features

- Parse PokerNow hand history logs into structured game data
- Persist parsed hands and player statistics using SQLite
- Analyze gameplay trends and player tendencies
- Generate interactive HTML reports summarizing performance
- Modular architecture designed to support future replay analysis and advanced analytics

---

## Demo

> *Screenshots and demo GIF coming soon.*

---

## Motivation

Poker is a game of incomplete information where long-term improvement depends on identifying recurring mistakes rather than individual bad outcomes. While PokerNow stores raw hand histories, it provides relatively limited tooling for long-term statistical analysis.

PokerNow Analyzer was built to automate this process by transforming raw hand histories into structured data that can be queried, analyzed, and visualized.

---

## Architecture

Current processing pipeline:

```text
PokerNow Log Files
        │
        ▼
 Parser (parser.py)
        │
        ▼
 Structured Hand Data
        │
        ▼
 Analysis Engine (analysis.py)
        │
        ▼
 SQLite Database
        │
        ▼
 HTML Report Generator (report.py)
```

Repository structure:

```
pokernow-analyzer/
│
├── src/
│   ├── parser.py
│   ├── analysis.py
│   ├── report.py
│   ├── database.py
│   ├── models.py
│   └── ...
│
├── data/
│
├── reports/
│
├── requirements.txt
└── README.md
```

---

## Technologies

| Category | Technologies |
|-----------|--------------|
| Language | Python |
| Database | SQLite |
| Frontend | HTML, CSS |
| Data Processing | pandas |
| Version Control | Git |

---

## Installation

Clone the repository

```bash
git clone https://github.com/eykzhang/pokernow-analyzer.git
cd pokernow-analyzer
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run the analyzer

```bash
python src/main.py
```

---

## Engineering Challenges

Some of the most interesting engineering problems in this project include:

- Parsing semi-structured PokerNow logs into a normalized data model
- Designing a SQLite schema capable of efficiently storing hands and player statistics
- Separating parsing, analysis, persistence, and report generation into independent modules
- Producing human-readable reports from large collections of historical games

---

## Future Work

Planned improvements include:

- Interactive replay browser
- Expected value (EV) analysis
- Leak detection heuristics
- Session comparison tools
- Machine learning-based decision support
- Web interface for uploading and analyzing sessions

---

## License

This project is licensed under the MIT License.
