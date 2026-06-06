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
import threading
import ta

load_dotenv()

# ══════════════════════════════════════════════════════════════
#  ⚙️  ГЛАВНЫЕ НАСТРОЙКИ — ИДЕНТИЧНО СТАРОМУ ПРИБЫЛЬНОМУ КОДУ
# ══════════════════════════════════════════════════════════════

MODE = os.getenv("MODE", "paper")
# "backtest" | "paper" | "live"

# ── Период бэктеста ──────────────────────────────────────────
BACKTEST_START = "2022-01-01"
BACKTEST_END   = "2026-05-01"

# ── Баланс и риск ────────────────────────────────────────────
STARTING_BALANCE   = 400.0

# Риск на сделку — всегда % от текущего баланса (растёт и падает вместе с ним)
# При $400  → 1.5% = $6.0  на сделку
# При $1000 → 1.5% = $15.0 на сделку
# При $5000 → 1.5% = $75.0 на сделку
RISK_PERCENT       = 1.5    # % от текущего баланса на одну сделку
MAX_RISK_PERCENT   = 5.0    # жёсткий потолок — не более 5% баланса на сделку
MAX_RISK_USD       = 50.0   # абсолютный потолок в $ — никогда не больше (защита от компаунд-взрыва)
                             # (защита от аномальных ATR)
MAX_OPEN_POSITIONS = 5      # не более 5 позиций одновременно
LEVERAGE           = 5

# ── Стратегия — ВСЕ ПАРАМЕТРЫ КАК В СТАРОМ ПРИБЫЛЬНОМ КОДЕ ──
COMMISSION           = 0.00055  # 0.055% — реальный тейкер Bybit
REWARD_RATIO         = 3.0
TRAIL_ACTIVATE       = 1.2
TRAIL_STEP           = 0.4
CONFIDENCE_MIN       = 65
ADX_MIN              = 28
ALLOW_BUY            = True
ALLOW_SELL           = True
RSI_LONG_MIN         = 52
RSI_LONG_MAX         = 72    # не покупать в перекупленности
RSI_SHORT_MAX        = 48
RSI_SHORT_MIN        = 28    # не продавать в перепроданности
MAX_CANDLES_IN_TRADE = 16
# Умный cooldown — зависит от причины закрытия:
#   TP      → очень короткий (тренд работал — почти сразу можно войти снова)
#   Trail   → короткий      (тренд был, зафиксировали прибыль)
#   SL      → средний       (рынок шёл против — нужна пауза)
#   Timeout → длинный       (позиция застряла — рынок боковой)
COOLDOWN_TP_CANDLES      = 1   # TP:      1 свеча   = 15 мин
COOLDOWN_TRAIL_CANDLES   = 2   # Trail:   2 свечи   = 30 мин
COOLDOWN_LOSS_CANDLES    = 8   # SL:      8 свечей  = 2 часа
COOLDOWN_TIMEOUT_CANDLES = 12  # Timeout: 12 свечей = 3 часа (рынок флэт)
SESSION_START_UTC    = 0
SESSION_END_UTC      = 24

# ── Уведомления ──────────────────────────────────────────────
DD_ALERT_THRESHOLD  = 10.0
SCAN_INTERVAL_MIN   = 15   # минут — поиск сигналов (синхронно со свечой M15)
TRAIL_INTERVAL_SEC  = 60   # секунд — обновление трейлинга

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
    {"symbol": "RENDERUSDT", "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},  # был RNDRUSDT — переименован на Bybit
    {"symbol": "TIAUSDT",    "tf_m15": TF_M15, "tf_h1": TF_H1, "live": True},
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
#  ДИАГНОСТИКА СТАРТА
# ══════════════════════════════════════════════════════════════

def validate_symbols():
    """Проверяет, какие символы реально торгуются на Bybit linear."""
    print("\n  Проверка символов на Bybit...")
    try:
        resp = session.get_instruments_info(category="linear")
        available = {i["symbol"] for i in resp["result"]["list"] if i.get("status") == "Trading"}
    except Exception as e:
        print(f"  WARNING: не удалось получить список инструментов: {e}")
        return

    ok, bad = [], []
    for a in ASSETS:
        if a["symbol"] in available:
            ok.append(a["symbol"])
        else:
            bad.append(a["symbol"])

    print(f"  OK  ({len(ok)}): {', '.join(ok)}")
    if bad:
        print(f"  BAD ({len(bad)}): {', '.join(bad)}  ← не найдены на Bybit, пропускаются!")
    print()


def validate_telegram():
    """Проверяет токен и chat_id Telegram."""
    if not TG_TOKEN or not TG_CHAT_ID:
        print("  WARNING: TG_TOKEN или TG_CHAT_ID не заданы в .env — уведомления отключены")
        return
    try:
        r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getMe", timeout=5)
        if r.ok:
            bot_name = r.json().get("result", {}).get("username", "?")
            print(f"  Telegram OK: @{bot_name}")
        else:
            print(f"  WARNING Telegram getMe: {r.text}  ← проверь TG_TOKEN в .env")
    except Exception as e:
        print(f"  WARNING Telegram недоступен: {e}")


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
    icons  = {"backtest": "🔬", "paper": "📡", "live": "⚡"}
    titles = {"backtest": "BACKTEST", "paper": "PAPER DEMO", "live": "LIVE TRADING"}
    icon   = icons.get(MODE, "🤖")
    title  = titles.get(MODE, MODE)
    period = ""
    if MODE == "backtest":
        s = BACKTEST_START or "начало данных"
        e = BACKTEST_END   or "сегодня"
        period = f"📅 Период  : <code>{s}</code> → <code>{e}</code>\n"
    assets_str = " · ".join(a["symbol"].replace("USDT","") for a in ASSETS)
    tg_send(
        f"{icon} <b>{title} ЗАПУЩЕН</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс  : <b>${STARTING_BALANCE:.2f}</b>\n"
        f"⚡ Плечо   : {LEVERAGE}x\n"
        f"{period}"
        f"🎯 Риск    : {RISK_PERCENT}% / макс ${MAX_RISK_USD}\n"
        f"📊 Активов : {len(ASSETS)}\n"
        f"<code>{assets_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


def tg_backtest_report(balance, profit, pct, total, winrate,
                       pf, rr, dd, expectancy, p_start, p_end, breakdown):
    lines = ""
    for sym, d in sorted(breakdown.items(), key=lambda x: -x[1]["pnl"])[:8]:
        wr    = d["wins"] / d["trades"] * 100 if d["trades"] else 0
        arrow = "📈" if d["pnl"] >= 0 else "📉"
        sign  = "+" if d["pnl"] >= 0 else ""
        name  = sym.replace("USDT","")
        lines += f"  {arrow} <code>{name:<8}</code> {d['trades']}tr  WR={wr:.0f}%  <b>${sign}{d['pnl']:.0f}</b>\n"
    pf_icon  = "✅" if pf  >= 1.5 else "⚠️"
    rr_icon  = "✅" if rr  >= 2.0 else "⚠️"
    dd_icon  = "✅" if dd  < 15   else "🔴"
    wr_icon  = "✅" if winrate > 40 else "⚠️"
    pnl_icon = "🚀" if pct > 20 else ("✅" if pct > 0 else "🔴")
    tg_send(
        f"🔬 <b>BACKTEST ЗАВЕРШЁН</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {p_start.strftime('%d.%m.%Y')} → {p_end.strftime('%d.%m.%Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Старт   : <code>${STARTING_BALANCE:.2f}</code>\n"
        f"💰 Финал   : <code>${balance:.2f}</code>\n"
        f"{pnl_icon} Прибыль : <b>${profit:+.2f}</b>  (<b>{pct:+.1f}%</b>)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 Сделок  : {total}  {wr_icon} WR=<b>{winrate:.1f}%</b>\n"
        f"💡 Expect  : <b>${expectancy:.2f}</b> / сделка\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{pf_icon} PF=<b>{pf:.2f}</b>   "
        f"{rr_icon} RR=<b>{rr:.2f}</b>   "
        f"{dd_icon} DD=<b>{dd:.1f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Топ активов:</b>\n{lines}"
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
            time.sleep(0.5)

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

            time.sleep(0.3)

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

    limit = 500

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


def calc_risk(balance: float) -> float:
    """
    Динамический риск — % от текущего баланса.

    Логика двойной защиты:
      1. Основной риск: RISK_PERCENT % от баланса
         При балансе $400  → $6    (1.5%)
         При балансе $1000 → $15   (1.5%)
         При балансе $5000 → $75   (1.5%)

      2. Drawdown-редукция: если баланс упал от пика — режем риск
         DD < 5%  → 100% риска (норма)
         DD 5-8%  → 80%  риска
         DD 8-12% → 60%  риска
         DD > 12% → 40%  риска (минимальный режим)

      3. Потолок по %: не более MAX_RISK_PERCENT % баланса на сделку

      4. Абсолютный потолок: не более MAX_RISK_USD $
         Главная защита от компаунд-взрыва — при любом балансе
         риск на сделку никогда не превысит фиксированную сумму
         При $400   → min($6,   $50) = $6
         При $5000  → min($75,  $50) = $50   ← потолок включается
         При $50000 → min($750, $50) = $50   ← всегда $50 максимум
    """
    # Просадка от пика (пик = максимум между стартом и текущим балансом)
    peak = max(STARTING_BALANCE, balance)
    dd   = max(0.0, (peak - balance) / peak * 100)

    dd_mult = (
        0.4 if dd >= 12 else
        0.6 if dd >= 8  else
        0.8 if dd >= 5  else
        1.0
    )

    base_risk = balance * (RISK_PERCENT / 100) * dd_mult
    pct_cap   = balance * (MAX_RISK_PERCENT / 100)

    # Абсолютный потолок: никогда не больше MAX_RISK_USD
    # Это главная защита от компаунд-взрыва в backtest и при росте баланса
    return min(base_risk, pct_cap, MAX_RISK_USD)


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

    # ── RSI hard-фильтры: не входим в перекупленность/перепроданность ──
    if rsi > RSI_LONG_MAX:   return "NO TRADE", 0, atr  # перекуплено — нет лонга
    if rsi < RSI_SHORT_MIN:  return "NO TRADE", 0, atr  # перепродано — нет шорта

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
        if not ALLOW_SELL:
            return "NO TRADE", 0, atr
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
    sl_d = atr * 1.5              # SL = 1.5x ATR — шире шума
    tp_d = sl_d * REWARD_RATIO    # TP масштабируется от SL
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
            tg_send(
                f"🔴 <b>ПРОСАДКА ДОСТИГЛА {self._max_dd:.1f}%</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Баланс : <b>${self.balance:.2f}</b>\n"
                f"📉 Риск снижен автоматически\n"
                f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            )
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
        "balance":   STARTING_BALANCE,
        "total_pnl": 0.0,
        "trades":    0,
        "wins":      0,
        "losses":    0,
        "positions": {},
        "cooldowns": {},   # symbol -> unix timestamp до которого нельзя входить
        "trade_log": [],
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
            price = get_current_price(symbol)

            entry  = pos["entry"]
            sl     = pos["sl"]
            tp     = pos["tp"]
            atr    = pos.get("atr", abs(tp - entry) / REWARD_RATIO)
            trail  = pos.get("trail", sl)
            qty    = pos["qty"]
            signal = pos["signal"]

            # ── Обновляем трейлинг ─────────────────────────
            if signal == "BUY":
                if price >= entry + TRAIL_ACTIVATE * atr:
                    trail = max(trail, price - TRAIL_STEP * atr)
                pos["trail"] = trail
                exit_sl = max(sl, trail)
                hit_tp  = price >= tp
                hit_sl  = price <= exit_sl
            else:  # SELL / SHORT
                if price <= entry - TRAIL_ACTIVATE * atr:
                    trail = min(trail, price + TRAIL_STEP * atr)
                pos["trail"] = trail
                exit_sl = min(sl, trail)
                hit_tp  = price <= tp
                hit_sl  = price >= exit_sl

            reason = None

            if hit_tp:
                reason  = "TP"
            elif hit_sl:
                reason  = "Trail/SL" if trail != sl else "SL"

            if reason:

                exit_px = tp if reason == "TP" else exit_sl

                pnl = (
                    ((exit_px - entry) if signal == "BUY" else (entry - exit_px))
                    * qty
                    * (1 - COMMISSION)
                )

                acc["balance"] += pnl
                acc["total_pnl"] += pnl
                acc["trades"] += 1

                if pnl > 0:
                    acc["wins"] += 1
                else:
                    acc["losses"] += 1

                acc["trade_log"].append({
                    "symbol": symbol,
                    "signal": signal,
                    "entry": round(entry, 6),
                    "exit": round(exit_px, 6),
                    "pnl": round(pnl, 2),
                    "reason": reason,
                    "time": datetime.now(timezone.utc).isoformat(),
                })

                del acc["positions"][symbol]

                # Умный cooldown: TP быстро, Trail быстро, SL средне, Timeout долго
                if "cooldowns" not in acc:
                    acc["cooldowns"] = {}
                if reason == "TP":
                    cd_candles = COOLDOWN_TP_CANDLES
                elif "Trail" in reason:
                    cd_candles = COOLDOWN_TRAIL_CANDLES
                else:  # SL
                    cd_candles = COOLDOWN_LOSS_CANDLES
                acc["cooldowns"][symbol] = time.time() + cd_candles * 15 * 60

                wr = (
                    acc["wins"] / acc["trades"] * 100
                    if acc["trades"] else 0
                )

                pct = (
                    (acc["balance"] - STARTING_BALANCE)
                    / STARTING_BALANCE * 100
                )

                print(
                    f"  {'OK' if pnl > 0 else 'FAIL'} "
                    f"ЗАКРЫТА {symbol}: {reason}  "
                    f"PnL={'+' if pnl >= 0 else ''}${pnl:.2f}  "
                    f"Баланс=${acc['balance']:.2f}"
                )

                side_label = "LONG 📈" if signal == "BUY" else "SHORT 📉"
                if reason == "TP":
                    header = "✅ <b>ТЕЙК-ПРОФИТ</b>"
                elif "Trail" in reason:
                    header = "🔒 <b>ТРЕЙЛИНГ СТОП</b>"
                else:
                    header = "🛑 <b>СТОП-ЛОСС</b>"
                pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
                change   = ((exit_px - entry) / entry * 100) if signal == "BUY" else ((entry - exit_px) / entry * 100)
                tg_send(
                    f"{header} · {symbol} {side_label}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📥 Вход   : <code>{entry:.6g}</code>\n"
                    f"📤 Выход  : <code>{exit_px:.6g}</code>  ({change:+.2f}%)\n"
                    f"💵 PnL    : <b>{pnl_str}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Баланс : <b>${acc['balance']:.2f}</b>  ({pct:+.1f}%)\n"
                    f"📊 Сделок : {acc['trades']}  WR={wr:.0f}%\n"
                    f"📈 Итого  : <b>{'+' if acc['total_pnl'] >= 0 else ''}${acc['total_pnl']:.2f}</b>\n"
                    f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                )

        except Exception as e:
            print(f"  WARNING {symbol}: {e}")

    return acc


def open_paper_position(
    acc,
    symbol,
    signal,
    entry,
    sl,
    tp,
    atr,
    conf,
    h1_trend
):

    if len(acc["positions"]) >= MAX_OPEN_POSITIONS:
        return acc

    if symbol in acc["positions"]:
        return acc

    # ── Dynamic Risk ─────────────────────────────

    risk = calc_risk(acc["balance"])

    qty = risk / atr

    pot_win = risk * REWARD_RATIO * (1 - COMMISSION)
    pot_los = -risk * (1 - COMMISSION)

    pct = (
        (acc["balance"] - STARTING_BALANCE)
        / STARTING_BALANCE * 100
    )

    acc["positions"][symbol] = {
        "signal":    signal,
        "entry":     entry,
        "sl":        sl,
        "tp":        tp,
        "trail":     sl,   # трейлинг = SL при открытии
        "atr":       atr,
        "qty":       qty,
        "risk":      risk,
        "open_time": datetime.now(timezone.utc).isoformat(),
    }

    side = "LONG" if signal == "BUY" else "SHORT"

    print(
        f"  [{side}] {symbol} @ {entry:.6g}  "
        f"SL={sl:.6g}  TP={tp:.6g}"
    )

    side_emoji = "🟢" if signal == "BUY" else "🔴"
    side_label = "LONG 📈" if signal == "BUY" else "SHORT 📉"
    conf_bar   = "█" * (conf // 10) + "░" * (10 - conf // 10)
    tg_send(
        f"{side_emoji} <b>ОТКРЫТА ПОЗИЦИЯ · {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 {side_label}   H1: {h1_trend}\n"
        f"⚡ Плечо : {LEVERAGE}x\n"
        f"🎯 Уверенность: <code>{conf_bar}</code> {conf}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Вход  : <code>{entry:.6g}</code>\n"
        f"🛑 SL    : <code>{sl:.6g}</code>\n"
        f"✅ TP    : <code>{tp:.6g}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Риск  : ${risk:.2f}  |  🏆 Win: +${pot_win:.2f}  |  💀 Loss: -${abs(pot_los):.2f}\n"
        f"💰 Баланс: <b>${acc['balance']:.2f}</b>  ({pct:+.1f}%)\n"
        f"📂 Позиций: {len(acc['positions'])}/{MAX_OPEN_POSITIONS}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
    )

    return acc


def _paper_trail_loop(acc_ref: list, lock: threading.Lock):
    """
    Фоновый поток: обновляет трейлинг каждые TRAIL_INTERVAL_SEC секунд.
    acc_ref[0] — разделяемый объект аккаунта, защищён lock.
    """
    while True:
        time.sleep(TRAIL_INTERVAL_SEC)
        with lock:
            try:
                acc_ref[0] = check_paper_positions(acc_ref[0])
                save_account(acc_ref[0])
            except Exception as e:
                print(f"  [trail-thread] WARNING: {e}")


def run_paper():

    print("PAPER TRADING -- BYBIT DEMO ACCOUNT")
    print(f"  Трейлинг : каждые {TRAIL_INTERVAL_SEC} сек")
    print(f"  Сигналы  : каждые {SCAN_INTERVAL_MIN} мин")

    acc = load_account()
    pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100

    wr_str = f"{acc['wins']/acc['trades']*100:.0f}%" if acc["trades"] else "—"
    tg_send(
        f"📡 <b>PAPER DEMO ЗАПУЩЕН</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс  : <b>${acc['balance']:.2f}</b>  ({pct:+.1f}%)\n"
        f"📊 Сделок  : {acc['trades']}  WR={wr_str}\n"
        f"📈 Итог PnL: <b>{'+' if acc['total_pnl']>=0 else ''}${acc['total_pnl']:.2f}</b>\n"
        f"📂 Позиций : {len(acc['positions'])}/{MAX_OPEN_POSITIONS}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Trail  : каждые {TRAIL_INTERVAL_SEC} сек\n"
        f"🔍 Сигналы: каждые {SCAN_INTERVAL_MIN} мин\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    # Разделяемый аккаунт + мьютекс для потокобезопасности
    acc_ref = [acc]
    lock    = threading.Lock()

    # Запускаем фоновый поток трейлинга
    trail_thread = threading.Thread(
        target=_paper_trail_loop,
        args=(acc_ref, lock),
        daemon=True,
        name="paper-trail"
    )
    trail_thread.start()
    print("  [trail-thread] запущен")

    # Считаем время до следующего скана сигналов
    # Первый скан — сразу при старте
    next_signal_scan = time.time()
    scan_count = 0

    while True:

        now_ts = time.time()

        # Ждём до следующего скана сигналов (с шагом 5 сек чтобы не грузить CPU)
        if now_ts < next_signal_scan:
            time.sleep(5)
            continue

        next_signal_scan = now_ts + SCAN_INTERVAL_MIN * 60
        scan_count += 1

        with lock:
            acc = acc_ref[0]

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        wr  = acc["wins"] / acc["trades"] * 100 if acc["trades"] else 0
        pct = (acc["balance"] - STARTING_BALANCE) / STARTING_BALANCE * 100

        print(f"\n{'=' * 64}")
        print(f"  SIGNAL SCAN #{scan_count} -- {now}")
        print(
            f"  ${acc['balance']:.2f} ({pct:+.1f}%)  |  "
            f"Positions: {len(acc['positions'])}/{MAX_OPEN_POSITIONS}  |  "
            f"Trades: {acc['trades']}  WR={wr:.0f}%"
        )
        print(f"{'=' * 64}")

        # ── Поиск новых входов ────────────────────────────────
        print(f"\n  Сканирование сигналов ({len(ASSETS)} активов)...")
        signals_found = 0

        for asset in ASSETS:

            symbol = asset["symbol"]

            with lock:
                already_open = symbol in acc_ref[0]["positions"]
                positions_full = len(acc_ref[0]["positions"]) >= MAX_OPEN_POSITIONS

            if already_open:
                print(f"  {symbol}: уже открыта позиция")
                continue

            if positions_full:
                print(f"  Лимит позиций ({MAX_OPEN_POSITIONS}) достигнут")
                break

            try:
                df, h1_lookup = prepare_asset(asset)
                if df is None or df.empty:
                    continue

                h1_trends = get_h1_trend_series(df["time"], h1_lookup)
                i = len(df) - 2

                if i < 50:
                    continue

                if not in_session(df["time"].iloc[i]):
                    print(f"  {symbol}: вне торговой сессии")
                    continue

                h1t = h1_trends.iloc[i]
                if h1t == "UNKNOWN":
                    print(f"  {symbol}: H1 тренд UNKNOWN")
                    continue

                # Cooldown check
                with lock:
                    cooldowns = acc_ref[0].get("cooldowns", {})
                cd_until = cooldowns.get(symbol, 0)
                if time.time() < cd_until:
                    mins_left = int((cd_until - time.time()) / 60)
                    print(f"  {symbol}: cooldown ещё {mins_left} мин")
                    continue

                signal, conf, atr = analyze(df, i, h1t)

                print(
                    f"  {symbol}: {signal}  conf={conf}  "
                    f"ADX={df['adx'].iloc[i]:.1f}  "
                    f"RSI={df['rsi'].iloc[i]:.1f}  "
                    f"H1={h1t}"
                )

                if signal == "NO TRADE":
                    continue

                signals_found += 1
                entry = df["close"].iloc[i]

                if atr <= 0:
                    continue

                sl_dist = atr * 1.5
                if signal == "BUY":
                    sl = entry - sl_dist
                    tp = entry + sl_dist * REWARD_RATIO
                else:
                    sl = entry + sl_dist
                    tp = entry - sl_dist * REWARD_RATIO

                with lock:
                    acc_ref[0] = open_paper_position(
                        acc_ref[0], symbol, signal,
                        entry, sl, tp, atr, conf, h1t
                    )
                    save_account(acc_ref[0])

            except Exception as e:
                print(f"  WARNING {symbol}: {e}")

            # пауза между активами чтобы не бить rate limit
            time.sleep(1.0)

        with lock:
            acc = acc_ref[0]

        print(
            f"\n  Скан завершён. "
            f"Сигналов: {signals_found}  "
            f"Открыто: {len(acc['positions'])}/{MAX_OPEN_POSITIONS}"
        )
        print(f"  Следующий скан сигналов через {SCAN_INTERVAL_MIN} мин...")


# ══════════════════════════════════════════════════════════════
#  LIVE TRADING
# ══════════════════════════════════════════════════════════════

def get_instrument_info(symbol: str) -> dict:
    """Фильтры инструмента: шаг цены, лота, мин. лот."""
    try:
        resp = session.get_instruments_info(category="linear", symbol=symbol)
        if resp.get("retCode", -1) != 0 or not resp["result"]["list"]:
            return {"min_qty": 0.001, "step_qty": 0.001, "tick_size": 0.01}
        info = resp["result"]["list"][0]
        lot  = info.get("lotSizeFilter", {})
        prc  = info.get("priceFilter",   {})
        return {
            "min_qty":   float(lot.get("minOrderQty", "0.001")),
            "step_qty":  float(lot.get("qtyStep",     "0.001")),
            "tick_size": float(prc.get("tickSize",    "0.01")),
        }
    except Exception as e:
        print(f"  WARNING get_instrument_info {symbol}: {e}")
        return {"min_qty": 0.001, "step_qty": 0.001, "tick_size": 0.01}


def round_qty(qty: float, step: float) -> float:
    decimals = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
    return round(math.floor(qty / step) * step, decimals)


def round_price(price: float, tick: float) -> float:
    decimals = len(str(tick).rstrip("0").split(".")[-1]) if "." in str(tick) else 0
    return round(round(price / tick) * tick, decimals)


def set_leverage_bybit(symbol: str):
    try:
        session.set_leverage(
            category     = "linear",
            symbol       = symbol,
            buyLeverage  = str(LEVERAGE),
            sellLeverage = str(LEVERAGE),
        )
    except Exception as e:
        print(f"  WARNING set_leverage {symbol}: {e}")


def get_open_symbols() -> set:
    """Символы с открытыми позициями на Bybit."""
    try:
        resp = session.get_positions(category="linear", settleCoin="USDT")
        if resp.get("retCode", -1) != 0:
            return set()
        return {
            p["symbol"]
            for p in resp["result"]["list"]
            if float(p.get("size", 0)) != 0
        }
    except Exception as e:
        print(f"  WARNING get_positions: {e}")
        return set()


def get_usdt_balance() -> float:
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        if resp.get("retCode", -1) != 0:
            return 0.0
        for c in resp["result"]["list"][0].get("coin", []):
            if c["coin"] == "USDT":
                return float(c.get("walletBalance", 0))
    except Exception as e:
        print(f"  WARNING get_wallet_balance: {e}")
    return 0.0


def place_live_order(symbol: str, signal: str, entry: float,
                     atr: float, balance: float) -> bool:
    """
    Открытие позиции через Bybit V5 Unified Trading.
    SL и TP передаются прямо в ордер — надёжнее conditional-ордеров.
    Trailing stop на бирже НЕ используется: трейлинг отслеживается
    локально в run_live() и обновляется через amend_order / cancel + replace.
    """
    try:
        f    = get_instrument_info(symbol)
        risk = calc_risk(balance)
        qty  = round_qty(risk / atr, f["step_qty"])

        if qty < f["min_qty"]:
            print(f"  WARNING {symbol}: qty {qty} < minQty {f['min_qty']}")
            return False, None

        set_leverage_bybit(symbol)

        side    = "Buy" if signal == "BUY" else "Sell"
        sl_dist = atr * 1.5
        sl   = round_price(
            entry - sl_dist if signal == "BUY" else entry + sl_dist,
            f["tick_size"]
        )
        tp   = round_price(
            entry + sl_dist * REWARD_RATIO if signal == "BUY" else entry - sl_dist * REWARD_RATIO,
            f["tick_size"]
        )

        resp = session.place_order(
            category    = "linear",
            symbol      = symbol,
            side        = side,
            orderType   = "Market",
            qty         = str(qty),
            stopLoss    = str(sl),
            takeProfit  = str(tp),
            slTriggerBy = "LastPrice",
            tpTriggerBy = "LastPrice",
            positionIdx = 0,
            timeInForce = "IOC",
        )

        if resp.get("retCode", -1) != 0:
            err = resp.get("retMsg", "Unknown")
            print(f"  ERROR {symbol}: {err}")
            tg_send(f"❌ <b>ОШИБКА ОРДЕРА</b> · {symbol}\n━━━━━━━━━━━━━━━━━━━━━━━━\n{err}")
            return False, None

        order_id  = resp["result"].get("orderId", "?")
        dir_label = "LONG" if signal == "BUY" else "SHORT"
        print(f"  OK {symbol} {dir_label} qty={qty} ~{entry:.6g}  SL={sl:.6g}  TP={tp:.6g}  id={order_id}")
        side_emoji = "🟢" if signal == "BUY" else "🔴"
        side_label2 = "LONG 📈" if signal == "BUY" else "SHORT 📉"
        tg_send(
            f"{side_emoji} <b>ОРДЕР ИСПОЛНЕН · {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {side_label2}   ⚡ {LEVERAGE}x\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 Цена  : <code>{entry:.6g}</code>\n"
            f"📦 Кол-во: <code>{qty}</code>\n"
            f"🛑 SL    : <code>{sl:.6g}</code>\n"
            f"✅ TP    : <code>{tp:.6g}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Риск  : ${risk:.2f}\n"
            f"🆔 ID    : <code>{order_id}</code>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        # Возвращаем данные позиции для трейлинга
        return True, {
            "symbol":    symbol,
            "signal":    signal,
            "entry":     entry,
            "sl":        sl,
            "tp":        tp,
            "trail":     sl,
            "atr":       atr,
            "qty":       qty,
            "risk":      risk,
            "open_time": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f"  ERROR place_live_order {symbol}: {e}")
        tg_send(f"❌ <b>ИСКЛЮЧЕНИЕ</b> · {symbol}\n━━━━━━━━━━━━━━━━━━━━━━━━\n{e}")
        return False, None


def update_live_trailing(live_positions: dict) -> tuple:
    """
    Проверяет и обновляет трейлинг-стоп для открытых live-позиций.
    Обновление SL на бирже через trading_stop().
    Если позиция уже закрыта биржей (TP/SL) — убираем из словаря.
    Возвращает (live_positions, closed_symbols).
    """
    open_on_exchange = get_open_symbols()
    closed_symbols = []

    for symbol in list(live_positions.keys()):

        # Если биржа уже закрыла позицию
        if symbol not in open_on_exchange:
            pos = live_positions.pop(symbol)
            closed_symbols.append(symbol)
            signal = pos["signal"]
            entry  = pos["entry"]
            tp     = pos["tp"]
            sl     = pos["sl"]
            risk   = pos.get("risk", 0)
            qty    = pos.get("qty", 0)
            side   = "LONG 📈" if signal == "BUY" else "SHORT 📉"

            # Определяем причину закрытия по текущей цене
            try:
                last_price = get_current_price(symbol)
                tp_dist = abs(last_price - tp)
                sl_dist = abs(last_price - sl)
                hit_tp  = tp_dist < sl_dist
            except Exception:
                last_price = None
                hit_tp = False

            # Считаем PnL
            if last_price:
                raw_pnl = (
                    (last_price - entry) if signal == "BUY" else (entry - last_price)
                ) * qty
                pnl = raw_pnl * (1 - COMMISSION)
            else:
                pnl = None

            # Иконки и заголовок
            if hit_tp:
                header    = "✅ <b>ТЕЙК-ПРОФИТ</b>"
                result    = "TP"
                emoji     = "🏆"
            else:
                header    = "🛑 <b>СТОП-ЛОСС</b>"
                result    = "SL"
                emoji     = "💀"

            pnl_str = (
                f"<b>+${pnl:.2f}</b> 🟢" if pnl and pnl >= 0
                else f"<b>-${abs(pnl):.2f}</b> 🔴"
            ) if pnl is not None else "—"

            price_str = f"<code>{last_price:.6g}</code>" if last_price else "—"

            open_time = pos.get("open_time", "")
            duration  = ""
            if open_time:
                try:
                    opened = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                    mins   = int((datetime.now(timezone.utc) - opened).total_seconds() / 60)
                    h, m   = divmod(mins, 60)
                    duration = f"⏱ Время  : {h}ч {m}мин\n" if h else f"⏱ Время  : {m} мин\n"
                except Exception:
                    pass

            print(f"  [{result}] {symbol} {side}  PnL={pnl_str}")
            tg_send(
                f"{emoji} {header} · <b>{symbol}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 {side}   ⚡ {LEVERAGE}x\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 Вход  : <code>{entry:.6g}</code>\n"
                f"📤 Выход : {price_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 PnL   : {pnl_str}\n"
                f"{duration}"
                f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            )
            continue

        pos = live_positions[symbol]

        try:
            price  = get_current_price(symbol)
            entry  = pos["entry"]
            atr    = pos["atr"]
            trail  = pos["trail"]
            sl     = pos["sl"]
            signal = pos["signal"]

            new_trail = trail

            if signal == "BUY":
                if price >= entry + TRAIL_ACTIVATE * atr:
                    new_trail = max(trail, price - TRAIL_STEP * atr)
            else:
                if price <= entry - TRAIL_ACTIVATE * atr:
                    new_trail = min(trail, price + TRAIL_STEP * atr)

            # Обновляем SL на бирже только если трейлинг сдвинулся
            if new_trail != trail:
                try:
                    f         = get_instrument_info(symbol)
                    new_sl    = round_price(new_trail, f["tick_size"])
                    session.set_trading_stop(
                        category    = "linear",
                        symbol      = symbol,
                        stopLoss    = str(new_sl),
                        slTriggerBy = "LastPrice",
                        positionIdx = 0,
                    )
                    pos["trail"] = new_trail
                    pos["sl"]    = new_sl
                    side = "LONG" if signal == "BUY" else "SHORT"
                    print(f"  [TRAIL] {symbol} {side}  SL: {trail:.6g} -> {new_sl:.6g}  (price={price:.6g})")
                except Exception as e:
                    print(f"  WARNING trail update {symbol}: {e}")

        except Exception as e:
            print(f"  WARNING update_live_trailing {symbol}: {e}")

    return live_positions, closed_symbols


def _live_trail_loop(positions_ref: list, lock: threading.Lock,
                     cooldowns_ref: list):
    """
    Фоновый поток: обновляет трейлинг live-позиций каждые TRAIL_INTERVAL_SEC секунд.
    positions_ref[0] — dict {symbol: pos_data}, защищён lock.
    cooldowns_ref[0] — dict {symbol: unix_timestamp}, защищён тем же lock.
    """
    while True:
        time.sleep(TRAIL_INTERVAL_SEC)
        with lock:
            if positions_ref[0]:
                try:
                    positions_ref[0], closed = update_live_trailing(positions_ref[0])
                    for sym in closed:
                        cooldowns_ref[0][sym] = time.time() + COOLDOWN_LOSS_CANDLES * 15 * 60
                except Exception as e:
                    print(f"  [live-trail-thread] WARNING: {e}")


def run_live():
    """Live trading — Bybit USDT Perpetual. Трейлинг в фоновом потоке."""

    print("LIVE TRADING -- BYBIT")
    print(f"  Трейлинг : каждые {TRAIL_INTERVAL_SEC} сек")
    print(f"  Сигналы  : каждые {SCAN_INTERVAL_MIN} мин")
    tg_startup()

    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        print("  ERROR: API ключи не заданы в .env!")
        return

    usdt_balance = get_usdt_balance()
    if usdt_balance == 0.0:
        print("  ERROR: баланс 0. Проверь API ключи и права.")
        tg_send("❌ <b>ОШИБКА ЗАПУСКА</b>\nБаланс USDT = 0\nПроверь API ключи и права доступа")
        return

    print(f"  USDT баланс: {usdt_balance:.2f}")
    tg_send(
        f"⚡ <b>LIVE TRADING ЗАПУЩЕН</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс  : <b>${usdt_balance:.2f} USDT</b>\n"
        f"⚡ Плечо   : {LEVERAGE}x\n"
        f"🎯 Риск    : {RISK_PERCENT}% / макс ${MAX_RISK_USD}\n"
        f"📂 Позиций : макс {MAX_OPEN_POSITIONS}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Trail   : каждые {TRAIL_INTERVAL_SEC} сек\n"
        f"🔍 Сигналы : каждые {SCAN_INTERVAL_MIN} мин\n"
        f"📊 Активов : {len(ASSETS)}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    # Разделяемый словарь позиций + мьютекс
    positions_ref  = [{}]
    live_cooldowns = {}
    cooldowns_ref  = [live_cooldowns]
    lock           = threading.Lock()

    # Запускаем фоновый поток трейлинга
    trail_thread = threading.Thread(
        target=_live_trail_loop,
        args=(positions_ref, lock, cooldowns_ref),
        daemon=True,
        name="live-trail"
    )
    trail_thread.start()
    print("  [live-trail-thread] запущен")

    # Таймер сигналов — первый скан сразу
    next_signal_scan = time.time()
    scan_count = 0

    while True:

        now_ts = time.time()

        if now_ts < next_signal_scan:
            time.sleep(5)
            continue

        next_signal_scan = now_ts + SCAN_INTERVAL_MIN * 60
        scan_count += 1

        # Обновляем баланс
        usdt_balance = get_usdt_balance() or usdt_balance

        with lock:
            open_locally = set(positions_ref[0].keys())

        # Позиции на бирже
        open_symbols = get_open_symbols() | open_locally

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"\n{'=' * 64}")
        print(f"  LIVE SIGNAL SCAN #{scan_count} -- {now}")
        print(f"  USDT: ${usdt_balance:.2f}  |  Открытых: {len(open_symbols)}/{MAX_OPEN_POSITIONS}")
        print(f"{'=' * 64}")

        signals_found = 0

        for asset in ASSETS:
            if not asset.get("live", False):
                continue

            symbol = asset["symbol"]

            if symbol in open_symbols:
                print(f"  {symbol}: позиция открыта")
                continue

            if len(open_symbols) >= MAX_OPEN_POSITIONS:
                print(f"  Лимит позиций ({MAX_OPEN_POSITIONS})")
                break

            # Cooldown check
            with lock:
                cd_until = cooldowns_ref[0].get(symbol, 0)
            if time.time() < cd_until:
                mins_left = int((cd_until - time.time()) / 60)
                print(f"  {symbol}: cooldown ещё {mins_left} мин")
                continue

            try:
                df, h1_lookup = prepare_asset(asset)
                if df is None:
                    continue

                i = len(df) - 2
                if i < 50:
                    continue

                if not in_session(df["time"].iloc[i]):
                    continue

                h1_trends = get_h1_trend_series(df["time"], h1_lookup)
                h1t = h1_trends.iloc[i]

                if h1t == "UNKNOWN":
                    continue

                signal, conf, atr = analyze(df, i, h1t)

                print(
                    f"  {symbol}: {signal}  conf={conf}  "
                    f"ADX={df['adx'].iloc[i]:.1f}  "
                    f"RSI={df['rsi'].iloc[i]:.1f}  "
                    f"H1={h1t}"
                )

                if signal == "NO TRADE":
                    continue

                signals_found += 1
                entry = df["close"].iloc[i]

                ok, pos_data = place_live_order(symbol, signal, entry, atr, usdt_balance)

                if ok and pos_data:
                    open_symbols.add(symbol)
                    with lock:
                        positions_ref[0][symbol] = pos_data

            except Exception as e:
                print(f"  WARNING {symbol}: {e}")

            # пауза между активами
            time.sleep(1.0)

        print(
            f"\n  Скан завершён. "
            f"Сигналов: {signals_found}  "
            f"Открыто: {len(open_symbols)}/{MAX_OPEN_POSITIONS}"
        )
        print(f"  Следующий скан сигналов через {SCAN_INTERVAL_MIN} мин...")

        pct = (usdt_balance - STARTING_BALANCE) / STARTING_BALANCE * 100
        signal_str = f"🔔 Сигналов найдено: {signals_found}" if signals_found > 0 else "😴 Сигналов нет"
        tg_send(
            f"🔍 <b>СКАН #{scan_count}</b> — {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Баланс : <b>${usdt_balance:.2f}</b> ({pct:+.1f}%)\n"
            f"📂 Позиций: {len(open_symbols)}/{MAX_OPEN_POSITIONS}\n"
            f"{signal_str}\n"
            f"⏱ Следующий скан через {SCAN_INTERVAL_MIN} мин"
        )


# ══════════════════════════════════════════════════════════════
#  BACKTEST — БЕЗ ИЗМЕНЕНИЙ
# ══════════════════════════════════════════════════════════════

def run_backtest():

    s = BACKTEST_START or "начало данных"
    e = BACKTEST_END or "сегодня"

    print(f"BACKTEST: {s} -> {e}")

    tg_startup()

    stats = Stats()

    # =====================================================
    # LOOP ASSETS
    # =====================================================
    for asset in ASSETS:

        symbol = asset["symbol"]

        print(f"\n  Loading {symbol} [{s} -> {e}]")

        df, h1_lookup = prepare_asset(
            asset,
            BACKTEST_START,
            BACKTEST_END
        )

        if df is None:
            continue

        h1_trends = get_h1_trend_series(
            df["time"],
            h1_lookup
        )

        trades_before = stats.total
        cooldown = 0

        # =====================================================
        # MAIN LOOP
        # =====================================================
        for i in range(
            50,
            len(df) - MAX_CANDLES_IN_TRADE - 1
        ):

            # cooldown
            if cooldown > 0:
                cooldown -= 1
                continue

            # session filter
            if not in_session(df["time"].iloc[i]):
                continue

            # H1 trend
            h1t = h1_trends.iloc[i]

            if h1t == "UNKNOWN":
                continue

            # signal
            signal, conf, atr = analyze(df, i, h1t)

            if signal == "NO TRADE":
                continue

            # =====================================================
            # ENTRY
            # =====================================================
            entry = df["close"].iloc[i]

            future = df["close"].iloc[
                i + 1:
                i + MAX_CANDLES_IN_TRADE + 1
            ]

            # =====================================================
            # DYNAMIC RISK SYSTEM
            # =====================================================
            risk = calc_risk(stats.balance)

            # защита
            if atr <= 0:
                continue

            pos_size = risk / atr

            # =====================================================
            # SIMULATE TRADE
            # =====================================================
            pnl, reason = simulate_trade(
                signal,
                entry,
                atr,
                future,
                pos_size
            )

            # =====================================================
            # RECORD
            # =====================================================
            stats.record(
                symbol,
                df["time"].iloc[i],
                signal,
                entry,
                pnl,
                reason,
                conf,
                risk
            )

            # Умный cooldown: TP быстро, Trail быстро, SL средне, Timeout долго
            if reason == "TP":
                cooldown = COOLDOWN_TP_CANDLES
            elif reason == "SL/Trail":
                cooldown = COOLDOWN_TRAIL_CANDLES
            elif reason == "Timeout":
                cooldown = COOLDOWN_TIMEOUT_CANDLES
            else:  # чистый SL
                cooldown = COOLDOWN_LOSS_CANDLES

        print(
            f"  {symbol} done -- "
            f"новых: {stats.total - trades_before}  "
            f"(всего: {stats.total})"
        )

    # =====================================================
    # NO TRADES
    # =====================================================
    if not stats.trade_log:

        print("\n  Нет сделок.")
        tg_send(
            "🔬 <b>BACKTEST</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Сделок не найдено\n"
            "Попробуй изменить период или параметры"
        )

        return

    # =====================================================
    # STATS
    # =====================================================
    profit = stats.balance - STARTING_BALANCE

    pct = (
        profit / STARTING_BALANCE * 100
    )

    rr = (
        abs(stats.avg_win() / stats.avg_loss())
        if stats.avg_loss() != 0 else 0
    )

    dd = stats.max_drawdown()

    pf = stats.profit_factor()

    bd = stats.asset_breakdown()

    p_start = stats.trade_log[0]["time"]
    p_end = stats.trade_log[-1]["time"]

    # =====================================================
    # EXIT REASONS
    # =====================================================
    exit_r = {}

    for t in stats.trade_log:

        exit_r[t["reason"]] = (
            exit_r.get(t["reason"], 0) + 1
        )

    # =====================================================
    # PRINT RESULTS
    # =====================================================
    print(f"""
RESULTS
=======

Period       : {p_start} -> {p_end}

Starting     : ${STARTING_BALANCE:.2f}
Final        : ${stats.balance:.2f}

Total Profit : ${profit:+.2f}
ROI          : {pct:+.1f}%

========================================

Total Trades : {stats.total}

Wins         : {stats.wins}
Losses       : {stats.losses}

Win Rate     : {stats.winrate():.1f}%

========================================

Profit Factor: {pf:.2f}

Expectancy   : ${stats.expectancy():.2f}

Avg Win      : ${stats.avg_win():.2f}
Avg Loss     : ${stats.avg_loss():.2f}

RR Ratio     : {rr:.2f}

Max Drawdown : {dd:.2f}%

========================================
""")

    # =====================================================
    # EXIT BREAKDOWN
    # =====================================================
    for r, c in sorted(
        exit_r.items(),
        key=lambda x: -x[1]
    ):

        print(
            f"  {r:<12}: "
            f"{c:>4}  "
            f"({c / stats.total * 100:.1f}%)"
        )

    # =====================================================
    # ASSET BREAKDOWN
    # =====================================================
    print("\nASSET BREAKDOWN:")

    for sym, d in sorted(
        bd.items(),
        key=lambda x: -x[1]["pnl"]
    ):

        wr = (
            d["wins"] / d["trades"] * 100
            if d["trades"] else 0
        )

        print(
            f"  {sym:<12}: "
            f"{d['trades']:>3} trades  "
            f"WR={wr:.0f}%  "
            f"PnL=${d['pnl']:+.2f}"
        )

    # =====================================================
    # SAVE CSV
    # =====================================================
    pd.DataFrame(
        stats.trade_log
    ).to_csv(
        "trade_log.csv",
        index=False
    )

    print("\nTrade log -> trade_log.csv")

    print("=" * 64)

    # =====================================================
    # TG REPORT
    # =====================================================
    tg_backtest_report(
        stats.balance,
        profit,
        pct,
        stats.total,
        stats.winrate(),
        pf,
        rr,
        dd,
        stats.expectancy(),
        p_start,
        p_end,
        bd
    )

# ══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n  Запуск диагностики...")
    validate_telegram()
    if MODE in ("paper", "live"):
        validate_symbols()
    if MODE == "backtest":
        run_backtest()
    elif MODE == "paper":
        run_paper()
    elif MODE == "live":
        run_live()
    else:
        print(f'Неизвестный MODE="{MODE}". Используй: backtest / paper / live')
