import glob
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path('bt_out'); OUT.mkdir(exist_ok=True)
files=sorted(glob.glob('bt_data/kline_*.parquet'))
df=pd.concat([pd.read_parquet(p) for p in files],ignore_index=True)
rename={}
for c in df.columns:
    lc=str(c).lower()
    if lc in ('date','trade_date'): rename[c]='date'
    elif lc in ('code','ts_code','symbol'): rename[c]='code'
    elif lc in ('open','high','low','close'): rename[c]=lc
    elif lc in ('turn','turnover','turnover_rate'): rename[c]='turnover'
df=df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
df['date']=pd.to_datetime(df['date'])
df['code']=df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
df=df.dropna().sort_values(['code','date']).reset_index(drop=True)
g=df.groupby('code',group_keys=False)

# Real-time state features.
df['low250']=g['low'].transform(lambda s:s.rolling(250,min_periods=250).min())
df['high250']=g['high'].transform(lambda s:s.rolling(250,min_periods=250).max())
df['pos250']=(df['close']-df['low250'])/(df['high250']-df['low250'])
df['ma10_prior']=g['turnover'].transform(lambda s:s.shift(1).rolling(10,min_periods=10).mean())
df['r1']=df['turnover']/df['ma10_prior']
mean3=g['turnover'].transform(lambda s:s.rolling(3,min_periods=3).mean())
base10_before3=g['turnover'].transform(lambda s:s.shift(3).rolling(10,min_periods=10).mean())
df['r3_10']=mean3/base10_before3
mean5=g['turnover'].transform(lambda s:s.rolling(5,min_periods=5).mean())
base20_before5=g['turnover'].transform(lambda s:s.shift(5).rolling(20,min_periods=20).mean())
df['r5_20']=mean5/base20_before5
for thr in [1.15,1.20,1.25]:
    col=f'cnt5_{str(thr).replace(".","p")}'
    flag=(df['r1']>=thr).astype(float)
    df[col]=flag.groupby(df['code']).transform(lambda s:s.rolling(5,min_periods=5).sum())

# User's required causal outcome: from the signal's NEXT-DAY open, future 60d max high >= +50%.
df['entry_open']=g['open'].shift(-1)
df['future_high60']=g['high'].transform(lambda s:s.shift(-1).iloc[::-1].rolling(60,min_periods=60).max().iloc[::-1])
df['mfe60_from_signal']=df['future_high60']/df['entry_open']-1

target_path=OUT/'segment_structural_target_events.csv'
if not target_path.exists():
    raise SystemExit('missing segment_structural_target_events.csv; run segment_structure_diagnostic.py first')
targets=pd.read_csv(target_path)
targets=targets[(targets['threshold'].round(2)==0.15)&(targets['decline_class']=='deep_>=30pct')].copy()
targets['low_date']=pd.to_datetime(targets['low_date'])
targets['code']=targets['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
assert len(targets)==5253, len(targets)

df['stock_idx']=g.cumcount()
idx_map=df.set_index(['code','date'])['stock_idx']
stock_frames={c:x for c,x in df.groupby('code',sort=False)}

rules={'R1_1d10_ge1p50': lambda x: x['r1']>=1.50}
for thr in [1.15,1.20,1.25,1.30,1.35]:
    rules[f'R2_3d10_ge{str(thr).replace(".","p")}']=lambda x,t=thr: x['r3_10']>=t
for thr in [1.10,1.15,1.20,1.25,1.30]:
    rules[f'R3_5d20_ge{str(thr).replace(".","p")}']=lambda x,t=thr: x['r5_20']>=t
for base_thr in [1.15,1.20,1.25]:
    c=f'cnt5_{str(base_thr).replace(".","p")}'
    for n in [2,3,4]:
        rules[f'R4_count5_r1ge{str(base_thr).replace(".","p")}_ge{n}']=lambda x,c=c,n=n: x[c]>=n

# Raw candidate inflation is measured WITHOUT future information.
low=df['pos250'].le(0.20)
global_counts={name:int((low & fn(df).fillna(False)).sum()) for name,fn in rules.items()}
r1_global=global_counts['R1_1d10_ge1p50']

def raw_mask(frame, name):
    return frame['pos250'].le(0.20) & rules[name](frame).fillna(False)

def effective_mask(frame, name):
    return raw_mask(frame,name) & frame['mfe60_from_signal'].ge(0.50)

windows={'pre20_0':(-20,0),'pre20_p5':(-20,5)}
raw_hits={w:{name:[] for name in rules} for w in windows}
eff_hits={w:{name:[] for name in rules} for w in windows}
miss_rows=[]

for ev in targets.itertuples(index=False):
    key=(ev.code,ev.low_date)
    try:
        p=int(idx_map.loc[key])
    except KeyError:
        continue
    grp=stock_frames[ev.code]
    pre=grp[(grp['stock_idx']>=p-20)&(grp['stock_idx']<=p)]
    if pre.empty:
        continue
    r1_raw=raw_mask(pre,'R1_1d10_ge1p50')
    r1_eff=effective_mask(pre,'R1_1d10_ge1p50')
    miss_rows.append({
        'code':ev.code,'low_date':ev.low_date,
        'raw_r1_hit_pre20_0':bool(r1_raw.any()),
        'effective_r1_hit_pre20_0':bool(r1_eff.any()),
        'max_r1_pre20_0':pre['r1'].max(),
        'max_r3_10_pre20_0':pre['r3_10'].max(),
        'max_r5_20_pre20_0':pre['r5_20'].max(),
        'max_cnt5_1p15_pre20_0':pre['cnt5_1p15'].max(),
        'max_cnt5_1p2_pre20_0':pre['cnt5_1p2'].max(),
    })
    for wname,(a,b) in windows.items():
        w=grp[(grp['stock_idx']>=p+a)&(grp['stock_idx']<=p+b)]
        for name in rules:
            raw_hits[wname][name].append(bool(raw_mask(w,name).any()))
            eff_hits[wname][name].append(bool(effective_mask(w,name).any()))

missfeat=pd.DataFrame(miss_rows)
missfeat.to_csv(OUT/'gradual_miss_event_features_corrected.csv',index=False)

rows=[]
for wname in windows:
    r1_raw=np.array(raw_hits[wname]['R1_1d10_ge1p50'],dtype=bool)
    r1_eff=np.array(eff_hits[wname]['R1_1d10_ge1p50'],dtype=bool)
    n=len(r1_eff)
    for name in rules:
        h_raw=np.array(raw_hits[wname][name],dtype=bool)
        h_eff=np.array(eff_hits[wname][name],dtype=bool)
        union_eff=r1_eff|h_eff
        rows.append({
            'window':wname,'rule':name,'n_targets':n,
            'raw_rule_recall':h_raw.mean(),
            'effective_rule_recall':h_eff.mean(),
            'r1_raw_recall':r1_raw.mean(),
            'r1_effective_recall':r1_eff.mean(),
            'incremental_effective_hits_over_r1':int((~r1_eff & h_eff).sum()),
            'incremental_effective_recall_over_r1':float((~r1_eff & h_eff).sum()/n),
            'union_effective_hits':int(union_eff.sum()),
            'union_effective_recall':union_eff.mean(),
            'global_low_signal_days':global_counts[name],
            'global_signal_inflation_vs_r1':global_counts[name]/r1_global if r1_global else np.nan,
        })
res=pd.DataFrame(rows)
res.to_csv(OUT/'gradual_recall_grid_corrected.csv',index=False)

# Decompose the R1 effective misses: no shock vs shock exists but is too early/high to preserve +50% future MFE.
eff_miss=missfeat[~missfeat['effective_r1_hit_pre20_0']]
miss_decomp=pd.Series({
    'total_targets':len(missfeat),
    'effective_r1_hits':int(missfeat['effective_r1_hit_pre20_0'].sum()),
    'effective_r1_misses':len(eff_miss),
    'miss_with_raw_r1_present':int(eff_miss['raw_r1_hit_pre20_0'].sum()),
    'miss_with_no_raw_r1':int((~eff_miss['raw_r1_hit_pre20_0']).sum()),
})
miss_decomp.to_csv(OUT/'gradual_r1_miss_decomposition.csv',header=['value'])

summary=[]
for grpname,sub in [('effective_R1_hit',missfeat[missfeat['effective_r1_hit_pre20_0']]),('effective_R1_miss',eff_miss),('true_no_raw_R1',eff_miss[~eff_miss['raw_r1_hit_pre20_0']])]:
    for c in ['max_r1_pre20_0','max_r3_10_pre20_0','max_r5_20_pre20_0','max_cnt5_1p15_pre20_0','max_cnt5_1p2_pre20_0']:
        s=pd.to_numeric(sub[c],errors='coerce').dropna()
        summary.append({'group':grpname,'feature':c,'n':len(s),'mean':s.mean(),'median':s.median(),'p25':s.quantile(.25),'p75':s.quantile(.75),'p90':s.quantile(.90)})
pd.DataFrame(summary).to_csv(OUT/'gradual_miss_feature_summary_corrected.csv',index=False)

print('--- CORRECTED R1 MISS DECOMPOSITION ---')
print(miss_decomp.to_string())
print('\n--- CORRECTED MISS FEATURE SUMMARY ---')
print(pd.DataFrame(summary).to_string(index=False))
for wname in ['pre20_0','pre20_p5']:
    show=res[(res.window==wname)&(res.rule!='R1_1d10_ge1p50')].sort_values(['union_effective_recall','global_signal_inflation_vs_r1'],ascending=[False,True])
    print(f'\n--- CORRECTED TOP GRADUAL CANDIDATES: {wname} ---')
    print(show[['rule','raw_rule_recall','effective_rule_recall','incremental_effective_recall_over_r1','union_effective_recall','global_signal_inflation_vs_r1']].head(20).to_string(index=False))
# trigger marker corrected
