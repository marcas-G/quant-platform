import numpy as np
import pandas as pd

# Importing re-runs the strict pre-entry experiment and exposes epi/train/val.
import precision_preentry_diagnostic as m

OUT = m.OUT
epi = m.epi.copy()
train = epi[epi['date'] <= m.TRAIN_END].copy()
val = epi[epi['date'] >= m.VAL_START].copy()

# -----------------------------------------------------------------------------
# Year-by-year baseline and fixed TRAIN-DERIVED rules.
# -----------------------------------------------------------------------------
q = {}
q['dd120_low20'] = float(train['dd_from_high120'].quantile(0.20))
q['dd120_low30'] = float(train['dd_from_high120'].quantile(0.30))
q['dd120_low40'] = float(train['dd_from_high120'].quantile(0.40))
q['dd120_low50'] = float(train['dd_from_high120'].quantile(0.50))
q['vol20_high20'] = float(train['vol20_prior'].quantile(0.80))
q['vol20_high30'] = float(train['vol20_prior'].quantile(0.70))
q['vol20_high40'] = float(train['vol20_prior'].quantile(0.60))
q['vol20_high50'] = float(train['vol20_prior'].quantile(0.50))
q['vol10_high20'] = float(train['vol10_prior'].quantile(0.80))

rules = {
    'BASE': lambda x: pd.Series(True, index=x.index),
    'DD120_L20': lambda x: x['dd_from_high120'] <= q['dd120_low20'],
    'VOL20_H20': lambda x: x['vol20_prior'] >= q['vol20_high20'],
    'DD120_L20_AND_VOL20_H20': lambda x: (x['dd_from_high120'] <= q['dd120_low20']) & (x['vol20_prior'] >= q['vol20_high20']),
    'DD120_L20_AND_VOL10_H20': lambda x: (x['dd_from_high120'] <= q['dd120_low20']) & (x['vol10_prior'] >= q['vol10_high20']),
}

year_rows = []
for year, y in epi.groupby(epi['date'].dt.year):
    base_pos = int(y['positive'].sum())
    for name, fn in rules.items():
        z = y[fn(y).fillna(False)]
        pos = int(z['positive'].sum())
        year_rows.append({
            'year': int(year), 'rule': name, 'n': len(z), 'positives': pos,
            'precision': pos / len(z) if len(z) else np.nan,
            'positive_retention_vs_year_base': pos / base_pos if base_pos else np.nan,
            'signal_retention_vs_year_base': len(z) / len(y) if len(y) else np.nan,
        })
yr = pd.DataFrame(year_rows)
yr.to_csv(OUT / 'precision_stage1_year_stability.csv', index=False)

# -----------------------------------------------------------------------------
# DD120 x VOL20 PRIOR grid. Thresholds come ONLY from training quantiles.
# Evaluate aggregate 2024+ validation Precision vs positive retention.
# -----------------------------------------------------------------------------
val_pos = int(val['positive'].sum())
val_n = len(val)
grid_rows = []
for dd_frac in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 1.00]:
    dd_thr = np.inf if dd_frac == 1.00 else float(train['dd_from_high120'].quantile(dd_frac))
    for vol_frac in [0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 1.00]:
        vol_thr = -np.inf if vol_frac == 1.00 else float(train['vol20_prior'].quantile(1-vol_frac))
        mask = (val['dd_from_high120'] <= dd_thr) & (val['vol20_prior'] >= vol_thr)
        z = val[mask.fillna(False)]
        pos = int(z['positive'].sum())
        grid_rows.append({
            'dd_train_low_frac': dd_frac,
            'vol_train_high_frac': vol_frac,
            'dd_threshold': dd_thr,
            'vol20_threshold': vol_thr,
            'val_n': len(z),
            'val_positives': pos,
            'val_precision': pos/len(z) if len(z) else np.nan,
            'val_positive_retention': pos/val_pos if val_pos else np.nan,
            'val_signal_retention': len(z)/val_n if val_n else np.nan,
        })
grid = pd.DataFrame(grid_rows)
grid.to_csv(OUT / 'precision_stage1_dd_vol_grid.csv', index=False)

# Pareto frontier: no point dominated in both precision and positive retention.
valid = grid.dropna(subset=['val_precision','val_positive_retention']).copy()
pareto = []
for i, r in valid.iterrows():
    dominated = ((valid['val_precision'] >= r['val_precision']) &
                 (valid['val_positive_retention'] >= r['val_positive_retention']) &
                 ((valid['val_precision'] > r['val_precision']) | (valid['val_positive_retention'] > r['val_positive_retention']))).any()
    if not dominated:
        pareto.append(r)
pareto = pd.DataFrame(pareto).sort_values('val_positive_retention')
pareto.to_csv(OUT / 'precision_stage1_dd_vol_pareto.csv', index=False)

print('\n--- YEAR STABILITY ---')
print(yr.to_string(index=False))
print('\n--- DD120 x VOL20 PARETO ---')
print(pareto[['dd_train_low_frac','vol_train_high_frac','dd_threshold','vol20_threshold','val_n','val_precision','val_positive_retention','val_signal_retention']].to_string(index=False))
