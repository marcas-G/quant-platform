import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT=Path('bt_out'); OUT.mkdir(exist_ok=True)
files=sorted(glob.glob('bt_data/kline_*.parquet'))
df=pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
rename={}
for c in df.columns:
    lc=str(c).lower()
    if lc in ('date','trade_date'): rename[c]='date'
    elif lc in ('code','ts_code','symbol'): rename[c]='code'
    elif lc=='open': rename[c]='open'
    elif lc=='high': rename[c]='high'
    elif lc=='low': rename[c]='low'
    elif lc=='close': rename[c]='close'
    elif lc in ('turn','turnover','turnover_rate'): rename[c]='turnover'
df=df.rename(columns=rename)[['date','code','open','high','low','close','turnover']].copy()
df['date']=pd.to_datetime(df['date'])
df['code']=df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c]=pd.to_numeric(df[c],errors='coerce')
df=df.dropna().sort_values(['code','date']).reset_index(drop=True)
g=df.groupby('code',group_keys=False)

df['low250']=g['low'].transform(lambda s:s.rolling(250,min_periods=250).min())
df['high250']=g['high'].transform(lambda s:s.rolling(250,min_periods=250).max())
df['pos250']=(df['close']-df['low250'])/(df['high250']-df['low250'])
df['to_ma10_prior']=g['turnover'].transform(lambda s:s.shift(1).rolling(10,min_periods=10).mean())
df['to_ratio']=df['turnover']/df['to_ma10_prior']
df['entry_open']=g['open'].shift(-1)

df['future_high60']=g['high'].transform(lambda s:s.shift(-1).iloc[::-1].rolling(60,min_periods=60).max().iloc[::-1])
df['mfe60']=df['future_high60']/df['entry_open']-1

base=df[df['entry_open'].notna() & df['pos250'].notna() & df['to_ratio'].notna()].copy()
base['stock_idx']=base.groupby('code').cumcount()
base['low']=base['pos250'].le(.20)
base['signal']=base['low'] & base['to_ratio'].ge(1.5)

sig_idx={c:grp['stock_idx'].to_numpy() for c,grp in base[base.signal].groupby('code')}

def cooldown_positive(frame, mask, cooldown=60):
    x=frame[mask].sort_values(['code','stock_idx']).copy()
    keep=[]; last={}
    for r in x.itertuples(index=False):
        c=r.code; p=int(r.stock_idx)
        ok=c not in last or p-last[c]>cooldown
        keep.append(ok)
        if ok: last[c]=p
    return x.loc[np.array(keep)].copy()

def captured_within(row, days):
    arr=sig_idx.get(row.code)
    if arr is None or len(arr)==0:
        return False
    p=int(row.stock_idx)
    j=np.searchsorted(arr,p,side='left')
    return j<len(arr) and arr[j] <= p+days

rows=[]
valid=base['low'] & base['mfe60'].notna()
for thr in [0.30,0.40,0.50,0.60]:
    positive=valid & base['mfe60'].ge(thr)
    n_pos=int(positive.sum())
    n_hit=int((positive & base['signal']).sum())
    sig_valid=base['signal'] & base['mfe60'].notna()
    precision=float((base.loc[sig_valid,'mfe60']>=thr).mean()) if sig_valid.any() else np.nan
    opp=cooldown_positive(base,positive,60)
    rec={}; cap={}
    for days in [0,5,10,20]:
        cap[days]=int(sum(captured_within(r,days) for r in opp.itertuples(index=False)))
        rec[days]=cap[days]/len(opp) if len(opp) else np.nan
    rows.append(dict(metric='mfe60', threshold=thr,
        positive_low_days=n_pos, signal_hits_same_day=n_hit,
        recall_same_day=n_hit/n_pos if n_pos else np.nan,
        precision_same_day=precision, opportunity_events=len(opp),
        captured_day0=cap[0], recall_opportunity_day0=rec[0],
        captured_within_5d=cap[5], recall_opportunity_5d=rec[5],
        captured_within_10d=cap[10], recall_opportunity_10d=rec[10],
        captured_within_20d=cap[20], recall_opportunity_20d=rec[20]))
res=pd.DataFrame(rows)
res.to_csv(OUT/'recall_mfe60.csv',index=False)
print('--- MFE60 RECALL DIAGNOSTIC ---')
print(res.to_string(index=False))
(OUT/'recall_mfe60_meta.json').write_text(json.dumps({
    'target':'MFE60 = max(high[t+1:t+60]) / open[t+1] - 1',
    'low':'pos250 <= 20%',
    'signal':'low and turnover_t / prior10d_mean >= 1.5',
    'opportunity_cooldown':'60 trading days per stock',
    'capture_windows':'signal on opportunity day or within +5/+10/+20 trading days'
},ensure_ascii=False,indent=2))
# ci trigger marker: maxup60 final run
