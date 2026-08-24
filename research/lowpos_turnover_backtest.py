import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd

H=(5,10,20,40,60)
OUT=Path('bt_out'); OUT.mkdir(exist_ok=True)

files=sorted(glob.glob('bt_data/kline_*.parquet'))
if not files: raise SystemExit('no parquet files')
df=pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
print(df.columns.tolist())

rename={}
for c in df.columns:
    lc=str(c).lower()
    if lc in ('date','trade_date'): rename[c]='date'
    elif lc in ('code','ts_code','symbol'): rename[c]='code'
    elif lc in ('open','adj_open','qfq_open'): rename[c]='open'
    elif lc in ('high','adj_high','qfq_high'): rename[c]='high'
    elif lc in ('low','adj_low','qfq_low'): rename[c]='low'
    elif lc in ('close','adj_close','qfq_close'): rename[c]='close'
    elif lc in ('turn','turnover','turnover_rate'): rename[c]='turnover'
df=df.rename(columns=rename)
need=['date','code','open','high','low','close','turnover']
missing=[c for c in need if c not in df.columns]
if missing: raise SystemExit(f'missing columns {missing}; got {df.columns.tolist()}')

df=df[need].copy()
df['date']=pd.to_datetime(df['date'])
df['code']=df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']:
    df[c]=pd.to_numeric(df[c], errors='coerce')
df=df.dropna().sort_values(['code','date']).reset_index(drop=True)

g=df.groupby('code', group_keys=False)
df['low250']=g['low'].transform(lambda s:s.rolling(250,min_periods=250).min())
df['high250']=g['high'].transform(lambda s:s.rolling(250,min_periods=250).max())
df['pos250']=(df['close']-df['low250'])/(df['high250']-df['low250'])
df['to_ma10_prior']=g['turnover'].transform(lambda s:s.shift(1).rolling(10,min_periods=10).mean())
df['to_ratio']=df['turnover']/df['to_ma10_prior']
df['entry_open']=g['open'].shift(-1)
for h in H:
    df[f'exit_close_{h}']=g['close'].shift(-h)
    df[f'ret_{h}d']=df[f'exit_close_{h}']/df['entry_open']-1

df['low_only']=df['pos250'].le(.20)
df['signal']=df['low_only'] & df['to_ratio'].ge(1.5)

base=df[df['entry_open'].notna() & df['pos250'].notna() & df['to_ratio'].notna()].copy()
base['stock_idx']=base.groupby('code').cumcount()

def cooldown_events(frame, flag, cooldown=20):
    x=frame[frame[flag]].copy()
    keep=[]; last={}
    for r in x.itertuples(index=False):
        p=int(r.stock_idx); c=r.code
        ok=c not in last or p-last[c]>cooldown
        keep.append(ok)
        if ok: last[c]=p
    return x.loc[np.array(keep)].copy()

sig_all=base[base.signal].copy(); low_all=base[base.low_only].copy()
sig_ev=cooldown_events(base,'signal',20); low_ev=cooldown_events(base,'low_only',20)

def summarize(frame,label):
    rows=[]
    for h in H:
        s=frame[f'ret_{h}d'].dropna()
        mean=s.mean() if len(s) else np.nan
        sd=s.std(ddof=1) if len(s)>1 else np.nan
        t=mean/(sd/np.sqrt(len(s))) if len(s)>1 and sd>0 else np.nan
        rows.append(dict(group=label,horizon=h,n=len(s),mean=mean,median=s.median() if len(s) else np.nan,
                         win_rate=(s>0).mean() if len(s) else np.nan,p10=s.quantile(.1) if len(s) else np.nan,
                         p90=s.quantile(.9) if len(s) else np.nan,t_stat=t))
    return rows

summary=[]
for f,l in [(sig_all,'signal_all_days'),(sig_ev,'signal_cooldown20'),(low_all,'low_only_all_days'),(low_ev,'low_only_cooldown20')]:
    summary+=summarize(f,l)
pd.DataFrame(summary).to_csv(OUT/'summary.csv',index=False)
sig_ev[['date','code','pos250','turnover','to_ma10_prior','to_ratio']+[f'ret_{h}d' for h in H]].to_csv(OUT/'signal_events.csv',index=False)

rows=[]
for f,l in [(sig_ev,'signal_cooldown20'),(low_ev,'low_only_cooldown20')]:
    for h in H:
        d=f.groupby('date')[f'ret_{h}d'].mean().dropna()
        rows.append(dict(group=l,horizon=h,n_dates=len(d),mean=d.mean(),median=d.median(),win_rate=(d>0).mean()))
pd.DataFrame(rows).to_csv(OUT/'summary_date_ew.csv',index=False)

rows=[]
for f,l in [(sig_ev,'signal_cooldown20'),(low_ev,'low_only_cooldown20')]:
    z=f.copy(); z['year']=z['date'].dt.year
    for y,yy in z.groupby('year'):
        for h in (20,60):
            s=yy[f'ret_{h}d'].dropna()
            if len(s): rows.append(dict(group=l,year=y,horizon=h,n=len(s),mean=s.mean(),median=s.median(),win_rate=(s>0).mean()))
pd.DataFrame(rows).to_csv(OUT/'summary_by_year.csv',index=False)

# Same-date paired control: on each signal date, compare signal stocks vs other low-position stocks
paired=[]
for h in H:
    c=f'ret_{h}d'
    s=sig_all.groupby('date')[c].mean().rename('signal_mean')
    ctrl=base[base['low_only'] & ~base['signal']].groupby('date')[c].mean().rename('control_mean')
    p=pd.concat([s,ctrl],axis=1).dropna()
    p['alpha']=p['signal_mean']-p['control_mean']
    a=p['alpha']
    sd=a.std(ddof=1) if len(a)>1 else np.nan
    t=a.mean()/(sd/np.sqrt(len(a))) if len(a)>1 and sd>0 else np.nan
    paired.append(dict(horizon=h,n_dates=len(a),signal_mean=s.loc[p.index].mean(),control_mean=ctrl.loc[p.index].mean(),
                       alpha_mean=a.mean(),alpha_median=a.median(),alpha_win_rate=(a>0).mean(),t_stat=t))
pd.DataFrame(paired).to_csv(OUT/'same_date_paired_alpha.csv',index=False)

meta=dict(rows=len(df),stocks=int(df.code.nunique()),date_min=str(df.date.min().date()),date_max=str(df.date.max().date()),
          signal_days=len(sig_all),signal_events=len(sig_ev),low_only_days=len(low_all),low_only_events=len(low_ev))
(OUT/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
print(json.dumps(meta,ensure_ascii=False,indent=2))
print(pd.DataFrame(summary).to_string(index=False))
print('--- SAME-DATE PAIRED ALPHA ---')
print(pd.DataFrame(paired).to_string(index=False))
