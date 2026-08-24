import glob
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('bt_out_inventory_rotation')
OUT.mkdir(exist_ok=True)
FILES = sorted(glob.glob('bt_data/kline_*.parquet'))
TRAIN_END = pd.Timestamp('2023-12-31')
VAL_START = pd.Timestamp('2024-01-01')
WINDOWS = [3, 5, 10, 20]

# =============================================================================
# Strict timing contract
# Base signal known at T close:
#   pos250 <= 20%, turnover_T / mean(turnover[T-10:T-1]) >= 1.5
# Entry: T+1 open.
# Label only: max high over T+1..T+60 versus T+1 open >= +50%.
# Every feature below uses observations no later than T close.
# Discovery <= 2023; validation >= 2024.
# =============================================================================

# Load / normalize
parts = [pd.read_parquet(p) for p in FILES]
df = pd.concat(parts, ignore_index=True)
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
df = df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
df['date'] = pd.to_datetime(df['date'])
df['code'] = df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df = df.dropna().sort_values(['code','date']).reset_index(drop=True)
g = df.groupby('code', group_keys=False)
df['stock_idx'] = g.cumcount()

# Frozen recall signal
low250 = g['low'].transform(lambda s: s.rolling(250, min_periods=250).min())
high250 = g['high'].transform(lambda s: s.rolling(250, min_periods=250).max())
denom = high250 - low250
df['pos250'] = np.where(denom > 0, (df['close'] - low250) / denom, np.nan)
df['turn_ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10, min_periods=10).mean())
df['turn_shock'] = df['turnover'] / df['turn_ma10_prior']

# Price path inputs known by T close
prev_close = g['close'].shift(1)
df['logret'] = np.log(df['close'] / prev_close)
df['abs_logret'] = df['logret'].abs()

FEATURES = []
for n in WINDOWS:
    # n trading days ending at T: returns T-n+1..T and turnover over same days.
    cum_to = g['turnover'].transform(lambda s, n=n: s.rolling(n, min_periods=n).sum())
    path = df['abs_logret'].groupby(df['code']).transform(lambda s, n=n: s.rolling(n, min_periods=n).sum())
    close_n = g['close'].shift(n)
    net_signed = np.log(df['close'] / close_n)
    net_abs = net_signed.abs()

    # Strict earlier baseline: 20-day normal turnover ending before the n-day observation window.
    base_turn = g['turnover'].transform(lambda s, n=n: s.shift(n).rolling(20, min_periods=20).mean())
    rel_cum_to = cum_to / (n * base_turn.replace(0, np.nan))

    # Directional efficiency. Clip tiny numerical overshoots only.
    de = net_abs / path.replace(0, np.nan)
    de = de.clip(lower=0, upper=1)

    df[f'cumto_{n}'] = cum_to
    df[f'relcumto_{n}'] = rel_cum_to
    df[f'netmove_{n}'] = net_abs
    df[f'signedmove_{n}'] = net_signed
    df[f'path_{n}'] = path
    df[f'pdi_{n}'] = net_abs / cum_to.replace(0, np.nan)              # net displacement per turnover
    df[f'path_per_to_{n}'] = path / cum_to.replace(0, np.nan)        # total movement per turnover
    df[f'de_{n}'] = de                                                # directional efficiency
    df[f'rotation_raw_{n}'] = cum_to * (1.0 - de)                    # absolute-scale rotation
    df[f'rir_{n}'] = rel_cum_to * (1.0 - de)                         # relative inventory rotation

    FEATURES += [
        f'cumto_{n}', f'relcumto_{n}', f'pdi_{n}', f'path_per_to_{n}',
        f'de_{n}', f'rotation_raw_{n}', f'rir_{n}'
    ]

# Existing strong pre-entry controls for comparison only.
for n in [60, 120]:
    rolling_high = g['high'].transform(lambda s, n=n: s.rolling(n, min_periods=n).max())
    df[f'dd_from_high{n}'] = df['close'] / rolling_high - 1.0
for n in [10,20]:
    df[f'vol{n}_prior'] = df['logret'].groupby(df['code']).transform(
        lambda s, n=n: s.shift(1).rolling(n, min_periods=n).std()
    )

# Future label only
def forward_high60(s):
    out = s.shift(-1).iloc[::-1].rolling(60, min_periods=60).max().iloc[::-1]
    out.index = s.index
    return out

df['fwd_high60'] = g['high'].transform(forward_high60)
df['next_open'] = g['open'].shift(-1)
df['maxup60'] = df['fwd_high60'] / df['next_open'] - 1.0
df['positive'] = df['maxup60'] >= 0.50

df['signal'] = (df['pos250'] <= 0.20) & (df['turn_shock'] >= 1.50) & df['maxup60'].notna()
sig = df[df['signal']].copy().sort_values(['code','date'])

# 20-stock-day cooldown episode: first base signal in each cluster.
episode_keep = pd.Series(False, index=sig.index, dtype=bool)
for _, x in sig.groupby('code', sort=False):
    last = -10**9
    for ix, sidx in zip(x.index, x['stock_idx'].astype(int)):
        if sidx - last > 20:
            episode_keep.loc[ix] = True
            last = sidx
sig['episode_keep'] = episode_keep
epi = sig[sig['episode_keep']].copy()

# Baselines
baseline_rows = []
for name, frame in [('signal_day', sig), ('episode20', epi)]:
    for split, mask in [
        ('train', frame['date'] <= TRAIN_END),
        ('validation', frame['date'] >= VAL_START),
        ('all', pd.Series(True, index=frame.index)),
    ]:
        z = frame[mask]
        baseline_rows.append({
            'sample': name, 'split': split, 'n': len(z),
            'positives': int(z['positive'].sum()),
            'precision': float(z['positive'].mean()) if len(z) else np.nan,
        })
pd.DataFrame(baseline_rows).to_csv(OUT/'inventory_rotation_baselines.csv', index=False)

train = epi[epi['date'] <= TRAIN_END].copy()
val = epi[epi['date'] >= VAL_START].copy()
train_base_p = float(train['positive'].mean())
val_base_p = float(val['positive'].mean())
train_pos = int(train['positive'].sum())
val_pos = int(val['positive'].sum())

# Univariate: choose tail/direction only on train; evaluate frozen threshold OOS.
uni_rows = []
decile_rows = []
for feat in FEATURES:
    tr = train[[feat,'positive']].replace([np.inf,-np.inf], np.nan).dropna()
    va = val[[feat,'positive']].replace([np.inf,-np.inf], np.nan).dropna()
    if len(tr) < 500 or tr[feat].nunique() < 20 or len(va) < 200:
        continue

    edges = np.unique(tr[feat].quantile(np.linspace(0,1,11)).to_numpy())
    if len(edges) >= 4:
        edges[0], edges[-1] = -np.inf, np.inf
        for split_name, xx in [('train',tr),('validation',va)]:
            bins = pd.cut(xx[feat], bins=edges, include_lowest=True, duplicates='drop')
            tmp = xx.assign(bin=bins).dropna(subset=['bin'])
            for order, (b,z) in enumerate(tmp.groupby('bin', observed=True),1):
                decile_rows.append({
                    'feature': feat, 'split': split_name, 'bin_order': order,
                    'bin_left': float(b.left), 'bin_right': float(b.right),
                    'n': len(z), 'precision': float(z['positive'].mean())
                })

    candidates = []
    for frac in [0.20,0.30,0.40,0.50,0.60,0.70]:
        lo = float(tr[feat].quantile(frac))
        hi = float(tr[feat].quantile(1-frac))
        for direction,thr in [('low',lo),('high',hi)]:
            mask = tr[feat] <= thr if direction == 'low' else tr[feat] >= thr
            z = tr[mask]
            if len(z) >= 100:
                candidates.append((float(z['positive'].mean()), int(z['positive'].sum()), frac, direction, thr))
    candidates.sort(key=lambda x:(x[0],x[1]), reverse=True)
    tr_prec, _, frac, direction, thr = candidates[0]
    tr_sel = tr[tr[feat] <= thr] if direction == 'low' else tr[tr[feat] >= thr]
    va_sel = va[va[feat] <= thr] if direction == 'low' else va[va[feat] >= thr]
    uni_rows.append({
        'feature': feat, 'direction': direction, 'train_tail_frac_target': frac, 'threshold': thr,
        'train_n': len(tr_sel), 'train_precision': float(tr_sel['positive'].mean()),
        'train_lift': float(tr_sel['positive'].mean()/train_base_p),
        'train_positive_retention': float(tr_sel['positive'].sum()/train_pos),
        'val_n': len(va_sel), 'val_precision': float(va_sel['positive'].mean()) if len(va_sel) else np.nan,
        'val_lift': float(va_sel['positive'].mean()/val_base_p) if len(va_sel) else np.nan,
        'val_positive_retention': float(va_sel['positive'].sum()/val_pos),
        'val_signal_retention': float(len(va_sel)/len(val)),
    })

uni = pd.DataFrame(uni_rows).sort_values(['val_lift','val_positive_retention'], ascending=False)
uni.to_csv(OUT/'inventory_rotation_univariate.csv', index=False)
pd.DataFrame(decile_rows).to_csv(OUT/'inventory_rotation_deciles.csv', index=False)

# Decompose the proposed RIR: compare its component decile monotonicity by window.
summary_rows = []
for n in WINDOWS:
    for feat in [f'relcumto_{n}', f'de_{n}', f'pdi_{n}', f'path_per_to_{n}', f'rir_{n}']:
        r = uni[uni['feature'] == feat]
        if len(r):
            summary_rows.append(r.iloc[0].to_dict())
pd.DataFrame(summary_rows).to_csv(OUT/'inventory_rotation_core_summary.csv', index=False)

# Fixed-threshold year stability for the best train-selected feature in each family/window.
best_train = pd.DataFrame(uni_rows).sort_values(['train_lift','train_positive_retention'], ascending=False)
top_feats = best_train.head(8)
year_rows = []
for _, rule in top_feats.iterrows():
    feat, direction, thr = rule['feature'], rule['direction'], rule['threshold']
    for year, y in epi.groupby(epi['date'].dt.year):
        yy = y[[feat,'positive']].replace([np.inf,-np.inf],np.nan).dropna()
        if not len(yy):
            continue
        base_pos = int(yy['positive'].sum())
        sel = yy[yy[feat] <= thr] if direction == 'low' else yy[yy[feat] >= thr]
        year_rows.append({
            'feature': feat, 'direction': direction, 'threshold': thr, 'year': int(year),
            'base_n': len(yy), 'base_precision': float(yy['positive'].mean()),
            'selected_n': len(sel), 'selected_precision': float(sel['positive'].mean()) if len(sel) else np.nan,
            'positive_retention': float(sel['positive'].sum()/base_pos) if base_pos else np.nan,
            'signal_retention': float(len(sel)/len(yy)),
        })
pd.DataFrame(year_rows).to_csv(OUT/'inventory_rotation_year_stability.csv', index=False)

print('--- BASELINES ---')
print(pd.DataFrame(baseline_rows).to_string(index=False))
print('\n--- INVENTORY ROTATION OOS UNIVARIATE ---')
print(uni[['feature','direction','threshold','train_precision','val_precision','val_lift','val_positive_retention','val_signal_retention']].head(30).to_string(index=False))
print('\n--- CORE SUMMARY ---')
print(pd.DataFrame(summary_rows)[['feature','direction','threshold','val_precision','val_lift','val_positive_retention','val_signal_retention']].to_string(index=False))
