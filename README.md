# 🃏 PokerNow Hand Analyzer

A Python-based poker analysis tool designed to parse hands played on
PokerNow, reconstruct game state, and provide GTO-inspired feedback and
player statistics.

> ⚠️ This project is intended for **training, research, and analysis
> only**. It is not designed for real-time assistance or use in
> real-money games.

------------------------------------------------------------------------

## 🚀 Features (V1)

-   ✅ Parse PokerNow hand histories\
-   ✅ Reconstruct full game state (pot, stacks, board, actions)\
-   ✅ Extract and analyze your decisions\
-   ✅ Calculate:
    -   Pot odds
    -   Equity (Monte Carlo)
-   ✅ Track player statistics:
    -   VPIP
    -   PFR
    -   Aggression Factor\
-   ✅ Provide heuristic "GTO-style" feedback\
-   ✅ Command-line interface for quick analysis

------------------------------------------------------------------------

## 🧠 Vision

### V1 (current)

-   Hand parsing + analysis
-   Rule-based feedback
-   Basic statistics

### V2 (planned)

-   Train a personal poker bot based on your playstyle
-   Compare your decisions vs GTO strategies
-   Identify systematic leaks

### V3 (future)

-   Advanced GTO approximation (solver data / ML)
-   Simulation environment
-   Self-improvement loop (bot vs GTO)

------------------------------------------------------------------------

## 🏗️ Project Structure

    poker-analyzer/
    │
    ├── main.py
    ├── config/
    ├── parser/
    ├── engine/
    ├── analysis/
    ├── feedback/
    ├── data/
    └── utils/

------------------------------------------------------------------------

## 🔄 How It Works

Hand History → Parser → State Builder → Decision Extraction → Analysis →
Feedback

------------------------------------------------------------------------

## 🧪 Example Usage

``` bash
python main.py data/sample_hands.txt
```

------------------------------------------------------------------------

## ⚠️ Disclaimer

-   For offline analysis only\
-   Do not use in real-time play\
-   GTO recommendations are approximations

------------------------------------------------------------------------

## 🛠️ Tech Stack

-   Python 3.x\
-   NumPy\
-   Pandas\
-   SQLite

------------------------------------------------------------------------

## 📌 Roadmap

-   Improve parser\
-   Add deeper feedback\
-   Integrate solver data\
-   Train personal bot

------------------------------------------------------------------------

## 💡 Goal

Understand how your play differs from optimal strategy and improve over
time.
