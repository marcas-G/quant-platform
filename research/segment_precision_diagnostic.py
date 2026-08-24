import glob
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path('bt_out'); OUT.mkdir(exist_ok=True)
ZZ=0.15
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
df['date']=pd.to_datetime(df['date']); df['code']=df['code'].astype(str).str.replace('.0','',regex=False).str.zfill(6)
for c in ['open','high','low','close','turnover']: df[c]=pd.to_numeric(df[c],errors='coerce')
df=df.dropna().sort_values(['code','date']).reset_index(drop=True)
g=df.groupby('code',group_keys=False)
df['low250']=g['low'].transform(lambda s:s.rolling(250,min_periods=250).min())
df['high250']=g['high'].transform(lambda s:s.rolling(250,min_periods=250).max())
df['pos250']=(df['close']-df['low250'])/(df['high250']-df['low250'])
df['to_ma10_prior']=g['turnover'].transform(lambda s:s.shift(1).rolling(10,min_periods=10).mean())
df['to_ratio']=df['turnover']/df['to_ma10_prior']
df['signal']=df['pos250'].le(.20)&df['to_ratio'].ge(1.5)


def pivots(close,thr=.15):
    n=len(close)
    if n<2:return []
    out=[]; rh=rl=close[0]; hi=li=0; trend=0
    for i in range(1,n):
        p=close[i]
        if trend==0:
            if p>rh: rh,hi=p,i
            if p<rl: rl,li=p,i
            if rl>0 and rh/rl-1>=thr:
                if li<hi:
                    out.append((li,'L',rl)); trend=1; rh,hi=p,i
                else:
                    out.append((hi,'H',rh)); trend=-1; rl,li=p,i
        elif trend==1:
            if p>=rh: rh,hi=p,i
            elif rh>0 and p/rh-1<=-thr:
                out.append((hi,'H',rh)); trend=-1; rl,li=p,i
        else:
            if p<=rl: rl,li=p,i
            elif rl>0 and p/rl-1>=thr:
                out.append((li,'L',rl)); trend=1; rh,hi=p,i
    clean=[]
    for x in out:
        if clean and x[0]==clean[-1][0]: continue
        if clean and x[1]==clean[-1][1]:
            if (x[1]=='H' and x[2]>clean[-1][2]) or (x[1]=='L' and x[2]<clean[-1][2]): clean[-1]=x
        else: clean.append(x)
    return clean

rows=[]
for code,z in df.groupby('code',sort=False):
    z=z.sort_values('date').reset_index(drop=True)
    if len(z)<320: continue
    pv=pivots(z['close'].to_numpy(float),ZZ)
    for j,(idx,typ,lp) in enumerate(pv):
        if typ!='L' or j==0 or pv[j-1][1]!='H': continue
        li=int(idx); hp=float(pv[j-1][2])
        if li+60>=len(z) or li+1>=len(z): continue
        decline=lp/hp-1 if hp>0 else np.nan
        if decline>-0.30: continue
        lowpos=z.at[li,'pos250']
        if pd.isna(lowpos) or lowpos>.20: continue
        entry=z.at[li+1,'open']; future=z.loc[li+1:li+60,'high'].max()
        target=bool(entry>0 and future/entry-1>=.50)
        def cap(a,b):
            lo=max(0,li+a); hi=min(len(z)-1,li+b)
            return bool(z.loc[lo:hi,'signal'].any())
        rows.append(dict(code=code,low_date=z.at[li,'date'],decline=decline,low_pos250=lowpos,
                         target_mfe50=target,
                         sig_pre20_0=cap(-20,0),sig_pre10_0=cap(-10,0),sig_pre5_0=cap(-5,0),
                         sig_m5_p5=cap(-5,5),sig_0_p5=cap(0,5),sig_m20_p5=cap(-20,5)))

x=pd.DataFrame(rows)
x.to_csv(OUT/'deep_bottom_all_events_15pct.csv',index=False)
windows=['sig_pre20_0','sig_pre10_0','sig_pre5_0','sig_m5_p5','sig_0_p5','sig_m20_p5']
base=float(x.target_mfe50.mean())
res=[]
res.append(dict(window='baseline_all_deep_bottoms',n=len(x),signals=len(x),targets=int(x.target_mfe50.sum()),precision=base,recall=1.0,lift=1.0))
for w in windows:
    s=x[x[w]]
    precision=float(s.target_mfe50.mean()) if len(s) else np.nan
    recall=float(s.target_mfe50.sum()/x.target_mfe50.sum()) if x.target_mfe50.sum() else np.nan
    res.append(dict(window=w,n=len(x),signals=len(s),targets=int(s.target_mfe50.sum()),precision=precision,recall=recall,lift=precision/base if base else np.nan))
res=pd.DataFrame(res)
res.to_csv(OUT/'deep_bottom_precision_recall_15pct.csv',index=False)
print('--- DEEP STRUCTURAL BOTTOM PRECISION/RECALL, ZIGZAG 15% ---')
print(res.to_string(index=False))
