import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path('bt_out')
OUT.mkdir(exist_ok=True)
FILES = sorted(glob.glob('bt_data/kline_*.parquet'))
THRESHOLDS = (0.10, 0.15, 0.20)


def load_data():
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
    df = df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
    df['date'] = pd.to_datetime(df['date'])
    df['code'] = df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
    for c in ['open','high','low','close','turnover']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna().sort_values(['code','date']).reset_index(drop=True)
    return df


def zigzag_pivots(close, threshold):
    """Return list of (idx, type, price), type in {'H','L'}.

    Pivots are retrospective structural extrema confirmed after a directional
    change of `threshold`. This is used only for ex-post regime labeling, not
    as a tradable signal.
    """
    n = len(close)
    if n < 2:
        return []
    pivots = []
    run_high = close[0]
    high_i = 0
    run_low = close[0]
    low_i = 0
    trend = 0  # 0 unknown, +1 up leg, -1 down leg

    for i in range(1, n):
        p = close[i]
        if trend == 0:
            if p > run_high:
                run_high, high_i = p, i
            if p < run_low:
                run_low, low_i = p, i
            if run_low > 0 and run_high / run_low - 1 >= threshold:
                # whichever extreme came first determines initial direction
                if low_i < high_i:
                    pivots.append((low_i, 'L', run_low))
                    trend = +1
                    run_high, high_i = p, i
                else:
                    pivots.append((high_i, 'H', run_high))
                    trend = -1
                    run_low, low_i = p, i
        elif trend == +1:
            if p >= run_high:
                run_high, high_i = p, i
            elif run_high > 0 and p / run_high - 1 <= -threshold:
                pivots.append((high_i, 'H', run_high))
                trend = -1
                run_low, low_i = p, i
        else:
            if p <= run_low:
                run_low, low_i = p, i
            elif run_low > 0 and p / run_low - 1 >= threshold:
                pivots.append((low_i, 'L', run_low))
                trend = +1
                run_high, high_i = p, i

    # no unconfirmed terminal pivot is added
    # remove accidental duplicates and enforce alternation
    clean = []
    for x in pivots:
        if clean and x[0] == clean[-1][0]:
            continue
        if clean and x[1] == clean[-1][1]:
            # retain more extreme pivot of same type
            if x[1] == 'H' and x[2] > clean[-1][2]:
                clean[-1] = x
            elif x[1] == 'L' and x[2] < clean[-1][2]:
                clean[-1] = x
        else:
            clean.append(x)
    return clean


def rolling_features(df):
    g = df.groupby('code', group_keys=False)
    df['low250'] = g['low'].transform(lambda s: s.rolling(250,min_periods=250).min())
    df['high250'] = g['high'].transform(lambda s: s.rolling(250,min_periods=250).max())
    df['pos250'] = (df['close'] - df['low250']) / (df['high250'] - df['low250'])
    df['to_ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10,min_periods=10).mean())
    df['to_ratio'] = df['turnover'] / df['to_ma10_prior']
    df['entry_open'] = g['open'].shift(-1)
    df['future_high60'] = g['high'].transform(lambda s: s.shift(-1).iloc[::-1].rolling(60,min_periods=60).max().iloc[::-1])
    df['mfe60'] = df['future_high60'] / df['entry_open'] - 1
    df['low_flag'] = df['pos250'].le(0.20)
    df['signal'] = df['low_flag'] & df['to_ratio'].ge(1.5)
    return df


def cooldown_old_opportunities(frame, cooldown=60):
    mask = frame['low_flag'] & frame['mfe60'].ge(0.50) & frame['mfe60'].notna()
    x = frame[mask].sort_values(['code','stock_idx']).copy()
    keep = []
    last = {}
    for r in x.itertuples(index=False):
        p = int(r.stock_idx)
        c = r.code
        ok = c not in last or p - last[c] > cooldown
        keep.append(ok)
        if ok:
            last[c] = p
    return x.loc[np.array(keep)].copy()


def process_threshold(df, threshold):
    old_rows = []
    leg_rows = []
    recall_rows = []

    for code, grp in df.groupby('code', sort=False):
        g = grp.sort_values('date').copy().reset_index(drop=True)
        if len(g) < 320:
            continue
        g['stock_idx'] = np.arange(len(g))
        piv = zigzag_pivots(g['close'].to_numpy(float), threshold)
        if not piv:
            continue

        pivot_idx = np.array([p[0] for p in piv], dtype=int)
        pivot_type = np.array([p[1] for p in piv], dtype=object)
        pivot_price = np.array([p[2] for p in piv], dtype=float)

        # 1) Decompose the old 60d-cooldown opportunity anchors.
        old = cooldown_old_opportunities(g, 60)
        for r in old.itertuples(index=False):
            i = int(r.stock_idx)
            j = np.searchsorted(pivot_idx, i, side='right') - 1
            if j < 0:
                cls = 'pre_structure'
                days_since_low = np.nan
                runup = np.nan
                prior_decline = np.nan
            elif pivot_type[j] == 'H':
                cls = 'down_leg_or_rebound'
                days_since_low = np.nan
                runup = np.nan
                prior_decline = np.nan
            else:
                li = pivot_idx[j]
                lp = pivot_price[j]
                days_since_low = i - li
                runup = r.close / lp - 1 if lp > 0 else np.nan
                # preceding structural high, if available
                prior_decline = np.nan
                if j >= 1 and pivot_type[j-1] == 'H':
                    hp = pivot_price[j-1]
                    prior_decline = lp / hp - 1 if hp > 0 else np.nan
                if days_since_low <= 5 and runup < 0.10:
                    cls = 'bottom_0_5d'
                elif days_since_low <= 20 and runup < 0.30:
                    cls = 'early_up_6_20d'
                else:
                    cls = 'continuation_up'
            old_rows.append(dict(
                threshold=threshold, code=code, date=r.date, close=r.close,
                class_old_opportunity=cls, days_since_structural_low=days_since_low,
                runup_from_structural_low=runup, prior_decline=prior_decline,
                mfe60=r.mfe60, to_ratio=r.to_ratio
            ))

        # 2) Build structural low -> up-leg targets.
        for j, (idx, typ, price) in enumerate(piv):
            if typ != 'L' or j == 0 or pivot_type[j-1] != 'H':
                continue
            low_i = int(idx)
            high_i = int(pivot_idx[j-1])
            prev_high = float(pivot_price[j-1])
            low_price = float(price)
            if low_i + 60 >= len(g) or low_i + 1 >= len(g):
                continue
            decline = low_price / prev_high - 1 if prev_high > 0 else np.nan
            low_pos = g.at[low_i, 'pos250']
            entry_open = g.at[low_i+1, 'open']
            future_high = g.loc[low_i+1:low_i+60, 'high'].max()
            mfe_from_low = future_high / entry_open - 1 if entry_open > 0 else np.nan
            if decline <= -0.30:
                decline_class = 'deep_>=30pct'
            elif decline <= -0.20:
                decline_class = 'medium_20_30pct'
            else:
                decline_class = 'shallow_15_20pct'

            target = bool(pd.notna(low_pos) and low_pos <= .20 and mfe_from_low >= .50)
            leg_rows.append(dict(
                threshold=threshold, code=code,
                prev_high_date=g.at[high_i,'date'], prev_high_price=prev_high,
                low_date=g.at[low_i,'date'], low_price=low_price,
                decline=decline, decline_class=decline_class,
                low_pos250=low_pos, mfe60_from_low=mfe_from_low,
                target_lowpos_mfe50=target
            ))

            if not target:
                continue

            # Signals around the structural low. A valid captured signal must itself
            # have MFE60>=50% from its T+1 open, matching the user's causal definition.
            lo = max(0, low_i - 20)
            hi = min(len(g)-1, low_i + 20)
            win = g.loc[lo:hi].copy()
            valid_sig = win[win['signal'] & win['mfe60'].ge(.50)].copy()

            def has(a, b):
                return bool(((valid_sig['stock_idx'] >= low_i + a) & (valid_sig['stock_idx'] <= low_i + b)).any())

            # union windows centered on the actual structural bottom
            cap_pre20_0 = has(-20, 0)
            cap_m5_p5 = has(-5, 5)
            cap_0_5 = has(0, 5)
            cap_0_10 = has(0, 10)
            cap_0_20 = has(0, 20)
            cap_m20_p5 = has(-20, 5)
            cap_m20_p10 = has(-20, 10)

            first_offset = np.nan
            first_runup = np.nan
            first_ratio = np.nan
            if len(valid_sig):
                valid_sig = valid_sig.sort_values('stock_idx')
                fr = valid_sig.iloc[0]
                first_offset = int(fr['stock_idx'] - low_i)
                first_runup = fr['close'] / low_price - 1 if low_price > 0 else np.nan
                first_ratio = fr['to_ratio']

            recall_rows.append(dict(
                threshold=threshold, code=code, low_date=g.at[low_i,'date'],
                decline=decline, decline_class=decline_class,
                low_pos250=low_pos, mfe60_from_low=mfe_from_low,
                cap_pre20_0=cap_pre20_0, cap_m5_p5=cap_m5_p5,
                cap_0_5=cap_0_5, cap_0_10=cap_0_10, cap_0_20=cap_0_20,
                cap_m20_p5=cap_m20_p5, cap_m20_p10=cap_m20_p10,
                first_signal_offset=first_offset,
                first_signal_runup_from_low=first_runup,
                first_signal_to_ratio=first_ratio
            ))

    return pd.DataFrame(old_rows), pd.DataFrame(leg_rows), pd.DataFrame(recall_rows)


def summarize_old(old):
    rows = []
    for th, x in old.groupby('threshold'):
        n = len(x)
        for cls, z in x.groupby('class_old_opportunity'):
            rows.append(dict(threshold=th, class_old_opportunity=cls, n=len(z), share=len(z)/n if n else np.nan,
                             median_days_since_low=z['days_since_structural_low'].median(),
                             median_runup=z['runup_from_structural_low'].median()))
    return pd.DataFrame(rows)


def summarize_legs(legs):
    rows = []
    for th, x in legs.groupby('threshold'):
        for cls, z in x.groupby('decline_class'):
            target = z['target_lowpos_mfe50']
            rows.append(dict(threshold=th, decline_class=cls, all_structural_lows=len(z),
                             target_lows=int(target.sum()), target_rate=float(target.mean()) if len(z) else np.nan))
    return pd.DataFrame(rows)


def summarize_recall(rec):
    rows = []
    caps = ['cap_pre20_0','cap_m5_p5','cap_0_5','cap_0_10','cap_0_20','cap_m20_p5','cap_m20_p10']
    for th, x in rec.groupby('threshold'):
        for cls_name, z in [('all_target_legs', x), ('deep_>=30pct', x[x.decline <= -.30])]:
            row = dict(threshold=th, subset=cls_name, n=len(z))
            for c in caps:
                row[c+'_recall'] = float(z[c].mean()) if len(z) else np.nan
                row[c+'_hits'] = int(z[c].sum()) if len(z) else 0
            captured = z[z['first_signal_offset'].notna()]
            row['captured_any_m20_p20'] = len(captured)
            row['median_first_signal_offset'] = captured['first_signal_offset'].median() if len(captured) else np.nan
            row['median_first_signal_runup'] = captured['first_signal_runup_from_low'].median() if len(captured) else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


df = rolling_features(load_data())
all_old = []
all_legs = []
all_rec = []
for th in THRESHOLDS:
    print(f'processing zigzag threshold={th:.0%}')
    old, legs, rec = process_threshold(df, th)
    all_old.append(old)
    all_legs.append(legs)
    all_rec.append(rec)

old = pd.concat(all_old, ignore_index=True) if all_old else pd.DataFrame()
legs = pd.concat(all_legs, ignore_index=True) if all_legs else pd.DataFrame()
rec = pd.concat(all_rec, ignore_index=True) if all_rec else pd.DataFrame()

old_summary = summarize_old(old)
leg_summary = summarize_legs(legs)
rec_summary = summarize_recall(rec)

old_summary.to_csv(OUT/'segment_old_opportunity_decomposition.csv', index=False)
leg_summary.to_csv(OUT/'segment_structural_leg_summary.csv', index=False)
rec_summary.to_csv(OUT/'segment_structural_recall_summary.csv', index=False)
rec.to_csv(OUT/'segment_structural_target_events.csv', index=False)

print('\n--- OLD 9051-LIKE OPPORTUNITY DECOMPOSITION ---')
print(old_summary.to_string(index=False))
print('\n--- STRUCTURAL LEG SUMMARY ---')
print(leg_summary.to_string(index=False))
print('\n--- STRUCTURAL TARGET RECALL ---')
print(rec_summary.to_string(index=False))

meta = {
    'zigzag_thresholds': THRESHOLDS,
    'target': 'structural pivot low with pos250<=20% and max high in next 60d / next-day open - 1 >=50%',
    'deep_decline': 'preceding structural high to structural low <= -30%',
    'signal': 'pos250<=20% and turnover_t/prior10d_mean>=1.5',
    'capture_rule': 'signal must itself have MFE60>=50% from signal T+1 open',
    'note': 'zigzag is retrospective label construction only; no tradable lookahead is used in signal definition'
}
(OUT/'segment_structure_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2))
