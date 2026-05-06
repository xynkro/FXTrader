# TradingView MCP — strategy research workflow (self-instruction)

**Purpose**: Standing rules for how I (Claude, working on FXTrader) use the
TradingView MCP server to find, inspect, summarise, code, and backtest
trading strategies — both from TV's Pine Script library and from external
sources (YouTube transcripts via Apify).

**Created**: 2026-05-06 — locked together with the v3/v4/v5 disciplines
already in `docs/`. This file extends, not replaces, those rules.

---

## The six rules (verbatim from user)

1. **Always use the MCP server for TradingView whenever it is relevant for
   retrieving, analyzing, or processing data.**
2. **When asked for trading strategies, first look for strategies from
   TradingView.**
3. **Summarise the strategy clearly before coding it** (Strategy Name,
   Core Logic, Entry Conditions, Exit Conditions, Risk Management Rules,
   Any Indicators or Parameters Used).
4. **After summarising, convert it into clean, working code.**
5. **Do not invent features that are not present** unless they are
   labelled as optional improvements.
6. **Run a backtest** using the MCP on the said strategy.

---

## TradingView MCP — tool inventory

| Tool | Purpose | Asset class |
|---|---|---|
| `tv_search_scripts` | Keyword-search TV's open-source Pine Script library by query, type, etc. Returns slug, title, author, likes. | All |
| `tv_get_script` | Fetch full Pine Script source by slug or URL. Open-source only. | All |
| `tv_analyze` | Real-time aggregated TA summary (BUY/SELL/NEUTRAL + RSI/MACD/EMA/BB/ATR values) for one symbol. | Equity / FX / Crypto |
| `tv_multi_analyze` | Same TA summary for a list of symbols at once. | Equity / FX / Crypto |
| `tv_screener_scan` | Filter symbols by TA recommendation + RSI range. | Equity / FX / Crypto |
| `tv_crypto_scan` | Top crypto pairs ranked by TA / RSI on Binance/Bybit/Coinbase/Kraken. | Crypto only |
| `tv_history` | OHLCV via Yahoo Finance (FX uses `EURUSD=X` style). | All |
| `tv_candles` | Live OHLCV from Binance/Bybit REST (no auth). | Crypto only |
| `tv_vwap` | VWAP + bands on Binance/Bybit candles. | Crypto only |

**Caveats locked in**:
- `tv_history` is Yahoo-sourced, not OANDA. For FX, OANDA's `download_history.py`
  remains the source of truth for our backtest harness; `tv_history` is for
  cross-validation and instruments OANDA doesn't carry (e.g. NASDAQ tickers).
- `tv_candles` and `tv_vwap` are crypto-only. Not used for FXTrader.
- The MCP **does not include a backtest engine**. Rule #6 is implemented via
  our existing Python harness (`run_backtest()` in `backend/app/backtest.py`).

---

## Workflow A — TradingView Pine Script strategies

```
Step 1: Search
  tv_search_scripts(query, script_type="strategy", open_source_only=True, limit=20)
  → ranked list of slugs with author + likes

Step 2: Pull source
  tv_get_script(slug)
  → full Pine Script + metadata (title, author, version)

Step 3: Summarise (Pre-coding gate — no code until this is presented and
        confirmed faithful to source)

  Strategy Name      :  ...
  Source             :  TradingView slug + URL + author handle
  Core Logic         :  one-paragraph mechanism story (how it claims to make money)
  Entry Conditions   :  long: ...
                        short: ...
  Exit Conditions    :  ...
  Risk Management    :  position sizing rule, stop placement, target rule
  Indicators / Params:  list with default settings from source
  Author claims      :  any historical performance the script's description claims
  Skepticism note    :  red flags spotted in the Pine code (lookahead, repainting,
                        unrealistic fills, missing friction, hardcoded magic numbers)

Step 4: Convert to our codebase
  Add an evaluator function in backend/app/strategy.py following the
  evaluate_pullback() pattern. Register in STRATEGIES dict.
  Naming: evaluate_<author_handle>_<short_name>, e.g. evaluate_lazybear_squeeze

Step 5: Pre-register validation bars BEFORE running backtest
  - Friction model: 1.0 pip spread + 0.4 pip slippage (2× retail FX defaults)
    or instrument-appropriate for non-FX
  - IS/OOS split: 80/20
  - Freshness window: data NOT in the source's claimed validation window
  - Bars: minimum Sharpe, CAGR, PF, max DD, trades/yr, yearly positive count
  - Falsification triggers: WR-up-but-expectancy-down, PF-unchanged-from-baseline, etc.
  - Lock document in docs/strategy-eval-<name>.md before any test runs

Step 6: Run backtest
  Use run_backtest() from backend/app/backtest.py.
  Friction-shocked. Output saved to backend/data/backtest_results/.

Step 7: Apply decision rule
  - All bars passed → CANDIDATE for v5/v6 demo cycle (queued behind current
    deployment + v4)
  - Any bar failed → KILLED. Document why. Do not re-run with adjusted bars.
  - Falsification trigger fired → KILLED regardless of numerical bars.
```

## Workflow B — YouTube transcripts via Apify (Strategy Extraction)

When the user pastes Apify-scraped YouTube transcripts:

```
Step 1: Read all pasted content carefully.

Step 2: Extract per the structured prompt:
  - Indicators: each one, settings (if mentioned), what it's used for
  - Entry conditions: separate LONG vs SHORT
  - Avoid conditions: red flags / staying-out criteria
  - Risk management: sizing, stop placement, take-profit
  - Timeframes: HTF for bias, LTF for entry

Step 3: Output rules.json in the EXACT user-provided structure:
  {
    "watchlist": ["..."],
    "default_timeframe": "...",
    "strategy": { "name": "...", "sources": ["@handle / video title"] },
    "indicators": { "indicator_key": "what it tells you" },
    "bias_criteria": {
      "bullish": [...], "bearish": [...], "neutral": [...]
    },
    "entry_rules": { "long": [...], "short": [...] },
    "exit_rules": [...],
    "risk_rules": [...],
    "notes": ""
  }

Step 4: Save as rules.json in the current working directory.

Step 5: Treat the rules.json as the equivalent of Step 3 above (summary)
        in Workflow A, then proceed to Workflow A Steps 4-7 with the
        rules.json as the source spec.
```

---

## Locked answers (resolved 2026-05-06)

**A1 — Backtest engine**: Use our existing Python harness
(`backend/app/backtest.py`'s `run_backtest()`). Less token-intensive,
already friction-aware, IS/OOS-ready. The MCP itself does NOT include a
backtest engine. Use `tv_history` or our `download_history.py` for data
acquisition only.

**A2 — Cross-instrument-class strategies**: Default behavior is **(B)** —
summarise faithfully, flag "**not deployable on FXTrader without
redesign**", and stop. **(C)** behavior — testing on the original
instrument class first via `tv_history` for source-verification — only
on explicit user request.

**A3 — Live deployment**: TV / YouTube-sourced strategies **CAN** go
live on the OANDA practice demo once they pass disciplined backtest
filters. The user's framing: *"the backtest is to filter and the demo
is the final filter."* The demo is a real cycling environment for
candidates that survive backtest. **BUT** — see A5 — never autonomously.

**A4 — `rules.json` location**: project root `~/Documents/Trading/FXTrader/rules.json`.
Single file, represents the CURRENTLY-EXTRACTED candidate. Previous
versions archived to `docs/strategies/archive/<date>_<name>.json` if
overwritten.

**A5 — Engine state authority**: NEVER touch the live PWA / OANDA engine
without an explicit user instruction to do so. Even if A3 allows live
deployment in principle, the actual flip from one strategy to another
requires the user to say so explicitly. *Default state: Pullback H1,
USD_JPY, 0.25% — untouched.*

---

## Hard discipline rules (apply to BOTH workflows)

These are non-negotiable. They extend the v3/v4/v5 disciplines documented
elsewhere in `docs/`:

1. **Source attribution**: every strategy summary and every `rules.json`
   includes the original creator + URL/handle. No anonymous strategies.
2. **No invented details**: if the source doesn't specify it, it doesn't go
   in the summary or rules.json. Gaps are flagged as "not specified in source"
   not silently filled with defaults.
3. **Optional improvements labeled separately**: anything I think *should*
   be added (e.g. friction model, kill switch, position sizing rule) goes
   in a clearly-marked "Optional improvements" section, NOT in the
   strategy spec / rules.json.
4. **Pre-registration before testing**: bars locked in a `.md` document
   before any backtest runs. No "let me just see what happens if..."
5. **Friction-shocked**: every backtest uses 2× retail friction by default
   (1.0p spread + 0.4p slippage on FX). Source claims with no friction
   ("on chart" Pine results) are treated as upper-bound fantasy.
6. **Truly fresh data for OOS**: validation runs on data NOT mentioned by
   the source's claimed test window. If unknown, default to using the
   most recent 20% as held-out OOS.
7. **Cross-instrument-class strategies**: per A2, default to "summarise
   + flag not deployable" (B); only run cross-class tests (C) on
   explicit user request.
8. **Live deployment is GATED on explicit user instruction** (per A5),
   even when backtest passes (per A3). The flow is:
   - Backtest passes → candidate is **ready**
   - User says "deploy candidate X" → I flip the engine
   - No autonomous live changes regardless of backtest result
9. **Skepticism baseline**: any TV-published or YouTube-pitched strategy
   is presumed curve-fit until cross-window validation proves otherwise.
   The `forexfury` / `galileofx` research from 2026-05-06 is the
   cautionary baseline — high-WR scalper claims are almost universally
   tail-risk-selling in disguise.
10. **One strategy at a time**: don't compound multiple TV strategies into
    a "best of breed" — that's the meta-overfitting trap.

---

## Cross-references

- Live deployment discipline: `docs/pullback-m15-v3-research-plan.md`
- Multi-instrument plan: `docs/pullback-v4-multiinstrument-spec.md`
- v5 pivot candidates: `docs/strategy-pivot-2026-05-06.md`
- Falsified strategies log (institutional memory): the v2/v3 docs above

---

## Audit log

| Date | Source | Strategy | Verdict |
|---|---|---|---|
| 2026-05-06 | (workflow created) | — | — |
