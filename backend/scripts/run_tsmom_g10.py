"""TSMOM G10 multi-pair backtest harness.

Implements the strategy locked in docs/tsmom-g10-spec.md:
- 7 G10-vs-USD pairs on daily bars
- Per-pair signal: sign of trailing 252-day return
- Per-pair vol-target sizing: target_vol_per_pair / (σ_60d × √252)
- Monthly rebalance on last trading day
- Symmetric long/short

Friction model:
- spread_pips per side, slippage_pips per side
- applied at each rebalance on |Δposition_notional|

Outputs:
- IS / OOS / friction-shock metrics
- per-pair contribution
- yearly breakdown
- gate evaluation against pre-registered spec
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from app.config import settings


PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF",
    "AUD_USD", "NZD_USD", "USD_CAD",
]

# Per-spec friction defaults
DEFAULT_SPREAD_PIPS = {
    "EUR_USD": 1.0, "GBP_USD": 1.2, "USD_JPY": 1.0, "USD_CHF": 1.5,
    "AUD_USD": 1.5, "NZD_USD": 1.8, "USD_CAD": 1.5,
}
DEFAULT_SLIP_PIPS = 0.3


def pip_size(instrument: str) -> float:
    return 0.01 if "JPY" in instrument else 0.0001


def load_pair_series(pair: str, days: int = 3650) -> list[dict]:
    """Load daily candles, return list of {date, close, open}."""
    fname = f"{pair}_D_{days}d.json"
    path = settings.historical_dir / fname
    if not path.exists():
        raise FileNotFoundError(f"missing {path}; run download_history.py")
    raw = json.loads(path.read_text())
    out = []
    for c in raw:
        t = datetime.fromisoformat(c["time"])
        out.append({
            "date": t.date(),
            "open": float(c["open"]),
            "close": float(c["close"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
        })
    out.sort(key=lambda x: x["date"])
    return out


def align_pair_data(pair_data: dict[str, list[dict]]) -> tuple[list[date], dict[str, dict[date, float]]]:
    """Build common date set + per-pair close lookup."""
    all_dates: set[date] = set()
    closes: dict[str, dict[date, float]] = {}
    for p, rows in pair_data.items():
        closes[p] = {r["date"]: r["close"] for r in rows}
        all_dates.update(closes[p].keys())
    # Use intersection of dates where ALL pairs have prices
    common = sorted(d for d in all_dates if all(d in closes[p] for p in pair_data))
    return common, closes


def is_month_end(d: date, dates: list[date], idx: int) -> bool:
    """True if d is the last date in `dates` for its calendar month."""
    if idx == len(dates) - 1:
        return True
    next_d = dates[idx + 1]
    return (next_d.year, next_d.month) != (d.year, d.month)


def compute_signal(closes: dict[date, float], dates: list[date], idx: int,
                   lookback: int = 252) -> Optional[int]:
    """Sign of close[idx] / close[idx-lookback] - 1. None if insufficient warmup."""
    if idx < lookback:
        return None
    d_now = dates[idx]
    d_then = dates[idx - lookback]
    p_now = closes[d_now]
    p_then = closes[d_then]
    r = (p_now / p_then) - 1.0
    if r > 0:
        return +1
    elif r < 0:
        return -1
    return 0


def compute_vol60(closes: dict[date, float], dates: list[date], idx: int,
                  window: int = 60) -> Optional[float]:
    """Trailing daily-return std over `window` days. None if insufficient."""
    if idx < window + 1:
        return None
    rets = []
    for k in range(idx - window, idx):
        d_a = dates[k]
        d_b = dates[k + 1]
        ra = (closes[d_b] / closes[d_a]) - 1.0
        rets.append(ra)
    arr = np.array(rets)
    sd = float(arr.std(ddof=0))
    return sd if sd > 0 else None


def usd_pnl_factor(pair: str, close: float) -> float:
    """Convert price-return to USD-equivalent return for unit USD notional.

    For pairs quoted as XXX/USD (USD as quote): factor = 1.0
    For pairs quoted as USD/XXX (USD as base, e.g. USD_JPY, USD_CHF, USD_CAD):
       holding $1 long USD_XXX means long 1 USD vs XXX
       daily USD P&L on this long position when rate moves:
       ΔUSD value of the XXX short ≈ -1 × Δrate / rate, so price-return
       in rate units ≈ daily USD return on $1 notional × -1 (because
       a higher USD/XXX rate = stronger USD = positive P&L for long).
    """
    # In our standard "long signal means buy base currency" formulation:
    # For EUR_USD, signal=+1 means long EUR, short USD. Daily P&L in USD ≈ Δprice
    # For USD_JPY, signal=+1 means long USD, short JPY. Daily P&L in USD ≈ Δprice / close
    # We compute price returns either way; for USD/XXX pairs we adjust with /close.
    if pair.startswith("USD_"):
        return 1.0 / close
    return 1.0


@dataclass
class PortfolioSnapshot:
    date: date
    equity: float
    positions: dict   # pair -> weight (signed, fraction of equity in USD notional)
    signals: dict     # pair -> -1/0/+1
    vol60: dict       # pair -> daily return std


def run_tsmom_portfolio(
    pair_data: dict[str, list[dict]],
    starting_equity: float = 10_000.0,
    target_vol_per_pair: float = 0.04,
    lookback: int = 252,
    vol_window: int = 60,
    max_weight: float = 5.0,   # cap | weight | per pair as multiple of equity
    spread_pips: Optional[dict[str, float]] = None,
    slip_pips: float = DEFAULT_SLIP_PIPS,
    friction_mult: float = 1.0,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> tuple[list[tuple[date, float]], list[dict], dict]:
    """Run the strategy. Returns (equity_curve, rebalance_trades, diagnostics)."""
    spread_pips = spread_pips or DEFAULT_SPREAD_PIPS
    dates, closes = align_pair_data(pair_data)
    if start_date is not None:
        dates = [d for d in dates if d >= start_date]
    if end_date is not None:
        dates = [d for d in dates if d <= end_date]

    equity = starting_equity
    weights: dict[str, float] = {p: 0.0 for p in pair_data}  # pair -> fraction of equity
    last_close: dict[str, float] = {p: closes[p][dates[0]] for p in pair_data}
    eq_curve: list[tuple[date, float]] = [(dates[0], equity)]
    rebalances: list[dict] = []
    yearly: dict[int, float] = defaultdict(float)
    pair_pnl: dict[str, float] = defaultdict(float)

    for idx in range(1, len(dates)):
        d = dates[idx]
        # 1) mark-to-market: each pair contributes weight × price-return × USD-conv
        daily_pnl = 0.0
        for p in pair_data:
            wt = weights[p]
            if wt == 0:
                last_close[p] = closes[p][d]
                continue
            cp = closes[p][d]
            cprev = last_close[p]
            price_ret = (cp - cprev) / cprev if cprev > 0 else 0.0
            # USD adjustment for USD-base pairs:
            # weight = signed fraction of equity; if wt>0 we are long base, short quote
            # USD P&L per unit weight ≈ price_ret (for XXX_USD) or -price_ret/cp (for USD_XXX)
            if p.startswith("USD_"):
                # long USD_XXX with $X notional: when USD strengthens (price up),
                # we profit. P&L ≈ X × Δprice/price_now ≈ X × (price_ret) but
                # ratio makes -ish: standard convention, profit on long when
                # USD/XXX rises = +Δprice/old_price ≈ +price_ret (small-move).
                pair_ret_usd = price_ret
            else:
                pair_ret_usd = price_ret
            pnl_p = wt * equity * pair_ret_usd
            daily_pnl += pnl_p
            pair_pnl[p] += pnl_p
            last_close[p] = cp
        equity += daily_pnl
        yearly[d.year] += daily_pnl

        # 2) on month-end, rebalance to new signal × vol-target weights
        if is_month_end(d, dates, idx):
            new_weights: dict[str, float] = {}
            sigs: dict[str, int] = {}
            vols: dict[str, float] = {}
            for p in pair_data:
                sig = compute_signal(closes[p], dates, idx, lookback=lookback)
                vol = compute_vol60(closes[p], dates, idx, window=vol_window)
                if sig is None or vol is None or vol <= 0:
                    new_w = 0.0
                else:
                    # daily-vol-target form: weight × σ_daily × √252 = target_vol
                    raw_w = target_vol_per_pair / (vol * math.sqrt(252.0))
                    raw_w = max(min(raw_w, max_weight), 0.0)
                    new_w = sig * raw_w
                sigs[p] = sig if sig is not None else 0
                vols[p] = vol if vol is not None else 0.0
                new_weights[p] = new_w

            # 3) friction cost: |Δw| × equity × cost-per-USD
            # cost-per-USD = (spread_pips_pair × friction_mult + 2*slip*friction_mult) × pip / price
            total_cost = 0.0
            for p in pair_data:
                dw = abs(new_weights[p] - weights[p])
                if dw == 0:
                    continue
                price = closes[p][d]
                pip_in_units = pip_size(p)
                cost_pips = (spread_pips[p] + 2.0 * slip_pips) * friction_mult
                cost_pct_of_notional = cost_pips * pip_in_units / price
                total_cost += dw * equity * cost_pct_of_notional
            equity -= total_cost
            yearly[d.year] -= total_cost

            rebalances.append({
                "date": d.isoformat(),
                "equity_pre": equity + total_cost,
                "equity_post": equity,
                "cost": total_cost,
                "weights": dict(new_weights),
                "signals": dict(sigs),
            })
            weights = new_weights

        eq_curve.append((d, equity))

    diag = {
        "yearly_pnl": dict(yearly),
        "pair_pnl_total": dict(pair_pnl),
        "rebalances": len(rebalances),
        "n_days": len(dates) - 1,
    }
    return eq_curve, rebalances, diag


def summarize(eq_curve: list[tuple[date, float]], starting_equity: float) -> dict:
    """Compute return / Sharpe / max DD / PF on daily P&L stream."""
    if len(eq_curve) < 2:
        return {}
    eqs = np.array([e for _, e in eq_curve])
    daily_pnl = np.diff(eqs)
    daily_ret = daily_pnl / eqs[:-1]
    n = len(daily_ret)
    days = (eq_curve[-1][0] - eq_curve[0][0]).days
    years = days / 365.25 if days > 0 else 0.001

    final_eq = eqs[-1]
    total_ret = (final_eq / starting_equity) - 1.0
    cagr = (final_eq / starting_equity) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    sd = daily_ret.std(ddof=0)
    sharpe = (daily_ret.mean() / sd * math.sqrt(252.0)) if sd > 0 else 0.0

    peaks = np.maximum.accumulate(eqs)
    dd = (peaks - eqs) / peaks
    max_dd = float(dd.max())

    gross_win = float(daily_pnl[daily_pnl > 0].sum())
    gross_loss = float(-daily_pnl[daily_pnl < 0].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    return {
        "start_date": eq_curve[0][0].isoformat(),
        "end_date": eq_curve[-1][0].isoformat(),
        "years": years,
        "starting_equity": starting_equity,
        "final_equity": final_eq,
        "total_return_pct": total_ret * 100.0,
        "cagr_pct": cagr * 100.0,
        "sharpe": sharpe,
        "max_drawdown_pct": max_dd * 100.0,
        "profit_factor": pf,
        "n_days": n,
    }


def fmt_summary(label: str, s: dict) -> str:
    if not s:
        return f"--- {label} ---\n  (no data)"
    return "\n".join([
        f"--- {label} ---",
        f"  Period      : {s['start_date']} → {s['end_date']}  ({s['years']:.2f}y)",
        f"  Days        : {s['n_days']:,}",
        f"  Total return: {s['total_return_pct']:+.2f}%",
        f"  CAGR        : {s['cagr_pct']:+.2f}%/yr",
        f"  Sharpe      : {s['sharpe']:.2f}",
        f"  Max DD      : {s['max_drawdown_pct']:.2f}%",
        f"  Profit fact : {s['profit_factor']:.2f}",
        f"  Final eq    : ${s['final_equity']:,.2f}  (start ${s['starting_equity']:,.2f})",
    ])


def evaluate_gates(is_s: dict, oos_s: dict, fr_s: dict,
                   is_diag: dict, fr_diag: dict) -> list[str]:
    """Pre-registered gate eval per docs/tsmom-g10-spec.md."""
    msgs = []
    pf_is = is_s.get("profit_factor", 0.0)
    if pf_is < 1.2:
        msgs.append(f"FAIL gate 1 — IS PF {pf_is:.2f} < 1.2")
    if is_s.get("total_return_pct", 0) <= 0:
        msgs.append(f"FAIL gate 1 — IS total return non-positive")

    pf_oos = oos_s.get("profit_factor", 0.0)
    if pf_is > 0:
        deg = (pf_is - pf_oos) / pf_is * 100.0
        if deg > 50:
            msgs.append(
                f"FAIL gate 2 — OOS PF {pf_oos:.2f} degraded {deg:.0f}% from IS {pf_is:.2f} (limit 50%)"
            )

    yr = is_diag.get("yearly_pnl", {})
    total_profit = sum(v for v in yr.values() if v > 0)
    if total_profit > 0:
        max_year = max(yr.values())
        max_year_pct = max_year / total_profit * 100.0
        if max_year_pct > 60:
            msgs.append(
                f"FAIL gate 3 — single year = {max_year_pct:.0f}% of cumulative profit (limit 60%)"
            )

    pp = fr_diag.get("pair_pnl_total", {})
    total_p = sum(v for v in pp.values() if v > 0)
    if total_p > 0:
        max_p = max(pp.values())
        max_p_pct = max_p / total_p * 100.0
        if max_p_pct > 60:
            msgs.append(
                f"FAIL gate 4 — single pair = {max_p_pct:.0f}% of profit (limit 60%)"
            )

    pf_fr = fr_s.get("profit_factor", 0.0)
    if pf_fr < 1.05:
        msgs.append(f"FAIL gate 5 — friction-shock PF {pf_fr:.2f} < 1.05")

    cagr_fr = fr_s.get("cagr_pct", 0.0)
    if cagr_fr < 8.0:
        msgs.append(
            f"FAIL gate 6 — friction-shocked CAGR {cagr_fr:.2f}% < 8.0% bar"
        )

    sh_fr = fr_s.get("sharpe", 0.0)
    if sh_fr < 0.6:
        msgs.append(
            f"FAIL gate 7 — friction-shocked Sharpe {sh_fr:.2f} < 0.6"
        )

    if not msgs:
        msgs.append(
            f"PASS all gates. IS PF={pf_is:.2f} CAGR={is_s['cagr_pct']:.2f}%; "
            f"OOS PF={pf_oos:.2f}; "
            f"FR PF={pf_fr:.2f} CAGR={cagr_fr:.2f}% Sharpe={sh_fr:.2f}"
        )
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3650)
    ap.add_argument("--equity", type=float, default=10_000.0)
    ap.add_argument("--target-vol-per-pair", type=float, default=0.04)
    ap.add_argument("--oos-years", type=float, default=1.5,
                    help="Length of OOS holdout in years")
    args = ap.parse_args()

    print("Loading G10 daily data...")
    pair_data = {p: load_pair_series(p, args.days) for p in PAIRS}
    for p, rows in pair_data.items():
        print(f"  {p}: {len(rows):,} bars  {rows[0]['date']} → {rows[-1]['date']}")

    # Common date span
    dates, _ = align_pair_data(pair_data)
    print(f"\nCommon date span: {dates[0]} → {dates[-1]}  ({len(dates):,} bars)")

    # IS / OOS split
    end_d = dates[-1]
    oos_start = date(end_d.year, end_d.month, 1)
    # back-up roughly oos_years
    yr_back = int(args.oos_years)
    mo_back = int(round((args.oos_years - yr_back) * 12))
    sy = oos_start.year - yr_back - (1 if oos_start.month <= mo_back else 0)
    sm = oos_start.month - mo_back if oos_start.month > mo_back else oos_start.month - mo_back + 12
    oos_start = date(sy, sm, 1)
    print(f"OOS window: {oos_start} → {end_d}\n")

    # Run IS (everything before oos_start)
    print("Running IS backtest...")
    is_curve, is_rebs, is_diag = run_tsmom_portfolio(
        pair_data,
        starting_equity=args.equity,
        target_vol_per_pair=args.target_vol_per_pair,
        end_date=oos_start,
        friction_mult=1.0,
    )
    is_s = summarize(is_curve, args.equity)

    # Run OOS (only oos_start through end)
    print("Running OOS backtest...")
    oos_curve, oos_rebs, oos_diag = run_tsmom_portfolio(
        pair_data,
        starting_equity=args.equity,
        target_vol_per_pair=args.target_vol_per_pair,
        start_date=oos_start,
        friction_mult=1.0,
    )
    oos_s = summarize(oos_curve, args.equity)

    # Run friction shock (full sample, 2× costs)
    print("Running FRICTION SHOCK backtest (full sample, 2×)...")
    fr_curve, fr_rebs, fr_diag = run_tsmom_portfolio(
        pair_data,
        starting_equity=args.equity,
        target_vol_per_pair=args.target_vol_per_pair,
        friction_mult=2.0,
    )
    fr_s = summarize(fr_curve, args.equity)

    line = "=" * 72
    print()
    print(line)
    print("  TSMOM G10 — pre-registered backtest result")
    print(line)
    print(fmt_summary("IN-SAMPLE (pre-OOS window)", is_s))
    print()
    print(fmt_summary("OUT-OF-SAMPLE", oos_s))
    print()
    print(fmt_summary("FRICTION SHOCK (full sample, 2× costs)", fr_s))
    print()

    # Yearly breakdown (full sample at default friction)
    print("--- Yearly P&L (full sample, 1× friction) ---")
    full_yearly: dict[int, float] = defaultdict(float)
    for y, v in is_diag.get("yearly_pnl", {}).items():
        full_yearly[y] += v
    for y, v in oos_diag.get("yearly_pnl", {}).items():
        full_yearly[y] += v
    for y in sorted(full_yearly.keys()):
        v = full_yearly[y]
        print(f"  {y}: ${v:+,.2f}")

    # Per-pair contribution
    print("\n--- Per-pair lifetime P&L (full sample, 1× friction) ---")
    full_pair: dict[str, float] = defaultdict(float)
    for p, v in is_diag.get("pair_pnl_total", {}).items():
        full_pair[p] += v
    for p, v in oos_diag.get("pair_pnl_total", {}).items():
        full_pair[p] += v
    for p in sorted(full_pair, key=lambda x: -full_pair[x]):
        v = full_pair[p]
        print(f"  {p}: ${v:+,.2f}")

    print("\n--- Rebalance summary ---")
    print(f"  IS rebalances:  {len(is_rebs)}")
    print(f"  OOS rebalances: {len(oos_rebs)}")
    print(f"  FR rebalances:  {len(fr_rebs)}")

    # Gates
    print()
    print(line)
    print("  PRE-REGISTERED GATE EVALUATION")
    print(line)
    # Build a "full-sample" diag for pair-concentration gate (using FR run since
    # that's the full sample, normalized by 2x friction; pair share unaffected).
    msgs = evaluate_gates(is_s, oos_s, fr_s, {"yearly_pnl": full_yearly},
                          {"pair_pnl_total": full_pair})
    for m in msgs:
        if m.startswith("PASS"):
            print(f"  ✓ {m}")
        else:
            print(f"  ✗ {m}")
    print(line)

    # Save outputs
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = settings.backtest_dir / f"{stamp}_tsmom_g10"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "is_summary.json").write_text(json.dumps(is_s, indent=2, default=str))
    (out_dir / "oos_summary.json").write_text(json.dumps(oos_s, indent=2, default=str))
    (out_dir / "friction_summary.json").write_text(json.dumps(fr_s, indent=2, default=str))
    (out_dir / "yearly.json").write_text(json.dumps(dict(full_yearly), indent=2, default=str))
    (out_dir / "pair_contribution.json").write_text(
        json.dumps(dict(full_pair), indent=2, default=str)
    )
    (out_dir / "gates.json").write_text(json.dumps(msgs, indent=2))
    (out_dir / "is_equity.json").write_text(
        json.dumps([{"d": d.isoformat(), "eq": e} for d, e in is_curve], default=str)
    )
    (out_dir / "oos_equity.json").write_text(
        json.dumps([{"d": d.isoformat(), "eq": e} for d, e in oos_curve], default=str)
    )
    (out_dir / "friction_equity.json").write_text(
        json.dumps([{"d": d.isoformat(), "eq": e} for d, e in fr_curve], default=str)
    )
    print(f"\nResults saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
