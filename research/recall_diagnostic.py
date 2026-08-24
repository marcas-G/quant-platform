import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('bt_out'); OUT.mkdir(exist_ok=True)
files = sorted(glob.glob('bt_data/kline_*.parquet'))
df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
rename = {}
for c in df.columns:
    lc = str(c).lower()
    if lc in ('date','trade_date'): rename[c] = 'date'
    elif lc in ('code','ts_code','symbol'): rename[c] = 'code'
    elif lc == 'open': rename[c] = 'open'
    elif lc == 'high': rename[c] = 'high'
    elif lc == 'low': rename[c] = 'low'
    elif lc == 'close': rename[c] = 'close'
    elif lc in ('turn','turnover','turnover_rate'): rename[c] = 'turnover'
df = df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
df['date'] = pd.to_datetime(df['date'])
df['code'] = df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df = df.dropna().sort_values(['code','date']).reset_index(drop=True)
g = df.groupby('code', group_keys=False)

df['low250'] = g['low'].transform(lambda s: s.rolling(250, min_periods=250).min())
df['high250'] = g['high'].transform(lambda s: s.rolling(250, min_periods=250).max())
df['pos250'] = (df['close'] - df['low250']) / (df['high250'] - df['low250'])
df['to_ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10, min_periods=10).mean())
df['to_ratio'] = df['turnover'] / df['to_ma10_prior']
df['entry_open'] = g['open'].shift(-1)
# Correct target: after signal day T, start from T+1 open and look at highs of T+1...T+60.
df['future_high60'] = g['high'].transform(lambda s: s.shift(-1).iloc[::-1].rolling(60, min_periods=60).max().iloc[::-1])
df['mfe60'] = df['future_high60'] / df['entry_open'] - 1

base = df[df['entry_open'].notna() & df['pos250'].notna() & df['to_ratio'].notna() & df['mfe60'].notna()].copy()
base['stock_idx'] = base.groupby('code').cumcount()
base['low'] = base['pos250'].le(.20)
base['signal'] = base['low'] & base['to_ratio'].ge(1.5)

def cooldown_events(frame, mask, cooldown=60):
    x = frame[mask].sort_values(['code','stock_idx']).copy()
    keep = []
    last = {}
    for r in x.itertuples(index=False):
        c = r.code; p = int(r.stock_idx)
        ok = c not in last or p - last[c] > cooldown
        keep.append(ok)
        if ok: last[c] = p
    return x.loc[np.array(keep)].copy()

def make_valid_signal_index(frame, threshold):
    # A signal is valid only if the +50% (or threshold) happens AFTER that signal:
    # max(high[T+1:T+60]) / open[T+1] - 1 >= threshold.
    z = frame[frame['signal'] & frame['mfe60'].ge(threshold)]
    return {c: grp['stock_idx'].to_numpy() for c, grp in z.groupby('code')}

def captured_valid_after_start(row, days, valid_sig_idx):
    arr = valid_sig_idx.get(row.code)
    if arr is None or len(arr) == 0:
        return False
    p = int(row.stock_idx)
    j = np.searchsorted(arr, p, side='left')
    return j < len(arr) and arr[j] <= p + days

rows = []
for thr in [0.30, 0.40, 0.50, 0.60]:
    positive = base['low'] & base['mfe60'].ge(thr)
    # Low-position big-move opportunity episodes, deduped by 60 trading days.
    opp = cooldown_events(base, positive, 60)

    valid_sig = base['signal'] & base['mfe60'].ge(thr)
    n_signal = int(base['signal'].sum())
    n_valid_signal = int(valid_sig.sum())
    precision_signal_day = n_valid_signal / n_signal if n_signal else np.nan

    valid_sig_idx = make_valid_signal_index(base, thr)
    cap = {}
    rec = {}
    for days in [0, 5, 10, 20]:
        cap[days] = int(sum(captured_valid_after_start(r, days, valid_sig_idx) for r in opp.itertuples(index=False)))
        rec[days] = cap[days] / len(opp) if len(opp) else np.nan

    rows.append(dict(
        metric='mfe60', threshold=thr,
        opportunity_events=len(opp),
        signal_days=n_signal,
        valid_signal_days=n_valid_signal,
        precision_signal_day=precision_signal_day,
        captured_day0=cap[0], recall_day0=rec[0],
        captured_within_5d=cap[5], recall_within_5d=rec[5],
        captured_within_10d=cap[10], recall_within_10d=rec[10],
        captured_within_20d=cap[20], recall_within_20d=rec[20],
    ))

res = pd.DataFrame(rows)
res.to_csv(OUT/'recall_mfe60_corrected.csv', index=False)
print('--- CORRECTED MFE60 RECALL (signal precedes its own future-60d move) ---')
print(res.to_string(index=False))
(OUT/'recall_mfe60_corrected_meta.json').write_text(json.dumps({
    'target': 'For each signal day T: max(high[T+1:T+60]) / open[T+1] - 1 >= threshold',
    'low': 'pos250 <= 20%',
    'signal': 'low and turnover_t / prior10d_mean >= 1.5',
    'critical_fix': 'A later turnover signal is counted only if that signal day itself still has >=threshold MaxUp over its own subsequent 60 trading days. No signal occurring inside a pre-defined future window is credited unless the +move occurs after that signal.',
    'opportunity_dedup': 'earliest low+future-MFE positive date, 60 trading day cooldown per stock',
    'windows': '0/5/10/20 trading days after earliest eligible low opportunity date; each counted signal must independently satisfy future MFE60 target'
}, ensure_ascii=False, indent=2))
