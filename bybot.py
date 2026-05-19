"""
╔══════════════════════════════════════════════════════════════╗
║         PRO ANALYTICS — BYBIT FUTURES TRADING ENGINE         ║
║   Bybit USDT Perpetual | Paper | Backtest                    ║
║   EMA + RSI + ADX + Volume | MTF | Trailing Stop             ║
╚══════════════════════════════════════════════════════════════╝

  РЕЖИМЫ:
    MODE = "backtest"  → исторический тест за выбранный период
    MODE = "paper"     → демо счёт, реальные цены, без денег
    MODE = "live"      → реальная торговля Bybit USDT Perpetual

  УСТАНОВКА:
    pip install pybit ta pandas requests python-dotenv

  .env файл (создай рядом со скриптом):
    BYBIT_API_KEY=ключ
    BYBIT_API_SECRET=секрет
    TG_TOKEN=токен
    TG_CHAT_ID=id_чата
"""

from pybit.unified_trading import HTTP
from datetime import datetime, timezone
from dotenv import load_dotenv
import pandas as pd
import requests
import json
import math
import time
import os
import ta

load_dotenv()

# ══════════════════════════════════════════════════════════════
#  ⚙️  ГЛАВНЫЕ НАСТРОЙКИ — ИДЕНТИЧНО СТАРОМУ ПРИБЫЛЬНОМУ КОДУ
# ══════════════════════════════════════════════════════════════

MODE = "paper"
# "backtest" | "paper" | "live"

# ── Период бэктеста ──────────────────────────────────────────
# BACKTEST_START = "2022-01-01"
# BACKTEST_END   = "2025-01-01"

# ── Баланс и риск ────────────────────────────────────────────
STARTING_BALANCE   = 400.0
RISK_PERCENT       = 1.0
MAX_RISK_PER_TRADE = 200.0
MAX_OPEN_POSITIONS = 10
LEVERAGE           = 5

# ── Стратегия — ВСЕ ПАРАМЕТРЫ КАК В СТАРОМ ПРИБЫЛЬНОМ КОДЕ ──
COMMISSION           = 0.001
REWARD_RATIO         = 3.0
TRAIL_ACTIVATE       = 1.2
TRAIL_STEP           = 0.4
CONFIDENCE_MIN       = 70
ADX_MIN              = 25
ALLOW_BUY            = True   # только SELL — как в прибыльном коде
RSI_LONG_MIN         = 52
RSI_SHORT_MAX        = 48
MAX_CANDLES_IN_TRADE = 16
COOLDOWN_CANDLES     = 5
SESSION_START_UTC    = 0
SESSION_END_UTC      = 24

# ── Уведомления ──────────────────────────────────────────────
DD_ALERT_THRESHOLD = 10.0
SCAN_INTERVAL_MIN  = 15

# ── API (из .env) ─────────────────────────────────────────────
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY",    "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
TG_TOKEN         = os.getenv("TG_TOKEN",         "")
TG_CHAT_ID       = os.getenv("TG_CHAT_ID",       "")

PAPER_ACCOUNT_FILE = "paper_account.json"

# ── Маппинг интервалов Bybit ──────────────────────────────────
TF_M15 = "15"    # 15 минут
TF_H1  = "60"    # 1 час

# ── Активы — Bybit USDT Perpetual ────────────────────────────
ASSETS = [
    {"symbol": "BTCUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "ETHUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "SOLUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "XRPUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "AVAXUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "LINKUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "DOTUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "LTCUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "ATOMUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "INJUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "DOGEUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "SUIUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "OPUSDT",   "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "STXUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "WLDUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "ARBUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "FETUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "RNDRUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
    {"symbol": "TIAUSDT",  "tf_m15": TF_M15, "tf_h1": TF_H1, "live": False},
]


# ══════════════════════════════════════════════════════════════
#  CLIENT — BYBIT
# ══════════════════════════════════════════════════════════════

def make_session(auth: bool = False) -> HTTP:
    if auth:
        if not BYBIT_API_KEY or not BYBIT_API_SECRET:
            raise RuntimeError("❌ API ключи не найдены в .env файле!")
        return HTTP(api_key=BYBIT_API_KEY, api_secret=BYBIT_API_SECRET)
    return HTTP()  # публичный доступ для paper/backtest


session = make_session(auth=(MODE == "live"))


# ══════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════

def tg_send(text: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            print(f"  WARNING Telegram: {r.text}")
    except Exception as e:
        print(f"  WARNING Telegram недоступен: {e}")


def tg_startup():
    labels = {"backtest": "BACKTEST", "paper": "PAPER DEMO", "live": "LIVE BYBIT"}
    period = ""
    if MODE == "backtest":
        s = BACKTEST_START or "начало данных"
        e = BACKTEST_END   or "сегодня"
        period = f"Период : {s} -> {e}\n"
    tg_send(
        f"{labels.get(MODE, MODE)} запущен\n"
        f"Баланс : ${STARTING_BALANCE:.2f}\n"
        f"{period}"
        f"Активы : {', '.join(a['symbol'] for a in ASSETS)}\n"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


def tg_backtest_report(balance, profit, pct, total, winrate,
                       pf, rr, dd, expectancy, p_start, p_end, breakdown):
    lines = ""
    for sym, d in sorted(breakdown.items(), key=lambda x: -x[1]["pnl"]):
        wr   = d["wins"] / d["trades"] * 100 if d["trades"] else 0
        sign = "+" if d["pnl"] >= 0 else ""
        lines += f"  {sym:<10} {d['trades']}tr  WR={wr:.0f}%  ${sign}{d['pnl']:.0f}\n"
    tg_send(
        f"BACKTEST ЗАВЕРШЁН\n"
        f"--------------------\n"
        f"{p_start.strftime('%d.%m.%Y')} -> {p_end.strftime('%d.%m.%Y')}\n"
        f"Старт   : ${STARTING_BALANCE:.2f}\n"
        f"Финал   : ${balance:.2f}\n"
        f"Прибыль : ${profit:+.2f}  ({pct:+.1f}%)\n"
        f"--------------------\n"
        f"Сделок  : {total}   WR={winrate:.1f}%\n"
        f"Expect  : ${expectancy:.2f}/сделка\n"
        f"PF={pf:.2f}  RR={rr:.2f}  DD={dd:.1f}%\n"
        f"--------------------\n"
        f"По активам:\n{lines}"
    )


# ══════════════════════════════════════════════════════════════
#  DATA LOADER — BYBIT KLINES
# ══════════════════════════════════════════════════════════════

def load_bybit(symbol: str, interval: str, limit: int,
               start: str = None, end: str = None) -> pd.DataFrame:

    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000) if start else None
    end_ms   = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) if end else int(time.time() * 1000)

    all_klines = []

    # =========================================================
    # BACKTEST MODE
    # =========================================================
      # =========================================================
    # BACKTEST MODE
    # =========================================================
    if start_ms:

        cur_start = start_ms

        while True:

            try:
                resp = session.get_kline(
                    category="linear",
                    symbol=symbol,
                    interval=interval,
                    start=cur_start,
                    limit=1000,
                )

            except Exception as e:
                print(f"  WARNING {symbol}: {e}")
                break

            data = resp.get("result", {}).get("list", [])

            if not data:
                print(f"  {symbol}: данных больше нет")
                break

            # Bybit отдаёт новые -> старые
            data = list(reversed(data))

            filtered = []

            for row in data:

                ts = int(row[0])

                # фильтр конца периода
                if ts > end_ms:
                    continue

                filtered.append(row)

            if not filtered:
                break

            all_klines.extend(filtered)

            first_ts = int(filtered[0][0])
            last_ts  = int(filtered[-1][0])

            print(
                f"  {symbol}: "
                f"{pd.to_datetime(first_ts, unit='ms')} "
                f"-> "
                f"{pd.to_datetime(last_ts, unit='ms')} "
                f"| total={len(all_klines)}"
            )

            # защита от зацикливания
            if last_ts <= cur_start:
                print(f"  {symbol}: обнаружено зацикливание")
                break

            # следующий батч
            cur_start = last_ts + 1

            # если пришло меньше 1000 свечей
            if len(data) < 1000:
                print(f"  {symbol}: история закончилась")
                break

            # защита
            if len(all_klines) >= limit:
                print(f"  {symbol}: достигнут limit={limit}")
                break

            # anti rate-limit
            time.sleep(0.35)

    # =========================================================
    # PAPER / LIVE MODE
    # =========================================================
    else:

        cur_end = end_ms

        while len(all_klines) < limit:

            try:
                resp = session.get_kline(
                    category="linear",
                    symbol=symbol,
                    interval=interval,
                    end=cur_end,
                    limit=1000,
                )

            except Exception as e:
                print(f"  WARNING {symbol}: {e}")
                break

            data = resp.get("result", {}).get("list", [])

            if not data:
                break

            data = list(reversed(data))

            all_klines = data + all_klines

            cur_end = int(data[0][0]) - 1

            if len(all_klines) >= limit:
                break

            time.sleep(0.1)

        all_klines = all_klines[-limit:]

    # =========================================================
    # EMPTY
    # =========================================================
    if not all_klines:
        return pd.DataFrame()

    # =========================================================
    # DATAFRAME
    # =========================================================
    df = pd.DataFrame(
        all_klines,
        columns=[
            "time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "turnover"
        ]
    )

    df = df[["time", "open", "high", "low", "close", "volume"]]

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["time"] = pd.to_datetime(
        df["time"].astype(int),
        unit="ms",
        utc=True
    )

    df = (
        df
        .drop_duplicates(subset=["time"])
        .sort_values("time")
        .reset_index(drop=True)
    )

    print(
        f"  {symbol}: ФИНАЛЬНО "
        f"{len(df)} свечей "
        f"({df['time'].iloc[0]} -> {df['time'].iloc[-1]})"
    )

    return df


def load_ohlcv(asset: dict, tf_key: str,
               start: str = None, end: str = None) -> pd.DataFrame:

    limit = 3000

    return load_bybit(
        asset["symbol"],
        asset[tf_key],
        limit,
        start,
        end
    )

# ══════════════════════════════════════════════════════════════
#  H1 TREND — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def build_h1_lookup(h1: pd.DataFrame) -> pd.DataFrame:
    return h1[["time", "trend"]].sort_values("time").reset_index(drop=True)


def get_h1_trend_series(m15_times: pd.Series, h1_lookup: pd.DataFrame) -> pd.Series:
    m15_df = pd.DataFrame({"time": m15_times})
    merged = pd.merge_asof(
        m15_df.sort_values("time"), h1_lookup,
        on="time", direction="backward",
    )
    merged = merged.set_index(m15_df.sort_values("time").index).reindex(m15_df.index)
    return merged["trend"].fillna("UNKNOWN")


# ══════════════════════════════════════════════════════════════
#  INDICATORS — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema20"]      = ta.trend.ema_indicator(df["close"], window=20)
    df["ema50"]      = ta.trend.ema_indicator(df["close"], window=50)
    df["rsi"]        = ta.momentum.rsi(df["close"], window=14)
    df["atr"]        = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
    df["adx"]        = ta.trend.adx(df["high"], df["low"], df["close"], window=14)
    df["avg_volume"] = df["volume"].rolling(20).mean()
    df["candle_dir"] = (df["close"] > df["open"]).astype(int)
    return df.dropna().reset_index(drop=True)


def in_session(ts: pd.Timestamp) -> bool:
    return SESSION_START_UTC <= ts.hour < SESSION_END_UTC


# ══════════════════════════════════════════════════════════════
#  SIGNAL ANALYZER — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def analyze(df: pd.DataFrame, i: int, h1_trend: str):
    row = df.iloc[i]
    ema20, ema50          = row["ema20"],      row["ema50"]
    rsi, atr, adx         = row["rsi"],        row["atr"],  row["adx"]
    volume, avg_vol, cdir = row["volume"], row["avg_volume"], row["candle_dir"]

    if atr <= 0 or abs(ema20 - ema50) < atr * 0.3 or adx < ADX_MIN:
        return "NO TRADE", 0, atr

    ls = ss = 0
    if ema20 > ema50:          ls += 50
    else:                      ss += 50
    if rsi > RSI_LONG_MIN:     ls += 20
    elif rsi < RSI_SHORT_MAX:  ss += 20
    if volume > avg_vol:
        if cdir == 1:          ls += 15
        else:                  ss += 15
    bonus = min(int((adx - ADX_MIN) / 5), 3) * 5
    if ema20 > ema50:          ls += bonus
    else:                      ss += bonus
    if h1_trend == "BULL":     ss  = 0
    elif h1_trend == "BEAR":   ls  = 0

    if ls > ss and ls >= CONFIDENCE_MIN:
        if not ALLOW_BUY:
            return "NO TRADE", 0, atr
        return "BUY", ls, atr
    if ss > ls and ss >= CONFIDENCE_MIN:
        return "SELL", ss, atr
    return "NO TRADE", 0, atr


# ══════════════════════════════════════════════════════════════
#  PREPARE ASSET — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def prepare_asset(asset: dict, start: str = None, end: str = None):
    symbol = asset["symbol"]
    df = load_ohlcv(asset, "tf_m15", start, end)
    if df.empty or len(df) < 100:
        print(f"  WARNING {symbol}: мало данных ({len(df)} < 100)")
        return None, None
    df = add_indicators(df)
    if len(df) < 55:
        print(f"  WARNING {symbol}: мало свечей после индикаторов")
        return None, None
    h1 = load_ohlcv(asset, "tf_h1", start, end)
    if h1.empty or len(h1) < 20:
        print(f"  WARNING {symbol}: нет H1 данных")
        return None, None
    h1 = add_indicators(h1)
    h1["trend"] = h1.apply(
        lambda r: "BULL" if r["ema20"] > r["ema50"] else "BEAR", axis=1
    )
    return df, build_h1_lookup(h1)


# ══════════════════════════════════════════════════════════════
#  TRADE SIMULATOR — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def simulate_trade(signal, entry, atr, future_prices, pos_size):
    sl_d, tp_d = atr, atr * REWARD_RATIO
    if signal == "BUY":
        sl, tp, trail = entry - sl_d, entry + tp_d, entry - sl_d
        for p in future_prices:
            if p >= entry + TRAIL_ACTIVATE * atr:
                trail = max(trail, p - TRAIL_STEP * atr)
            if p >= tp:
                return (tp - entry) * pos_size * (1 - COMMISSION), "TP"
            if p <= max(sl, trail):
                return (max(sl, trail) - entry) * pos_size * (1 - COMMISSION), "SL/Trail"
        return (future_prices.iloc[-1] - entry) * pos_size * (1 - COMMISSION), "Timeout"
    else:
        sl, tp, trail = entry + sl_d, entry - tp_d, entry + sl_d
        for p in future_prices:
            if p <= entry - TRAIL_ACTIVATE * atr:
                trail = min(trail, p + TRAIL_STEP * atr)
            if p <= tp:
                return (entry - tp) * pos_size * (1 - COMMISSION), "TP"
            if p >= min(sl, trail):
                return (entry - min(sl, trail)) * pos_size * (1 - COMMISSION), "SL/Trail"
        return (entry - future_prices.iloc[-1]) * pos_size * (1 - COMMISSION), "Timeout"


# ══════════════════════════════════════════════════════════════
#  STATS — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

class Stats:
    def __init__(self):
        self.balance     = STARTING_BALANCE
        self.total       = self.wins = self.losses = self.timeouts = 0
        self.equity      = []
        self.win_pnls    = []
        self.loss_pnls   = []
        self.trade_log   = []
        self._peak       = STARTING_BALANCE
        self._max_dd     = 0.0
        self._dd_alerted = False

    def record(self, asset, ts, signal, entry, pnl, reason, confidence, risk_used):
        self.balance += pnl
        self.total   += 1
        self.equity.append(self.balance)
        if self.balance > self._peak:
            self._peak = self.balance
        dd_now = (self._peak - self.balance) / self._peak * 100
        if dd_now > self._max_dd:
            self._max_dd = dd_now
        if pnl > 0:
            self.wins += 1; self.win_pnls.append(pnl)
        else:
            self.losses += 1; self.loss_pnls.append(pnl)
        if reason == "Timeout":
            self.timeouts += 1
        self.trade_log.append({
            "asset": asset, "time": ts, "signal": signal,
            "entry": round(entry, 6), "pnl": round(pnl, 4),
            "reason": reason, "confidence": confidence,
            "risk_used": round(risk_used, 2), "balance": round(self.balance, 2),
        })
        if self._max_dd >= DD_ALERT_THRESHOLD and not self._dd_alerted:
            tg_send(f"ПРОСАДКА {self._max_dd:.1f}% | Баланс: ${self.balance:.2f}")
            self._dd_alerted = True
        elif self._max_dd < DD_ALERT_THRESHOLD * 0.7:
            self._dd_alerted = False

    def max_drawdown(self):   return self._max_dd
    def profit_factor(self):
        gp = sum(self.win_pnls); gl = abs(sum(self.loss_pnls))
        return gp / gl if gl > 0 else float("inf")
    def avg_win(self):  return sum(self.win_pnls)  / len(self.win_pnls)  if self.win_pnls  else 0
    def avg_loss(self): return sum(self.loss_pnls) / len(self.loss_pnls) if self.loss_pnls else 0
    def winrate(self):  return self.wins / self.total * 100 if self.total else 0
    def expectancy(self):
        wr = self.winrate() / 100
        return wr * self.avg_win() + (1 - wr) * self.avg_loss()
    def asset_breakdown(self):
        bd = {}
        for t in self.trade_log:
            a = t["asset"]
            if a not in bd: bd[a] = {"trades": 0, "wins": 0, "pnl": 0.0}
            bd[a]["trades"] += 1; bd[a]["pnl"] += t["pnl"]
            if t["pnl"] > 0: bd[a]["wins"] += 1
        return bd


# ══════════════════════════════════════════════════════════════
#  PAPER TRADING
# ══════════════════════════════════════════════════════════════

def load_account() -> dict:
    if os.path.exists(PAPER_ACCOUNT_FILE):
        try:
            with open(PAPER_ACCOUNT_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "balance": STARTING_BALANCE, "total_pnl": 0.0,
        "trades": 0, "wins": 0, "losses": 0,
        "positions": {}, "trade_log": [],
    }


def save_account(acc: dict):
    with open(PAPER_ACCOUNT_FILE, "w") as f:
        json.dump(acc, f, indent=2, default=str)


def get_current_price(symbol: str) -> float:
    resp = session.get_tickers(category="linear", symbol=symbol)
    return float(resp["result"]["list"][0]["lastPrice"])


def check_paper_positions(acc: dict) -> dict:
    for symbol, pos in list(acc["positions"].items()):
        try:
            price         = get_current_price(symbol)
            entry, sl, tp = pos["entry"], pos["sl"], pos["tp"]
            qty, signal   = pos["qty"], pos["signal"]

            reason = None
            if signal == "BUY":
                if price >= tp:   reason = "TP"
                elif price <= sl: reason = "SL"
            else:
                if price <= tp:   reason = "TP"
                elif price >= sl: reason = "SL"

            if reason:
                exit_px = tp if reason == "TP" else sl
                pnl = ((exit_px - entry) if signal == "BUY" else (entry - exit_px)) * qty * (1 - COMMISSION)
                acc["balance"]   += pnl
                acc["total_pnl"] += pnl
                acc["trades"]    += 1
                if pnl > 0: acc["wins"]   += 1
                else:       acc["losses"] += 1
                acc["trade_log"].append({
                    "symbol": symbol, "signal": signal,
                    "entry": round(entry, 6), "exit": round(exit_px, 6),
                    "pnl": round(pnl, 2), "reason": reason,
                    "time": datetime.now(timezone.utc).isoformat(),
                })
                del acc["positions"][symbol]
                wr  = acc["wins"] / acc["trades"] * 100 if acc["trades"] else 0
                pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100
                print(f"  {'OK' if pnl>0 else 'FAIL'} ЗАКРЫТА {symbol}: {reason}  "
                      f"PnL={'+'if pnl>=0 else ''}${pnl:.2f}  Баланс=${acc['balance']:.2f}")
                tg_send(
                    f"{'OK' if pnl>0 else 'FAIL'} ДЕМО ЗАКРЫТА {symbol}\n"
                    f"Причина : {reason}\n"
                    f"Вход    : {entry:.6g}\n"
                    f"Выход   : {exit_px:.6g}\n"
                    f"PnL     : {'+'if pnl>=0 else ''}${pnl:.2f}\n"
                    f"Баланс  : ${acc['balance']:.2f}  ({pct:+.1f}%)\n"
                    f"Сделок  : {acc['trades']}  WR={wr:.0f}%\n"
                    f"Итого   : {'+'if acc['total_pnl']>=0 else ''}${acc['total_pnl']:.2f}"
                )
        except Exception as e:
            print(f"  WARNING {symbol}: {e}")
    return acc


def open_paper_position(acc, symbol, signal, entry, sl, tp, atr, conf, h1_trend):
    if len(acc["positions"]) >= MAX_OPEN_POSITIONS or symbol in acc["positions"]:
        return acc
    risk    = min(acc["balance"] * (RISK_PERCENT / 100), MAX_RISK_PER_TRADE)
    qty     = risk / atr
    pot_win = risk * REWARD_RATIO * (1 - COMMISSION)
    pot_los = -risk * (1 - COMMISSION)
    pct     = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100
    acc["positions"][symbol] = {
        "signal": signal, "entry": entry, "sl": sl, "tp": tp,
        "qty": qty, "risk": risk,
        "open_time": datetime.now(timezone.utc).isoformat(),
    }
    side = "LONG" if signal == "BUY" else "SHORT"
    print(f"  [{side}] {symbol} @ {entry:.6g}  SL={sl:.6g}  TP={tp:.6g}")
    tg_send(
        f"{side} ДЕМО ОТКРЫТА {symbol}\n"
        f"H1 тренд    : {h1_trend}\n"
        f"Уверенность : {conf}/100\n"
        f"Вход  : {entry:.6g}\n"
        f"SL    : {sl:.6g}\n"
        f"TP    : {tp:.6g}\n"
        f"Риск  : ${risk:.2f}   Win: +${pot_win:.2f}   Loss: ${pot_los:.2f}\n"
        f"Баланс: ${acc['balance']:.2f}  ({pct:+.1f}%)\n"
        f"Открытых: {len(acc['positions'])}/{MAX_OPEN_POSITIONS}"
    )
    return acc


def run_paper():
    print("PAPER TRADING -- BYBIT DEMO ACCOUNT")
    acc = load_account()
    pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100
    tg_send(
        f"PAPER DEMO запущен\n"
        f"Баланс    : ${acc['balance']:.2f}  ({pct:+.1f}%)\n"
        f"Сделок    : {acc['trades']}\n"
        f"Итого PnL : {'+'if acc['total_pnl']>=0 else ''}${acc['total_pnl']:.2f}\n"
        f"Позиций   : {len(acc['positions'])}/{MAX_OPEN_POSITIONS}\n"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    scan_count = 0
    while True:
        scan_count += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        wr  = acc["wins"] / acc["trades"] * 100 if acc["trades"] else 0
        pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100

        print(f"\n{'='*64}")
        print(f"  SCAN #{scan_count} -- {now}")
        print(f"  ${acc['balance']:.2f} ({pct:+.1f}%)  |  "
              f"Positions: {len(acc['positions'])}/{MAX_OPEN_POSITIONS}  |  "
              f"Trades: {acc['trades']}  WR={wr:.0f}%")
        print(f"{'='*64}")

        acc = check_paper_positions(acc)
        save_account(acc)

        for asset in ASSETS:
            symbol = asset["symbol"]
            if symbol in acc["positions"]:
                print(f"  {symbol}: позиция открыта")
                continue
            if len(acc["positions"]) >= MAX_OPEN_POSITIONS:
                print(f"  Лимит {MAX_OPEN_POSITIONS} позиций")
                break

            print(f"\n  Scanning {symbol}...")
            df, h1_lookup = prepare_asset(asset)
            if df is None:
                continue

            i        = len(df) - 2
            ts       = df["time"].iloc[i]
            h1_trend = get_h1_trend_series(pd.Series([ts]), h1_lookup).iloc[0]

            if not in_session(ts) or h1_trend == "UNKNOWN":
                print(f"  {symbol}: вне сессии или H1 неизвестен")
                continue

            signal, conf, atr = analyze(df, i, h1_trend)
            if signal == "NO TRADE":
                print(f"  {symbol}: нет сигнала (H1={h1_trend})")
                continue

            entry = df["close"].iloc[i]
            sl    = entry - atr if signal == "BUY" else entry + atr
            tp    = entry + atr * REWARD_RATIO if signal == "BUY" else entry - atr * REWARD_RATIO

            acc = open_paper_position(acc, symbol, signal, entry, sl, tp, atr, conf, h1_trend)
            save_account(acc)

        if scan_count % 10 == 0 and acc["trades"] > 0:
            wr  = acc["wins"] / acc["trades"] * 100
            pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100
            tg_send(
                f"PAPER ОТЧЁТ -- скан #{scan_count}\n"
                f"Баланс   : ${acc['balance']:.2f}  ({pct:+.1f}%)\n"
                f"Итог PnL : {'+'if acc['total_pnl']>=0 else ''}${acc['total_pnl']:.2f}\n"
                f"Сделок   : {acc['trades']}   WR={wr:.1f}%\n"
                f"Открытых : {len(acc['positions'])}/{MAX_OPEN_POSITIONS}\n"
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            )

        print(f"\n  Следующий скан через {SCAN_INTERVAL_MIN} мин...")
        time.sleep(SCAN_INTERVAL_MIN * 60)


# ══════════════════════════════════════════════════════════════
#  LIVE TRADING — BYBIT USDT PERPETUAL
# ══════════════════════════════════════════════════════════════

def get_instrument_info(symbol: str) -> dict:
    resp = session.get_instruments_info(category="linear", symbol=symbol)
    info = resp["result"]["list"][0]
    lot  = info["lotSizeFilter"]
    price_f = info["priceFilter"]
    return {
        "min_qty":   float(lot.get("minOrderQty",  "0.001")),
        "step_qty":  float(lot.get("qtyStep",      "0.001")),
        "tick_size": float(price_f.get("tickSize", "0.01")),
    }


def round_qty(qty: float, step: float) -> float:
    decimals = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    return round(math.floor(qty / step) * step, decimals)


def round_price(price: float, tick: float) -> float:
    decimals = len(str(tick).rstrip("0").split(".")[-1]) if "." in str(tick) else 0
    return round(round(price / tick) * tick, decimals)


def set_leverage(symbol: str):
    try:
        session.set_leverage(
            category     = "linear",
            symbol       = symbol,
            buyLeverage  = str(LEVERAGE),
            sellLeverage = str(LEVERAGE),
        )
    except Exception as e:
        print(f"  WARNING плечо {symbol}: {e}")


def place_live_order(symbol: str, signal: str, entry: float,
                     atr: float, balance: float) -> bool:
    try:
        f    = get_instrument_info(symbol)
        risk = min(balance * (RISK_PERCENT / 100), MAX_RISK_PER_TRADE)
        qty  = round_qty(risk / atr, f["step_qty"])

        if qty < f["min_qty"]:
            print(f"  WARNING {symbol}: qty {qty} < minQty {f['min_qty']}")
            return False

        set_leverage(symbol)

        side = "Buy" if signal == "BUY" else "Sell"
        sl   = round_price(entry - atr if signal == "BUY" else entry + atr,         f["tick_size"])
        tp   = round_price(entry + atr * REWARD_RATIO if signal == "BUY"
                           else entry - atr * REWARD_RATIO,                          f["tick_size"])

        resp = session.place_order(
            category     = "linear",
            symbol       = symbol,
            side         = side,
            orderType    = "Market",
            qty          = str(qty),
            stopLoss     = str(sl),
            takeProfit   = str(tp),
            timeInForce  = "IOC",
        )

        order_id = resp["result"].get("orderId", "?")
        dir_label = "LONG" if signal == "BUY" else "SHORT"
        print(f"  OK {symbol} {dir_label} {qty} @ ~{entry:.6g}  SL={sl}  TP={tp}  id={order_id}")
        tg_send(
            f"{dir_label} ОРДЕР {symbol}\n"
            f"Цена  : ~{entry:.6g}\n"
            f"SL    : {sl}\n"
            f"TP    : {tp}\n"
            f"Кол-во: {qty}\n"
            f"Плечо : {LEVERAGE}x\n"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        return True

    except Exception as e:
        print(f"  FAIL {symbol}: {e}")
        tg_send(f"FAIL ордер {symbol}: {e}")
        return False


def get_open_symbols() -> set:
    try:
        resp = session.get_positions(category="linear", settleCoin="USDT")
        return {p["symbol"] for p in resp["result"]["list"] if float(p["size"]) != 0}
    except Exception:
        return set()


def get_usdt_balance() -> float:
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        return float(resp["result"]["list"][0]["coin"][0]["walletBalance"])
    except Exception:
        return STARTING_BALANCE


def run_live():
    print("LIVE BYBIT FUTURES TRADING")
    tg_startup()

    usdt_balance = get_usdt_balance()
    print(f"  USDT баланс: {usdt_balance:.2f}")
    tg_send(f"Bybit live запущен\nUSDT: {usdt_balance:.2f}\nПлечо: {LEVERAGE}x")

    scan_count = 0
    while True:
        scan_count += 1
        print(f"\n{'='*64}")
        print(f"  LIVE SCAN #{scan_count} -- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*64}")

        open_symbols = get_open_symbols()
        usdt_balance = get_usdt_balance()
        print(f"  Открытых позиций: {len(open_symbols)}  USDT: {usdt_balance:.2f}")

        for asset in ASSETS:
            if not asset.get("live", False):
                continue
            symbol = asset["symbol"]
            if symbol in open_symbols:
                print(f"  {symbol}: позиция открыта")
                continue
            if len(open_symbols) >= MAX_OPEN_POSITIONS:
                print(f"  Лимит {MAX_OPEN_POSITIONS} позиций")
                break

            print(f"\n  Scanning {symbol}...")
            df, h1_lookup = prepare_asset(asset)
            if df is None:
                continue

            i        = len(df) - 2
            ts       = df["time"].iloc[i]
            h1_trend = get_h1_trend_series(pd.Series([ts]), h1_lookup).iloc[0]

            if not in_session(ts) or h1_trend == "UNKNOWN":
                continue

            signal, conf, atr = analyze(df, i, h1_trend)
            if signal == "NO TRADE":
                print(f"  {symbol}: нет сигнала (H1={h1_trend})")
                continue

            entry = df["close"].iloc[i]
            if place_live_order(symbol, signal, entry, atr, usdt_balance):
                open_symbols.add(symbol)

        print(f"\n  Следующий скан через {SCAN_INTERVAL_MIN} мин...")
        time.sleep(SCAN_INTERVAL_MIN * 60)


# ══════════════════════════════════════════════════════════════
#  BACKTEST — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def run_backtest():
    s = BACKTEST_START or "начало данных"
    e = BACKTEST_END   or "сегодня"
    print(f"BACKTEST: {s} -> {e}")
    tg_startup()
    stats = Stats()

    for asset in ASSETS:
        symbol = asset["symbol"]
        print(f"\n  Loading {symbol}  [{s} -> {e}]")
        df, h1_lookup = prepare_asset(asset, BACKTEST_START, BACKTEST_END)
        if df is None:
            continue

        h1_trends     = get_h1_trend_series(df["time"], h1_lookup)
        trades_before = stats.total
        cooldown      = 0

        for i in range(50, len(df) - MAX_CANDLES_IN_TRADE - 1):
            if cooldown > 0:
                cooldown -= 1; continue
            if not in_session(df["time"].iloc[i]):
                continue
            h1t = h1_trends.iloc[i]
            if h1t == "UNKNOWN":
                continue
            signal, conf, atr = analyze(df, i, h1t)
            if signal == "NO TRADE":
                continue
            entry    = df["close"].iloc[i]
            future   = df["close"].iloc[i + 1: i + MAX_CANDLES_IN_TRADE + 1]
            risk     = min(stats.balance * (RISK_PERCENT / 100), MAX_RISK_PER_TRADE)
            pos_size = risk / atr
            pnl, reason = simulate_trade(signal, entry, atr, future, pos_size)
            stats.record(symbol, df["time"].iloc[i], signal, entry,
                         pnl, reason, conf, risk)
            cooldown = COOLDOWN_CANDLES

        print(f"  {symbol} done -- новых: {stats.total - trades_before}  (всего: {stats.total})")

    if not stats.trade_log:
        print("\n  Нет сделок.")
        tg_send("Бэктест: нет сделок.")
        return

    profit  = stats.balance - STARTING_BALANCE
    pct     = profit / STARTING_BALANCE * 100
    rr      = abs(stats.avg_win() / stats.avg_loss()) if stats.avg_loss() != 0 else 0
    dd      = stats.max_drawdown()
    pf      = stats.profit_factor()
    bd      = stats.asset_breakdown()
    p_start = stats.trade_log[0]["time"]
    p_end   = stats.trade_log[-1]["time"]
    exit_r  = {}
    for t in stats.trade_log:
        exit_r[t["reason"]] = exit_r.get(t["reason"], 0) + 1

    print(f"""
RESULTS
=======
Period       : {p_start} -> {p_end}
Starting     : ${STARTING_BALANCE:.2f}
Final        : ${stats.balance:.2f}
Total Profit : ${profit:+.2f}   ({pct:+.1f}%)

Total Trades : {stats.total}
Wins         : {stats.wins}
Losses       : {stats.losses}
Win Rate     : {stats.winrate():.1f}%

Profit Factor: {pf:.2f}
Expectancy   : ${stats.expectancy():.2f}
Avg Win      : ${stats.avg_win():.2f}
Avg Loss     : ${stats.avg_loss():.2f}
RR Ratio     : {rr:.2f}
Max Drawdown : {dd:.2f}%
""")

    for r, c in sorted(exit_r.items(), key=lambda x: -x[1]):
        print(f"  {r:<12}: {c:>4}  ({c/stats.total*100:.1f}%)")

    print("\nASSET BREAKDOWN:")
    for sym, d in sorted(bd.items(), key=lambda x: -x[1]["pnl"]):
        wr = d["wins"] / d["trades"] * 100 if d["trades"] else 0
        print(f"  {sym:<12}: {d['trades']:>3} trades  WR={wr:.0f}%  PnL=${d['pnl']:>+.2f}")

    pd.DataFrame(stats.trade_log).to_csv("trade_log.csv", index=False)
    print(f"\nTrade log -> trade_log.csv")
    print("=" * 64)

    tg_backtest_report(stats.balance, profit, pct, stats.total,
                       stats.winrate(), pf, rr, dd, stats.expectancy(),
                       p_start, p_end, bd)


# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if MODE == "backtest":
        run_backtest()
    elif MODE == "paper":
        run_paper()
    elif MODE == "live":
        run_live()
    else:
        print(f'Неизвестный MODE="{MODE}". Используй: backtest / paper / live')