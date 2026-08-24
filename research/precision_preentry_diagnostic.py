import glob
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('bt_out')
OUT.mkdir(exist_ok=True)
FILES = sorted(glob.glob('bt_data/kline_*.parquet'))

# =============================================================================
# Goal
# =============================================================================
# Base signal at T close (frozen):
#   pos250 <= 20% AND turnover_T / mean(turnover[T-10:T-1]) >= 1.5
# Entry: T+1 open
# Positive label ONLY (future, never a feature):
#   max(high[T+1:T+60]) / open[T+1] - 1 >= 50%
#
# All precision features below use data available no later than T close.
# We report both raw signal-day statistics and 20-trading-day cooldown episodes.
# Discovery: <= 2023-12-31. Validation: >= 2024-01-01.
# =============================================================================

# -----------------------------------------------------------------------------
# Load / normalize
# -----------------------------------------------------------------------------
df = pd.concat([pd.read_parquet(p) for p in FILES], ignore_index=True)
rename = {}
for c in df.columns:
    lc = str(c).lower()
    if lc in ('date', 'trade_date'):
        rename[c] = 'date'
    elif lc in ('code', 'ts_code', 'symbol'):
        rename[c] = 'code'
    elif lc in ('open', 'high', 'low', 'close'):
        rename[c] = lc
    elif lc in ('turn', 'turnover', 'turnover_rate'):
        rename[c] = 'turnover'

df = df.rename(columns=rename)[['date', 'code', 'open', 'high', 'low', 'close', 'turnover']].copy()
df['date'] = pd.to_datetime(df['date'])
df['code'] = df['code'].astype(str).str.replace('.0', '', regex=False).str.zfill(6)
for c in ['open', 'high', 'low', 'close', 'turnover']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df = df.dropna().sort_values(['code', 'date']).reset_index(drop=True)
g = df.groupby('code', group_keys=False)
df['stock_idx'] = g.cumcount()

# -----------------------------------------------------------------------------
# Frozen recall features
# -----------------------------------------------------------------------------
df['low250'] = g['low'].transform(lambda s: s.rolling(250, min_periods=250).min())
df['high250'] = g['high'].transform(lambda s: s.rolling(250, min_periods=250).max())
denom = df['high250'] - df['low250']
df['pos250'] = np.where(denom > 0, (df['close'] - df['low250']) / denom, np.nan)

df['turn_ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10, min_periods=10).mean())
df['turn_shock'] = df['turnover'] / df['turn_ma10_prior']

# -----------------------------------------------------------------------------
# Strictly pre-entry features: only <= T close
# -----------------------------------------------------------------------------
df['prev_close'] = g['close'].shift(1)
df['ret_t'] = df['close'] / df['prev_close'] - 1.0
df['gap_t'] = df['open'] / df['prev_close'] - 1.0
df['oc_ret_t'] = df['close'] / df['open'] - 1.0

df['range_t'] = (df['high'] - df['low']) / df['prev_close']
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['prev_close']).abs(),
    (df['low'] - df['prev_close']).abs(),
], axis=1).max(axis=1)
df['true_range_t'] = tr / df['prev_close']
spread = df['high'] - df['low']
df['clv_t'] = np.where(spread > 0, (df['close'] - df['low']) / spread, 0.5)
df['lower_recovery_t'] = np.where(spread > 0, (df['close'] - df['low']) / spread, 0.5)

# Volatility ending before T (prior state) and including T (state + shock response)
for n in [3, 5, 10, 20]:
    df[f'vol{n}_prior'] = g['ret_t'].transform(lambda s, n=n: s.shift(1).rolling(n, min_periods=n).std())
    df[f'vol{n}_inclT'] = g['ret_t'].transform(lambda s, n=n: s.rolling(n, min_periods=n).std())
    df[f'range_mean{n}_prior'] = g['range_t'].transform(lambda s, n=n: s.shift(1).rolling(n, min_periods=n).mean())

df['vol5_20_prior'] = df['vol5_prior'] / df['vol20_prior'].replace(0, np.nan)
df['vol10_20_prior'] = df['vol10_prior'] / df['vol20_prior'].replace(0, np.nan)
df['range5_20_prior'] = df['range_mean5_prior'] / df['range_mean20_prior'].replace(0, np.nan)

# Immediate impact / absorption proxies known at T close
# Lower values = more turnover for less absolute/downward price movement.
df['abs_impact_per_shock'] = df['ret_t'].abs() / df['turn_shock'].replace(0, np.nan)
df['down_impact_per_shock'] = (-df['ret_t']).clip(lower=0) / df['turn_shock'].replace(0, np.nan)
df['range_per_shock'] = df['range_t'] / df['turn_shock'].replace(0, np.nan)
df['turnover_per_abs_move'] = df['turn_shock'] / (df['ret_t'].abs() + 1e-4)
df['turnover_per_range'] = df['turn_shock'] / (df['range_t'] + 1e-4)

# Cumulative turnover relative to a strictly earlier baseline.
for n in [5, 10, 20]:
    recent = g['turnover'].transform(lambda s, n=n: s.rolling(n, min_periods=n).mean())
    base = g['turnover'].transform(lambda s, n=n: s.shift(n).rolling(20, min_periods=20).mean())
    df[f'turn_mean{n}_vs_prior20'] = recent / base.replace(0, np.nan)

# Prior shock counts exclude T itself.
for thr in [1.2, 1.5]:
    raw = (df['turn_shock'] >= thr).astype(float)
    for n in [5, 10, 20]:
        df[f'prior{n}_shock{str(thr).replace(".","p")}_count'] = raw.groupby(df['code']).transform(
            lambda s, n=n: s.shift(1).rolling(n, min_periods=n).sum()
        )

# Drawdown / decline speed available at T.
for n in [20, 60, 120]:
    prior_high = g['high'].transform(lambda s, n=n: s.rolling(n, min_periods=n).max())
    df[f'dd_from_high{n}'] = df['close'] / prior_high - 1.0
for n in [5, 10, 20]:
    df[f'ret_{n}d'] = df['close'] / g['close'].shift(n) - 1.0

# -----------------------------------------------------------------------------
# Future LABEL ONLY: from T+1 open, max high over T+1..T+60
# -----------------------------------------------------------------------------
def forward_high60(s):
    out = s.shift(-1).iloc[::-1].rolling(60, min_periods=60).max().iloc[::-1]
    out.index = s.index
    return out

df['fwd_high60'] = g['high'].transform(forward_high60)
df['next_open'] = g['open'].shift(-1)
df['maxup60'] = df['fwd_high60'] / df['next_open'] - 1.0
df['positive'] = df['maxup60'] >= 0.50

# Frozen base signal.
df['signal'] = (df['pos250'] <= 0.20) & (df['turn_shock'] >= 1.50) & df['maxup60'].notna()
sig = df[df['signal']].copy().sort_values(['code', 'date'])

# -----------------------------------------------------------------------------
# 20-trading-day cooldown episodes: first signal, then suppress <=20 stock days.
# -----------------------------------------------------------------------------
def cooldown_events(x, cooldown=20):
    keep = []
    last = -10**9
    for idx in x['stock_idx'].astype(int).to_numpy():
        if idx - last > cooldown:
            keep.append(True)
            last = idx
        else:
            keep.append(False)
    return pd.Series(keep, index=x.index)

sig['episode_keep'] = sig.groupby('code', group_keys=False).apply(cooldown_events).reset_index(level=0, drop=True)
epi = sig[sig['episode_keep']].copy()

# -----------------------------------------------------------------------------
# Feature set
# -----------------------------------------------------------------------------
FEATURES = [
    'turn_shock',
    'ret_t', 'gap_t', 'oc_ret_t', 'range_t', 'true_range_t', 'clv_t',
    'vol3_prior', 'vol5_prior', 'vol10_prior', 'vol20_prior',
    'vol3_inclT', 'vol5_inclT', 'vol10_inclT', 'vol20_inclT',
    'vol5_20_prior', 'vol10_20_prior', 'range5_20_prior',
    'abs_impact_per_shock', 'down_impact_per_shock', 'range_per_shock',
    'turnover_per_abs_move', 'turnover_per_range',
    'turn_mean5_vs_prior20', 'turn_mean10_vs_prior20', 'turn_mean20_vs_prior20',
    'prior5_shock1p2_count', 'prior10_shock1p2_count', 'prior20_shock1p2_count',
    'prior5_shock1p5_count', 'prior10_shock1p5_count', 'prior20_shock1p5_count',
    'dd_from_high20', 'dd_from_high60', 'dd_from_high120',
    'ret_5d', 'ret_10d', 'ret_20d',
]
FEATURES = [c for c in FEATURES if c in df.columns]

TRAIN_END = pd.Timestamp('2023-12-31')
VAL_START = pd.Timestamp('2024-01-01')

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def metrics(x, base_positive_n=None):
    n = len(x)
    pos = int(x['positive'].sum()) if n else 0
    precision = pos / n if n else np.nan
    recall_ret = pos / base_positive_n if base_positive_n else np.nan
    return n, pos, precision, recall_ret


def baseline_table(frame, sample_name):
    rows = []
    for split, m in [('train', frame['date'] <= TRAIN_END), ('validation', frame['date'] >= VAL_START), ('all', pd.Series(True, index=frame.index))]:
        x = frame[m]
        n, pos, p, _ = metrics(x)
        rows.append({'sample': sample_name, 'split': split, 'n': n, 'positives': pos, 'precision': p})
    return rows

baseline_rows = baseline_table(sig, 'signal_day') + baseline_table(epi, 'episode20')
baselines = pd.DataFrame(baseline_rows)
baselines.to_csv(OUT / 'precision_preentry_baselines.csv', index=False)

# -----------------------------------------------------------------------------
# Univariate train->validation tail tests on episode sample.
# Tail orientation and threshold are selected ONLY on train.
# Candidate tails: low/high 20%, 30%, 40%, 50%.
# -----------------------------------------------------------------------------
train = epi[epi['date'] <= TRAIN_END].copy()
val = epi[epi['date'] >= VAL_START].copy()
train_base_p = float(train['positive'].mean())
val_base_p = float(val['positive'].mean())
train_base_pos = int(train['positive'].sum())
val_base_pos = int(val['positive'].sum())

uni_rows = []
decile_rows = []
for feat in FEATURES:
    tr = train[[feat, 'positive']].dropna().copy()
    va = val[[feat, 'positive']].dropna().copy()
    if len(tr) < 200 or tr[feat].nunique() < 10 or len(va) < 100:
        continue

    # Training deciles for shape diagnostics; apply train edges to validation.
    qs = np.unique(tr[feat].quantile(np.linspace(0, 1, 11)).to_numpy())
    if len(qs) >= 4:
        qs[0] = -np.inf
        qs[-1] = np.inf
        tr_bin = pd.cut(tr[feat], bins=qs, include_lowest=True, duplicates='drop')
        va_bin = pd.cut(va[feat], bins=qs, include_lowest=True, duplicates='drop')
        for split_name, xx, bb in [('train', tr, tr_bin), ('validation', va, va_bin)]:
            tmp = xx.assign(bin=bb).dropna(subset=['bin'])
            for i, (b, z) in enumerate(tmp.groupby('bin', observed=True), 1):
                decile_rows.append({
                    'feature': feat, 'split': split_name, 'bin_order': i,
                    'bin_left': float(b.left), 'bin_right': float(b.right),
                    'n': len(z), 'precision': float(z['positive'].mean())
                })

    candidates = []
    for frac in [0.20, 0.30, 0.40, 0.50]:
        lo = float(tr[feat].quantile(frac))
        hi = float(tr[feat].quantile(1 - frac))
        for direction, thr in [('low', lo), ('high', hi)]:
            sel = tr[feat] <= thr if direction == 'low' else tr[feat] >= thr
            z = tr[sel]
            if len(z) < 50:
                continue
            candidates.append((float(z['positive'].mean()), frac, direction, thr, len(z), int(z['positive'].sum())))
    if not candidates:
        continue
    # Pick on training precision, tie-break by larger retained positive count.
    candidates.sort(key=lambda x: (x[0], x[5]), reverse=True)
    tr_prec, frac, direction, thr, tr_n, tr_pos = candidates[0]
    tr_sel = tr[feat] <= thr if direction == 'low' else tr[feat] >= thr
    va_sel = va[feat] <= thr if direction == 'low' else va[feat] >= thr
    tr_z = tr[tr_sel]
    va_z = va[va_sel]

    uni_rows.append({
        'feature': feat,
        'direction': direction,
        'train_tail_frac_target': frac,
        'threshold': thr,
        'train_n': len(tr_z),
        'train_precision': float(tr_z['positive'].mean()),
        'train_lift': float(tr_z['positive'].mean() / train_base_p),
        'train_recall_retention': float(tr_z['positive'].sum() / train_base_pos) if train_base_pos else np.nan,
        'val_n': len(va_z),
        'val_precision': float(va_z['positive'].mean()) if len(va_z) else np.nan,
        'val_lift': float(va_z['positive'].mean() / val_base_p) if len(va_z) and val_base_p else np.nan,
        'val_recall_retention': float(va_z['positive'].sum() / val_base_pos) if val_base_pos else np.nan,
        'val_signal_retention': float(len(va_z) / len(val)) if len(val) else np.nan,
    })

uni = pd.DataFrame(uni_rows).sort_values(['val_lift', 'val_recall_retention'], ascending=False)
uni.to_csv(OUT / 'precision_preentry_univariate.csv', index=False)
pd.DataFrame(decile_rows).to_csv(OUT / 'precision_preentry_deciles.csv', index=False)

# -----------------------------------------------------------------------------
# Pairwise intersections. Features are selected ONLY by training lift.
# Use each feature's training-selected direction/threshold, then evaluate OOS.
# -----------------------------------------------------------------------------
uni_train_rank = pd.DataFrame(uni_rows).sort_values(['train_lift', 'train_recall_retention'], ascending=False)
top = uni_train_rank.head(8).copy()
pair_rows = []
for i in range(len(top)):
    for j in range(i + 1, len(top)):
        a = top.iloc[i]
        b = top.iloc[j]
        fa, fb = a['feature'], b['feature']

        def mask(frame, row):
            s = frame[row['feature']]
            return s <= row['threshold'] if row['direction'] == 'low' else s >= row['threshold']

        tr_mask = mask(train, a) & mask(train, b)
        va_mask = mask(val, a) & mask(val, b)
        trz = train[tr_mask]
        vaz = val[va_mask]
        if len(trz) < 50 or len(vaz) < 30:
            continue
        pair_rows.append({
            'feature_a': fa, 'dir_a': a['direction'], 'thr_a': a['threshold'],
            'feature_b': fb, 'dir_b': b['direction'], 'thr_b': b['threshold'],
            'train_n': len(trz), 'train_precision': float(trz['positive'].mean()),
            'train_lift': float(trz['positive'].mean() / train_base_p),
            'train_recall_retention': float(trz['positive'].sum() / train_base_pos) if train_base_pos else np.nan,
            'val_n': len(vaz), 'val_precision': float(vaz['positive'].mean()),
            'val_lift': float(vaz['positive'].mean() / val_base_p) if val_base_p else np.nan,
            'val_recall_retention': float(vaz['positive'].sum() / val_base_pos) if val_base_pos else np.nan,
            'val_signal_retention': float(len(vaz) / len(val)) if len(val) else np.nan,
        })

pairs = pd.DataFrame(pair_rows)
if len(pairs):
    pairs = pairs.sort_values(['val_lift', 'val_recall_retention'], ascending=False)
pairs.to_csv(OUT / 'precision_preentry_pairs.csv', index=False)

# -----------------------------------------------------------------------------
# Explicit 2D turnover-shock x volatility / absorption grids for interpretation.
# Train quantile edges, OOS cell precision.
# -----------------------------------------------------------------------------
grid_rows = []
for feat in ['vol5_prior', 'vol5_inclT', 'vol5_20_prior', 'range_t', 'clv_t', 'abs_impact_per_shock', 'range_per_shock']:
    if feat not in train.columns:
        continue
    tr = train[['turn_shock', feat, 'positive']].dropna()
    va = val[['turn_shock', feat, 'positive']].dropna()
    if len(tr) < 200 or len(va) < 100:
        continue
    qx = np.unique(tr['turn_shock'].quantile([0, .25, .5, .75, 1]).to_numpy())
    qy = np.unique(tr[feat].quantile([0, .25, .5, .75, 1]).to_numpy())
    if len(qx) < 4 or len(qy) < 4:
        continue
    qx[0], qx[-1] = -np.inf, np.inf
    qy[0], qy[-1] = -np.inf, np.inf
    for split_name, xx in [('train', tr), ('validation', va)]:
        bx = pd.cut(xx['turn_shock'], qx, include_lowest=True, duplicates='drop')
        by = pd.cut(xx[feat], qy, include_lowest=True, duplicates='drop')
        z = xx.assign(xbin=bx, ybin=by).dropna(subset=['xbin', 'ybin'])
        for (xb, yb), cell in z.groupby(['xbin', 'ybin'], observed=True):
            grid_rows.append({
                'feature_y': feat, 'split': split_name,
                'turn_bin_left': float(xb.left), 'turn_bin_right': float(xb.right),
                'y_bin_left': float(yb.left), 'y_bin_right': float(yb.right),
                'n': len(cell), 'precision': float(cell['positive'].mean())
            })
pd.DataFrame(grid_rows).to_csv(OUT / 'precision_preentry_2d_grids.csv', index=False)

# -----------------------------------------------------------------------------
# Print compact summaries
# -----------------------------------------------------------------------------
print('--- BASELINES ---')
print(baselines.to_string(index=False))
print('\n--- TOP OOS UNIVARIATE ---')
cols = ['feature','direction','threshold','train_precision','val_precision','val_lift','val_recall_retention','val_signal_retention']
print(uni[cols].head(20).to_string(index=False))
print('\n--- TOP OOS PAIRS (chosen from train-top features only) ---')
if len(pairs):
    cols2 = ['feature_a','dir_a','feature_b','dir_b','train_precision','val_precision','val_lift','val_recall_retention','val_signal_retention']
    print(pairs[cols2].head(20).to_string(index=False))
else:
    print('no valid pairs')

# Sanity: no feature column name may contain future/label.
for c in FEATURES:
    assert 'fwd' not in c.lower() and 'maxup' not in c.lower() and 'positive' not in c.lower()
