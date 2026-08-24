import glob
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
    elif lc in ('open','high','low','close'): rename[c] = lc
    elif lc in ('turn','turnover','turnover_rate'): rename[c] = 'turnover'
df = df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
df['date'] = pd.to_datetime(df['date'])
df['code'] = df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
df = df.dropna().sort_values(['code','date']).reset_index(drop=True)
g = df.groupby('code', group_keys=False)

# Real-time observables.
df['low250'] = g['low'].transform(lambda s: s.rolling(250,min_periods=250).min())
df['high250'] = g['high'].transform(lambda s: s.rolling(250,min_periods=250).max())
df['pos250'] = (df['close']-df['low250'])/(df['high250']-df['low250'])
df['ma10_prior'] = g['turnover'].transform(lambda s: s.shift(1).rolling(10,min_periods=10).mean())
df['r1'] = df['turnover']/df['ma10_prior']
mean3 = g['turnover'].transform(lambda s: s.rolling(3,min_periods=3).mean())
base10_before3 = g['turnover'].transform(lambda s: s.shift(3).rolling(10,min_periods=10).mean())
df['r3_10'] = mean3/base10_before3
mean5 = g['turnover'].transform(lambda s: s.rolling(5,min_periods=5).mean())
base20_before5 = g['turnover'].transform(lambda s: s.shift(5).rolling(20,min_periods=20).mean())
df['r5_20'] = mean5/base20_before5
for thr in [1.15,1.20,1.25]:
    name = f'cnt5_{str(thr).replace(".","p")}'
    flag = (df['r1'] >= thr).astype(float)
    df[name] = flag.groupby(df['code']).transform(lambda s: s.rolling(5,min_periods=5).sum())

# Label only: from signal T+1 open, max high during T+1..T+60.
def fwd60(s):
    z = s.shift(-1).iloc[::-1].rolling(60,min_periods=60).max().iloc[::-1]
    z.index = s.index
    return z

df['fwd_high60'] = g['high'].transform(fwd60)
df['next_open'] = g['open'].shift(-1)
df['maxup60_sig'] = df['fwd_high60']/df['next_open'] - 1.0
df['stock_idx'] = g.cumcount()

# Structural positives built by the previous diagnostic.
t = pd.read_csv(OUT/'segment_structural_target_events.csv')
t = t[(t['threshold'].round(2)==0.15) & (t['decline_class']=='deep_>=30pct')].copy()
t['low_date'] = pd.to_datetime(t['low_date'])
t['code'] = t['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
assert len(t)==5253, len(t)
idx_map = df.set_index(['code','date'])['stock_idx']
frames = {c:x for c,x in df.groupby('code',sort=False)}

# Mutually exclusive decomposition on bottom-20 .. bottom.
records=[]
for ev in t.itertuples(index=False):
    try: p = int(idx_map.loc[(ev.code,ev.low_date)])
    except KeyError: continue
    x = frames[ev.code]
    w = x[(x.stock_idx>=p-20)&(x.stock_idx<=p)].copy()
    if w.empty: continue
    w['offset'] = w.stock_idx-p
    raw = (w.r1>=1.5).fillna(False)
    eff = raw & (w.maxup60_sig>=0.5).fillna(False)
    loweff = eff & (w.pos250<=0.20).fillna(False)
    if loweff.any(): cls='HIT'
    elif eff.any(): cls='M2_ABOVE_BAND'
    elif raw.any(): cls='M1_TOO_EARLY'
    else: cls='M3_NO_1P5_SHOCK'
    rec={'code':ev.code,'low_date':ev.low_date,'class':cls,
         'max_r1':w.r1.max(),'max_r3_10':w.r3_10.max(),'max_r5_20':w.r5_20.max(),
         'max_cnt5_1p15':w.cnt5_1p15.max(),'max_cnt5_1p2':w.cnt5_1p2.max(),'max_cnt5_1p25':w.cnt5_1p25.max()}
    if raw.any():
        q=w.loc[raw].sort_values('stock_idx').iloc[-1]
        rec.update(latest_raw_offset=int(q.offset),latest_raw_pos250=q.pos250,latest_raw_maxup60=q.maxup60_sig)
    if eff.any():
        q=w.loc[eff].sort_values('pos250').iloc[0]
        rec.update(best_eff_pos250=q.pos250,best_eff_offset=int(q.offset),best_eff_maxup60=q.maxup60_sig)
    records.append(rec)
evdf=pd.DataFrame(records)
evdf.to_csv(OUT/'m123_v2_events.csv',index=False)

order=['HIT','M1_TOO_EARLY','M2_ABOVE_BAND','M3_NO_1P5_SHOCK']
cs=evdf['class'].value_counts().reindex(order,fill_value=0).rename_axis('class').reset_index(name='n')
cs['share_all']=cs.n/len(evdf)
miss_n=int((evdf['class']!='HIT').sum())
cs['share_miss']=np.where(cs['class']=='HIT',np.nan,cs.n/miss_n)
cs.to_csv(OUT/'m123_v2_class_summary.csv',index=False)

# M2 position distribution and position-cap sensitivity.
m2=evdf[evdf['class']=='M2_ABOVE_BAND'].copy()
def band(v):
    if pd.isna(v): return 'NA'
    if v<=.25: return '20-25%'
    if v<=.30: return '25-30%'
    if v<=.40: return '30-40%'
    return '>40%'
m2['band']=m2.best_eff_pos250.map(band) if len(m2) else []
bands=m2['band'].value_counts().reindex(['20-25%','25-30%','30-40%','>40%','NA'],fill_value=0).rename_axis('band').reset_index(name='n') if len(m2) else pd.DataFrame({'band':[],'n':[]})
if len(bands): bands['share_M2']=bands.n/len(m2)
bands.to_csv(OUT/'m123_v2_m2_bands.csv',index=False)

caprows=[]
for cap in [.20,.25,.30,.40,1.00]:
    hits=0
    for ev in t.itertuples(index=False):
        try: p=int(idx_map.loc[(ev.code,ev.low_date)])
        except KeyError: continue
        w=frames[ev.code]
        w=w[(w.stock_idx>=p-20)&(w.stock_idx<=p)]
        m=(w.r1>=1.5)&(w.pos250<=cap)&(w.maxup60_sig>=.5)
        hits += int(m.fillna(False).any())
    caprows.append({'pos_cap':cap,'hits':hits,'recall':hits/len(t)})
capdf=pd.DataFrame(caprows); capdf.to_csv(OUT/'m123_v2_poscap.csv',index=False)

# M1 timing profile.
m1=evdf[evdf['class']=='M1_TOO_EARLY'].copy()
def ob(v):
    if pd.isna(v): return 'NA'
    if v<=-16:return '-20..-16'
    if v<=-11:return '-15..-11'
    if v<=-6:return '-10..-6'
    if v<=-3:return '-5..-3'
    if v<=-1:return '-2..-1'
    return '0'
m1['offset_band']=m1.latest_raw_offset.map(ob) if len(m1) else []
off=m1['offset_band'].value_counts().reindex(['-20..-16','-15..-11','-10..-6','-5..-3','-2..-1','0','NA'],fill_value=0).rename_axis('offset_band').reset_index(name='n') if len(m1) else pd.DataFrame({'offset_band':[],'n':[]})
if len(off): off['share_M1']=off.n/len(m1)
off.to_csv(OUT/'m123_v2_m1_offsets.csv',index=False)

# M3 only: gradual channels, with the same strict causal requirements.
rules={}
for th in [1.10,1.15,1.20,1.25,1.30]: rules[f'3d10_ge{th:.2f}']=lambda x,t=th:x.r3_10>=t
for th in [1.05,1.10,1.15,1.20,1.25]: rules[f'5d20_ge{th:.2f}']=lambda x,t=th:x.r5_20>=t
for th in [1.15,1.20,1.25]:
    col=f'cnt5_{str(th).replace(".","p")}'
    for n in [2,3,4]: rules[f'count5_r1ge{th:.2f}_ge{n}']=lambda x,c=col,n=n:x[c]>=n
base_global=int(((df.pos250<=.20)&(df.r1>=1.5)).sum())
global_n={k:int(((df.pos250<=.20)&fn(df).fillna(False)).sum()) for k,fn in rules.items()}
m3keys={(r.code,pd.Timestamp(r.low_date)) for r in evdf[evdf['class']=='M3_NO_1P5_SHOCK'].itertuples(index=False)}
grows=[]
for name,fn in rules.items():
    gh=0
    for code,ld in m3keys:
        try:p=int(idx_map.loc[(code,ld)])
        except KeyError:continue
        w=frames[code]; w=w[(w.stock_idx>=p-20)&(w.stock_idx<=p)]
        m=fn(w).fillna(False)&(w.pos250<=.20)&(w.maxup60_sig>=.5)
        gh += int(m.any())
    union=int((cs.loc[cs['class']=='HIT','n'].iloc[0] if (cs['class']=='HIT').any() else 0)+gh)
    grows.append({'rule':name,'m3_n':len(m3keys),'m3_hits':gh,'m3_recall':gh/len(m3keys) if m3keys else np.nan,
                  'incremental_pp_all':gh/len(t),'union_recall_all':union/len(t),
                  'global_low_signal_days':global_n[name],'rule_signal_ratio_vs_R1':global_n[name]/base_global})
gdf=pd.DataFrame(grows).sort_values(['union_recall_all','rule_signal_ratio_vs_R1'],ascending=[False,True])
gdf.to_csv(OUT/'m123_v2_m3_gradual.csv',index=False)

print('--- CLASS SUMMARY ---')
print(cs.to_string(index=False))
print('\n--- M2 POSITION BANDS ---')
print(bands.to_string(index=False))
print('\n--- POSITION CAP SENSITIVITY ---')
print(capdf.to_string(index=False))
print('\n--- M1 LATEST RAW SHOCK OFFSETS ---')
print(off.to_string(index=False))
print('\n--- M3 GRADUAL TOP ---')
print(gdf.head(15).to_string(index=False))
