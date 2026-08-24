import glob
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('bt_out')
OUT.mkdir(exist_ok=True)
FILES = sorted(glob.glob('bt_data/kline_*.parquet'))

# -----------------------------------------------------------------------------
# Load full-market daily bars
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

# -----------------------------------------------------------------------------
# Strict real-time features
# -----------------------------------------------------------------------------
df['low250'] = g['low'].transform(lambda s: s.rolling(250, min_periods=250).min())
df['high250'] = g['high'].transform(lambda s: s.rolling(250, min_periods=250).max())
df['pos250'] = (df['close'] - df['low250']) / (df['high250'] - df['low250'])

df['ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10, min_periods=10).mean())
df['r1'] = df['turnover'] / df['ma10_prior']

# Gradual turnover channels. Denominators end before the numerator window begins.
mean3 = g['turnover'].transform(lambda s: s.rolling(3, min_periods=3).mean())
base10_before3 = g['turnover'].transform(lambda s: s.shift(3).rolling(10, min_periods=10).mean())
df['r3_10'] = mean3 / base10_before3

mean5 = g['turnover'].transform(lambda s: s.rolling(5, min_periods=5).mean())
base20_before5 = g['turnover'].transform(lambda s: s.shift(5).rolling(20, min_periods=20).mean())
df['r5_20'] = mean5 / base20_before5

for thr in [1.15, 1.20, 1.25]:
    col = f'cnt5_{str(thr).replace(".", "p")}'
    flag = (df['r1'] >= thr).astype(float)
    df[col] = flag.groupby(df['code']).transform(lambda s: s.rolling(5, min_periods=5).sum())

# Future 60-trading-day max upside from T+1 open. This is LABEL ONLY.
def add_forward_60(x):
    x = x.copy()
    fut_high = x['high'].shift(-1)
    x['fwd_high60'] = fut_high.iloc[::-1].rolling(60, min_periods=60).max().iloc[::-1].to_numpy()
    x['next_open'] = x['open'].shift(-1)
    x['maxup60_from_signal'] = x['fwd_high60'] / x['next_open'] - 1.0
    return x

df = df.groupby('code', group_keys=False).apply(add_forward_60).reset_index(drop=True)
df['stock_idx'] = df.groupby('code').cumcount()

# -----------------------------------------------------------------------------
# Target = 15% ZigZag structural bottom, previous down leg >=30%, then +50% within 60d
# -----------------------------------------------------------------------------
target_path = OUT / 'segment_structural_target_events.csv'
if not target_path.exists():
    raise SystemExit('missing segment_structural_target_events.csv; run segment_structure_diagnostic.py first')
targets = pd.read_csv(target_path)
targets = targets[(targets['threshold'].round(2) == 0.15) & (targets['decline_class'] == 'deep_>=30pct')].copy()
targets['low_date'] = pd.to_datetime(targets['low_date'])
targets['code'] = targets['code'].astype(str).str.replace('.0', '', regex=False).str.zfill(6)
assert len(targets) == 5253, len(targets)

idx_map = df.set_index(['code', 'date'])['stock_idx']
stock_frames = {c: x for c, x in df.groupby('code', sort=False)}

# -----------------------------------------------------------------------------
# Mutually exclusive M1 / M2 / M3 decomposition, primary window = bottom-20 .. bottom
#
# HIT: effective low-band shock exists:
#      r1>=1.5, pos250<=20%, AND from that shock T+1 forward 60d MaxUp>=50%.
# M2 Band: no HIT, but an effective r1>=1.5 shock exists above the 20% band.
# M1 Timing: no effective shock anywhere, but a raw r1>=1.5 shock exists somewhere.
# M3 True no-shock: no raw r1>=1.5 shock anywhere in the window.
#
# The priority HIT -> M2 -> M1 -> M3 makes the classes mutually exclusive and causal.
# -----------------------------------------------------------------------------
rows = []
for ev in targets.itertuples(index=False):
    key = (ev.code, ev.low_date)
    try:
        p = int(idx_map.loc[key])
    except KeyError:
        continue
    grp = stock_frames[ev.code]
    w = grp[(grp['stock_idx'] >= p - 20) & (grp['stock_idx'] <= p)].copy()
    if w.empty:
        continue

    lowrow = grp[grp['stock_idx'] == p].iloc[0]
    low_px = float(lowrow['low'])
    w['offset'] = w['stock_idx'] - p
    w['raw_shock'] = w['r1'] >= 1.50
    w['effective_shock'] = w['raw_shock'] & (w['maxup60_from_signal'] >= 0.50)
    w['effective_low_shock'] = w['effective_shock'] & (w['pos250'] <= 0.20)

    hit = bool(w['effective_low_shock'].fillna(False).any())
    eff_any = bool(w['effective_shock'].fillna(False).any())
    raw_any = bool(w['raw_shock'].fillna(False).any())

    if hit:
        cls = 'HIT_effective_lowband_R1'
    elif eff_any:
        cls = 'M2_above_band_effective_shock'
    elif raw_any:
        cls = 'M1_timing_raw_shock_too_early'
    else:
        cls = 'M3_true_no_1p5x_shock'

    rec = {
        'code': ev.code,
        'low_date': ev.low_date,
        'class': cls,
        'bottom_low': low_px,
        'n_days_window': len(w),
        'max_r1': w['r1'].max(),
        'max_r3_10': w['r3_10'].max(),
        'max_r5_20': w['r5_20'].max(),
        'max_cnt5_1p15': w['cnt5_1p15'].max(),
        'max_cnt5_1p2': w['cnt5_1p2'].max(),
        'max_cnt5_1p25': w['cnt5_1p25'].max(),
    }

    raw = w[w['raw_shock']].copy()
    eff = w[w['effective_shock']].copy()
    eff_low = w[w['effective_low_shock']].copy()

    if not raw.empty:
        latest = raw.sort_values('stock_idx').iloc[-1]
        rec.update({
            'latest_raw_offset': int(latest['offset']),
            'latest_raw_pos250': latest['pos250'],
            'latest_raw_r1': latest['r1'],
            'latest_raw_maxup60': latest['maxup60_from_signal'],
            'latest_raw_close_above_bottom': latest['close'] / low_px - 1.0,
            'raw_shock_count': len(raw),
            'raw_lowband_shock_count': int((raw['pos250'] <= 0.20).sum()),
        })
    if not eff.empty:
        # Closest-to-low-band effective shock is the one most relevant to testing the 20% boundary.
        chosen = eff.sort_values('pos250').iloc[0]
        rec.update({
            'effective_shock_count_anypos': len(eff),
            'closest_effective_pos250': chosen['pos250'],
            'closest_effective_offset': int(chosen['offset']),
            'closest_effective_r1': chosen['r1'],
            'closest_effective_maxup60': chosen['maxup60_from_signal'],
            'closest_effective_close_above_bottom': chosen['close'] / low_px - 1.0,
        })
    if not eff_low.empty:
        chosen = eff_low.sort_values('stock_idx').iloc[-1]
        rec.update({
            'latest_effective_low_offset': int(chosen['offset']),
            'latest_effective_low_pos250': chosen['pos250'],
            'latest_effective_low_r1': chosen['r1'],
        })

    rows.append(rec)

events = pd.DataFrame(rows)
events.to_csv(OUT / 'm123_event_decomposition.csv', index=False)

# Main class counts
class_order = [
    'HIT_effective_lowband_R1',
    'M1_timing_raw_shock_too_early',
    'M2_above_band_effective_shock',
    'M3_true_no_1p5x_shock',
]
class_summary = events['class'].value_counts().reindex(class_order, fill_value=0).rename_axis('class').reset_index(name='n')
class_summary['share_all_targets'] = class_summary['n'] / len(events)
miss_n = int((events['class'] != 'HIT_effective_lowband_R1').sum())
class_summary['share_of_misses'] = np.where(
    class_summary['class'].eq('HIT_effective_lowband_R1'), np.nan, class_summary['n'] / miss_n
)
class_summary.to_csv(OUT / 'm123_class_summary.csv', index=False)

# -----------------------------------------------------------------------------
# M2: quantify whether 20% is simply too tight
# -----------------------------------------------------------------------------
m2 = events[events['class'] == 'M2_above_band_effective_shock'].copy()
def pos_band(x):
    if pd.isna(x):
        return 'NA'
    if x <= 0.25:
        return '20-25%'
    if x <= 0.30:
        return '25-30%'
    if x <= 0.40:
        return '30-40%'
    return '>40%'
if len(m2):
    m2['closest_effective_pos_band'] = m2['closest_effective_pos250'].map(pos_band)
    m2_band = m2['closest_effective_pos_band'].value_counts().reindex(['20-25%', '25-30%', '30-40%', '>40%', 'NA'], fill_value=0).rename_axis('band').reset_index(name='n')
    m2_band['share_M2'] = m2_band['n'] / len(m2)
else:
    m2_band = pd.DataFrame(columns=['band', 'n', 'share_M2'])
m2_band.to_csv(OUT / 'm2_position_bands.csv', index=False)

# Direct sensitivity: how much target recall would rise if ONLY the position cap changed,
# while keeping r1>=1.5 and MaxUp60-from-signal>=50% unchanged.
poscap_rows = []
for cap in [0.20, 0.25, 0.30, 0.40, 1.00]:
    hit_count = 0
    for ev in targets.itertuples(index=False):
        try:
            p = int(idx_map.loc[(ev.code, ev.low_date)])
        except KeyError:
            continue
        grp = stock_frames[ev.code]
        w = grp[(grp['stock_idx'] >= p - 20) & (grp['stock_idx'] <= p)]
        mask = (w['r1'] >= 1.50) & (w['pos250'] <= cap) & (w['maxup60_from_signal'] >= 0.50)
        hit_count += int(mask.fillna(False).any())
    poscap_rows.append({'pos_cap': cap, 'hits': hit_count, 'recall': hit_count / len(targets)})
pd.DataFrame(poscap_rows).to_csv(OUT / 'm2_poscap_sensitivity.csv', index=False)

# -----------------------------------------------------------------------------
# M1: timing profile — shocks exist but are too early to leave +50% within next 60d
# -----------------------------------------------------------------------------
m1 = events[events['class'] == 'M1_timing_raw_shock_too_early'].copy()
if len(m1):
    def offset_band(x):
        if pd.isna(x): return 'NA'
        if x <= -16: return '-20..-16'
        if x <= -11: return '-15..-11'
        if x <= -6: return '-10..-6'
        if x <= -3: return '-5..-3'
        if x <= -1: return '-2..-1'
        return '0'
    m1['latest_raw_offset_band'] = m1['latest_raw_offset'].map(offset_band)
    m1_offset = m1['latest_raw_offset_band'].value_counts().reindex(['-20..-16','-15..-11','-10..-6','-5..-3','-2..-1','0','NA'], fill_value=0).rename_axis('offset_band').reset_index(name='n')
    m1_offset['share_M1'] = m1_offset['n'] / len(m1)
else:
    m1_offset = pd.DataFrame(columns=['offset_band','n','share_M1'])
m1_offset.to_csv(OUT / 'm1_timing_offsets.csv', index=False)

m1_metrics = []
for c in ['latest_raw_offset','latest_raw_pos250','latest_raw_r1','latest_raw_maxup60','latest_raw_close_above_bottom','raw_shock_count','raw_lowband_shock_count']:
    s = pd.to_numeric(m1[c], errors='coerce').dropna() if c in m1.columns else pd.Series(dtype=float)
    if len(s):
        m1_metrics.append({'feature': c, 'n': len(s), 'mean': s.mean(), 'median': s.median(), 'p25': s.quantile(.25), 'p75': s.quantile(.75), 'p90': s.quantile(.90)})
pd.DataFrame(m1_metrics).to_csv(OUT / 'm1_timing_feature_summary.csv', index=False)

# -----------------------------------------------------------------------------
# M3: true no-single-day-shock cases. Test gradual turnover channels.
# A candidate is counted as an effective gradual capture only if, on that rule day,
# pos250 is under a chosen cap AND MaxUp60 from T+1 is still >=50%.
# -----------------------------------------------------------------------------
gradual_rules = {}
for thr in [1.10, 1.15, 1.20, 1.25, 1.30]:
    gradual_rules[f'R2_3d10_ge{str(thr).replace(".","p")}'] = lambda x, t=thr: x['r3_10'] >= t
for thr in [1.05, 1.10, 1.15, 1.20, 1.25]:
    gradual_rules[f'R3_5d20_ge{str(thr).replace(".","p")}'] = lambda x, t=thr: x['r5_20'] >= t
for base_thr in [1.15, 1.20, 1.25]:
    col = f'cnt5_{str(base_thr).replace(".","p")}'
    for n in [2, 3, 4]:
        gradual_rules[f'R4_count5_r1ge{str(base_thr).replace(".","p")}_ge{n}'] = lambda x, c=col, n=n: x[c] >= n

# Global low-band signal-day counts to understand noise/candidate inflation.
base_r1_global = int(((df['pos250'] <= 0.20) & (df['r1'] >= 1.50)).sum())
global_gradual = {}
for name, fn in gradual_rules.items():
    global_gradual[name] = int(((df['pos250'] <= 0.20) & fn(df).fillna(False)).sum())

m3 = events[events['class'] == 'M3_true_no_1p5x_shock'].copy()
m3_keys = {(r.code, pd.Timestamp(r.low_date)) for r in m3.itertuples(index=False)}
grad_rows = []
for cap in [0.20, 0.25, 0.30]:
    hitsets = {name: 0 for name in gradual_rules}
    for code, low_date in m3_keys:
        try:
            p = int(idx_map.loc[(code, low_date)])
        except KeyError:
            continue
        grp = stock_frames[code]
        w = grp[(grp['stock_idx'] >= p - 20) & (grp['stock_idx'] <= p)]
        for name, fn in gradual_rules.items():
            mask = fn(w).fillna(False) & (w['pos250'] <= cap) & (w['maxup60_from_signal'] >= 0.50)
            hitsets[name] += int(mask.any())
    for name in gradual_rules:
        n_hit = hitsets[name]
        grad_rows.append({
            'pos_cap': cap,
            'rule': name,
            'm3_n': len(m3),
            'm3_hits': n_hit,
            'm3_coverage': n_hit / len(m3) if len(m3) else np.nan,
            'incremental_recall_all_targets_if_added_to_R1': n_hit / len(targets),
            'union_recall_R1_plus_this_M3_rule': (int((events['class'] == 'HIT_effective_lowband_R1').sum()) + n_hit) / len(targets),
            'global_low_signal_days_rule': global_gradual[name],
            'global_rule_days_vs_R1_days': global_gradual[name] / base_r1_global if base_r1_global else np.nan,
        })
grad = pd.DataFrame(grad_rows)
grad.to_csv(OUT / 'm3_gradual_rule_grid.csv', index=False)

# Pareto-ish views: prefer high M3 coverage with lower global signal inflation.
for cap in [0.20, 0.25, 0.30]:
    show = grad[grad['pos_cap'] == cap].sort_values(['m3_coverage', 'global_rule_days_vs_R1_days'], ascending=[False, True])
    show.to_csv(OUT / f'm3_gradual_rank_poscap_{int(cap*100)}.csv', index=False)

# -----------------------------------------------------------------------------
# Human-readable console output
# -----------------------------------------------------------------------------
print('--- M1 / M2 / M3 CLASS SUMMARY ---')
print(class_summary.to_string(index=False))
print('\n--- M2 EFFECTIVE SHOCK POSITION BANDS ---')
print(m2_band.to_string(index=False))
print('\n--- R1 POSITION-CAP SENSITIVITY ---')
print(pd.DataFrame(poscap_rows).to_string(index=False))
print('\n--- M1 TIMING OFFSETS (LATEST RAW SHOCK) ---')
print(m1_offset.to_string(index=False))
print('\n--- M1 FEATURE SUMMARY ---')
print(pd.DataFrame(m1_metrics).to_string(index=False))
print('\n--- M3 TOP GRADUAL RULES, POS<=20% ---')
show = grad[grad['pos_cap'] == 0.20].sort_values(['m3_coverage', 'global_rule_days_vs_R1_days'], ascending=[False, True])
print(show[['rule','m3_coverage','incremental_recall_all_targets_if_added_to_R1','union_recall_R1_plus_this_M3_rule','global_rule_days_vs_R1_days']].head(20).to_string(index=False))
print('\n--- M3 TOP GRADUAL RULES, POS<=30% ---')
show = grad[grad['pos_cap'] == 0.30].sort_values(['m3_coverage', 'global_rule_days_vs_R1_days'], ascending=[False, True])
print(show[['rule','m3_coverage','incremental_recall_all_targets_if_added_to_R1','union_recall_R1_plus_this_M3_rule','global_rule_days_vs_R1_days']].head(20).to_string(index=False))
