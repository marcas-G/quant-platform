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

# Core real-time features. Every denominator excludes the days in its numerator.
df['low250']=g['low'].transform(lambda s:s.rolling(250,min_periods=250).min())
df['high250']=g['high'].transform(lambda s:s.rolling(250,min_periods=250).max())
df['pos250']=(df['close']-df['low250'])/(df['high250']-df['low250'])
df['ma10_prior']=g['turnover'].transform(lambda s:s.shift(1).rolling(10,min_periods=10).mean())
df['r1']=df['turnover']/df['ma10_prior']
# gradual channels
mean3=g['turnover'].transform(lambda s:s.rolling(3,min_periods=3).mean())
base10_before3=g['turnover'].transform(lambda s:s.shift(3).rolling(10,min_periods=10).mean())
df['r3_10']=mean3/base10_before3
mean5=g['turnover'].transform(lambda s:s.rolling(5,min_periods=5).mean())
base20_before5=g['turnover'].transform(lambda s:s.shift(5).rolling(20,min_periods=20).mean())
df['r5_20']=mean5/base20_before5
# persistence counts based on daily r1
for thr in [1.15,1.20,1.25]:
    col=f'cnt5_{str(thr).replace(".","p")}'
    flag=(df['r1']>=thr).astype(float)
    df[col]=flag.groupby(df['code']).transform(lambda s:s.rolling(5,min_periods=5).sum())

# Use previously generated 15% ZigZag target events.
target_path=OUT/'segment_structural_target_events.csv'
if not target_path.exists():
    raise SystemExit('missing segment_structural_target_events.csv; run segment_structure_diagnostic.py first')
targets=pd.read_csv(target_path)
targets=targets[(targets['threshold'].round(2)==0.15)&(targets['decline_class']=='deep_>=30pct')].copy()
targets['low_date']=pd.to_datetime(targets['low_date'])
targets['code']=targets['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
assert len(targets)==5253, len(targets)

# Map each target bottom to its stock-local row index.
df['stock_idx']=g.cumcount()
idx_map=df.set_index(['code','date'])['stock_idx']

# Rule grid. R1 stays frozen; others are possible gradual expansion channels.
rules={
    'R1_1d10_ge1p50': lambda x: x['r1']>=1.50,
}
for thr in [1.15,1.20,1.25,1.30,1.35]:
    rules[f'R2_3d10_ge{str(thr).replace(".","p")}']=lambda x,t=thr: x['r3_10']>=t
for thr in [1.10,1.15,1.20,1.25,1.30]:
    rules[f'R3_5d20_ge{str(thr).replace(".","p")}']=lambda x,t=thr: x['r5_20']>=t
for base_thr in [1.15,1.20,1.25]:
    c=f'cnt5_{str(base_thr).replace(".","p")}'
    for n in [2,3,4]:
        rules[f'R4_count5_r1ge{str(base_thr).replace(".","p")}_ge{n}']=lambda x,c=c,n=n: x[c]>=n

# Precompute global low-day signal counts to quantify candidate-pool inflation.
low=df['pos250'].le(0.20)
global_counts={}
for name,fn in rules.items():
    m=low & fn(df).fillna(False)
    global_counts[name]=int(m.sum())
r1_global=global_counts['R1_1d10_ge1p50']

# Evaluate event recall in two diagnostic windows around the retrospective bottom.
windows={'pre20_0':(-20,0),'pre20_p5':(-20,5)}
rows=[]
miss_feature_rows=[]
# collect per-event maxima for describing R1 misses
for ev in targets.itertuples(index=False):
    key=(ev.code,ev.low_date)
    try:
        p=int(idx_map.loc[key])
    except KeyError:
        continue
    grp=df[df['code'].eq(ev.code)]
    w=grp[(grp['stock_idx']>=p-20)&(grp['stock_idx']<=p+5)].copy()
    pre=w[w['stock_idx']<=p]
    if pre.empty:
        continue
    miss_feature_rows.append({
        'code':ev.code,'low_date':ev.low_date,
        'max_r1_pre20_0':pre['r1'].max(),
        'max_r3_10_pre20_0':pre['r3_10'].max(),
        'max_r5_20_pre20_0':pre['r5_20'].max(),
        'max_cnt5_1p15_pre20_0':pre['cnt5_1p15'].max(),
        'max_cnt5_1p20_pre20_0':pre['cnt5_1p20'].max(),
        'r1_hit_pre20_0':bool((pre['r1']>=1.5).any()),
    })

missfeat=pd.DataFrame(miss_feature_rows)
missfeat.to_csv(OUT/'gradual_miss_event_features.csv',index=False)

# event recall calculation
# store R1 hit sets for incremental recall
event_hits={w:{} for w in windows}
for wname,(a,b) in windows.items():
    for name in rules:
        event_hits[wname][name]=[]

for ev in targets.itertuples(index=False):
    key=(ev.code,ev.low_date)
    try:
        p=int(idx_map.loc[key])
    except KeyError:
        continue
    grp=df[df['code'].eq(ev.code)]
    for wname,(a,b) in windows.items():
        w=grp[(grp['stock_idx']>=p+a)&(grp['stock_idx']<=p+b)]
        for name,fn in rules.items():
            event_hits[wname][name].append(bool(fn(w).fillna(False).any()))

for wname in windows:
    r1=np.array(event_hits[wname]['R1_1d10_ge1p50'],dtype=bool)
    n=len(r1)
    for name in rules:
        h=np.array(event_hits[wname][name],dtype=bool)
        union=r1|h
        rows.append({
            'window':wname,
            'rule':name,
            'n_targets':n,
            'rule_hits':int(h.sum()),
            'rule_recall':h.mean(),
            'r1_hits':int(r1.sum()),
            'r1_recall':r1.mean(),
            'incremental_hits_over_r1':int((~r1 & h).sum()),
            'incremental_recall_over_r1':float((~r1 & h).sum()/n),
            'union_hits':int(union.sum()),
            'union_recall':union.mean(),
            'global_low_signal_days':global_counts[name],
            'global_signal_inflation_vs_r1':global_counts[name]/r1_global if r1_global else np.nan,
        })
res=pd.DataFrame(rows)
res.to_csv(OUT/'gradual_recall_grid.csv',index=False)

# summarize miss distributions for the strict pre-bottom window
miss=missfeat[~missfeat['r1_hit_pre20_0']]
hit=missfeat[missfeat['r1_hit_pre20_0']]
summary=[]
for grpname,sub in [('R1_hit',hit),('R1_miss',miss)]:
    for c in ['max_r1_pre20_0','max_r3_10_pre20_0','max_r5_20_pre20_0','max_cnt5_1p15_pre20_0','max_cnt5_1p20_pre20_0']:
        s=pd.to_numeric(sub[c],errors='coerce').dropna()
        summary.append({'group':grpname,'feature':c,'n':len(s),'mean':s.mean(),'median':s.median(),'p25':s.quantile(.25),'p75':s.quantile(.75),'p90':s.quantile(.90)})
pd.DataFrame(summary).to_csv(OUT/'gradual_miss_feature_summary.csv',index=False)

# Pareto-like ranking: highest union recall with modest candidate inflation, on pre20_0.
show=res[(res.window=='pre20_0') & (res.rule!='R1_1d10_ge1p50')].copy()
show=show.sort_values(['union_recall','global_signal_inflation_vs_r1'],ascending=[False,True])
print('--- R1 MISS FEATURE SUMMARY ---')
print(pd.DataFrame(summary).to_string(index=False))
print('\n--- TOP GRADUAL RECALL CANDIDATES: PRE20..BOTTOM ---')
print(show[['rule','rule_recall','incremental_recall_over_r1','union_recall','global_signal_inflation_vs_r1']].head(20).to_string(index=False))
print('\n--- TOP GRADUAL RECALL CANDIDATES: PRE20..+5 ---')
show2=res[(res.window=='pre20_p5') & (res.rule!='R1_1d10_ge1p50')].sort_values(['union_recall','global_signal_inflation_vs_r1'],ascending=[False,True])
print(show2[['rule','rule_recall','incremental_recall_over_r1','union_recall','global_signal_inflation_vs_r1']].head(20).to_string(index=False))
