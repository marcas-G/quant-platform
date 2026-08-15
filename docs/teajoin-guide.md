# teajoin Tushare 代理使用指南（2026-08-16 存档）

> 来源：`https://teajoin.com/g` 使用指南页（访问验证后内容）。
> 平台配置：API Key 存于项目 `.env`（`FACTORLAB_TEAJOIN_TOKEN`，gitignored），到期 2026-08-22。

## 使用前必读

- 本服务兼容 Tushare SDK 与 HTTP API；将请求地址改为 `https://teajoin.com` 后即可使用。
- 15000 积分通用套餐覆盖常用股票、ETF、指数、基金、期货、期权、财务、资金流及特色数据接口；
  具体以已开通套餐和卖家提供的接口清单为准。
- 历史分钟与实时行情属于可单独开通的权限，通用套餐默认不包含。
- **最高频率 450 次/分钟**。批量请求建议间隔至少 0.2 秒，不要用无限并发方式下载全市场数据。
- 返回格式与 Tushare Pro 保持一致：`data.fields` 为字段名，`data.items` 为数据行。
  无数据时正常返回空列表，不代表程序出错。

## 1. 获取 API Key

兑换页面：`https://teajoin.com/redeem`，输入兑换码获得专属 API Key 和到期时间。
兑换码可重复使用（随时重新输入同一兑换码即可查看 Key）。返回示例：

```json
{"api_key": "c14680ec99fb6de2d8509ef72f938453", "expires_at": "2026-06-08 17:47:34"}
```

## 2. 调用方式

### 方式一：Tushare SDK（推荐，最简单）

```python
import tushare as ts

token = "<YOUR_API_KEY>"  # 兑换获得的 API Key
ts.set_token(token)
pro = ts.pro_api()
pro._DataApi_token = token
pro._DataApi__http_url = "https://teajoin.com"

df = pro.daily(ts_code='000001.SZ', start_date='20260101', end_date='20260110')
```

特殊情形：`ts.pro_bar()` 等模块级函数必须手动传 `api=pro`：

```python
df = ts.pro_bar(ts_code='002594.SZ', api=pro, start_date='20180101', end_date='20181011', adj='qfq')
```

### 方式二：直接 HTTP 请求

POST 到**根路径 `/`**（不是 `/g`）：

```python
import requests

resp = requests.post("https://teajoin.com", json={
    "api_name": "daily",
    "token": "<YOUR_API_KEY>",
    "params": {"ts_code": "000001.SZ", "start_date": "20260101", "end_date": "20260110"},
})
data = resp.json()
```

### 方式三：MCP 协议（接入 AI 大模型）

```json
{
  "mcpServers": {
    "tushare": {
      "url": "https://teajoin.com/mcp/?api_key=<YOUR_API_KEY>"
    }
  }
}
```

## 3. 批量下载建议

尽量按日期或代码分批请求，不要瞬间并发提交大量任务。带间隔、重试和断点落盘示例：

```python
import time
from pathlib import Path
import pandas as pd
import tushare as ts

API_KEY = "<YOUR_API_KEY>"
OUTPUT = Path("daily_prices.csv")
CODES = ["000001.SZ", "000002.SZ", "600519.SH"]

ts.set_token(API_KEY)
pro = ts.pro_api()
pro._DataApi_token = API_KEY
pro._DataApi__http_url = "https://teajoin.com"

frames = []
for index, ts_code in enumerate(CODES, start=1):
    for attempt in range(3):
        try:
            df = pro.daily(ts_code=ts_code, start_date="20260101", end_date="20260131")
            frames.append(df)
            print(f"[{index}/{len(CODES)}] {ts_code}: {len(df)} 行")
            break
        except Exception as exc:
            if attempt == 2:
                print(f"跳过 {ts_code}: {exc}")
            else:
                time.sleep(2 * (attempt + 1))
    time.sleep(0.2)  # 建议的最小请求间隔

result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
```

常用技巧：
- `fields="ts_code,trade_date,close,vol"` 只取需要的列。
- 大量历史数据优先按交易日、月份或股票列表分批保存，中断后从已保存文件继续。
- 部分接口支持 `limit` 与 `offset` 分页。

## 4. 常用接口速查

日期统一 `YYYYMMDD`，股票代码用 Tushare 格式（`000001.SZ`）。

| 接口名 | 用途 | 常用参数 |
|--------|------|----------|
| `daily` | 日线行情 | ts_code, trade_date, start_date, end_date |
| `weekly` | 周线行情 | ts_code, start_date, end_date |
| `monthly` | 月线行情 | ts_code, start_date, end_date |
| `daily_basic` | 每日指标 | ts_code, trade_date |
| `stock_basic` | 股票列表 | exchange, list_status |
| `trade_cal` | 交易日历 | exchange, start_date, end_date |
| `income` | 利润表 | ts_code, start_date, end_date |
| `balancesheet` | 资产负债表 | ts_code, start_date, end_date |
| `cashflow` | 现金流量表 | ts_code, start_date, end_date |
| `index_daily` | 指数日线 | ts_code, start_date, end_date |
| `limit_list_d` | 涨跌停列表 | trade_date, ts_code |
| `moneyflow` | 个股资金流向 | ts_code, trade_date |
| `stk_limit` | 涨跌停价格 | ts_code, trade_date |
| `ths_hot` | 同花顺热点 | trade_date, ts_code |
| `broker_recommend` | 券商金股 | month |
| `cyq_chips` | 筹码分布 | ts_code, trade_date |
| `stk_factor_pro` | 专业量化因子 | ts_code 或 trade_date |

## 5. 已支持接口目录（137 个）

带 `_vip` 的是对应财务接口的 VIP 版本；不同接口必填参数不同。

- **股票基础与行情**：stock_basic、trade_cal、hk_tradecal、us_tradecal、namechange、stk_rewards、
  bak_basic、stock_st、st、stock_hsgt、bse_mapping、daily、weekly、monthly、stk_weekly_monthly、
  stk_week_month_adj、adj_factor、suspend_d、daily_basic、stk_limit、moneyflow、moneyflow_hsgt、
  hsgt_top10、ggt_top10、hk_hold、bak_daily
- **财务、公司与市场参考**：income(_vip)、balancesheet(_vip)、cashflow(_vip)、forecast(_vip)、
  express(_vip)、dividend、fina_indicator(_vip)、fina_audit、fina_mainbz(_vip)、disclosure_date、
  top10_holders、top10_floatholders、top_inst、pledge_stat、pledge_detail、repurchase、share_float、
  block_trade、stk_holdernumber、stk_holdertrade、broker_recommend
- **资金流、打板与题材**：margin、margin_detail、moneyflow_ths、moneyflow_dc、moneyflow_ind_ths、
  moneyflow_ind_dc、moneyflow_cnt_ths、moneyflow_mkt_dc、limit_list_d、limit_list_ths、
  limit_cpt_list、limit_step、top_list、kpl_list、kpl_concept_cons、ths_hot、dc_hot、dc_index、
  dc_member、dc_daily、dc_concept、dc_concept_cons、tdx_index、tdx_member、tdx_daily
- **同花顺、游资、筹码与量化**：ths_daily、ths_index、ths_member、hm_list、hm_detail、cyq_perf、
  cyq_chips、stk_factor、stk_factor_pro、stk_surv、stk_nineturn、stk_auction、stk_auction_o、
  stk_auction_c、report_rc
- **指数、基金与 ETF**：index_basic、index_daily、index_weekly、index_monthly、index_weight、
  index_dailybasic、index_classify、index_member_all、sw_daily、ci_index_member、fund_basic、
  fund_nav、fund_daily、fund_adj、fund_div、fund_portfolio、fund_share、etf_basic、etf_index、
  etf_share_size
- **期货、期权、可转债、债券与宏观**：fut_basic、fut_daily、fut_holding、fut_wsr、fut_settle、
  opt_basic、opt_daily、cb_basic、cb_daily、bond_blk、bc_otcqt、bc_bestotcqt、hk_basic、cn_gdp、
  cn_cpi、cn_ppi、cn_pmi、cn_m、cn_schedule、shibor、shibor_quote、shibor_lpr、libor
- **独立权限**：历史分钟（stk_mins、etf_mins，需单独开通）；集合竞价（stk_auction，所有套餐包含，
  早盘 9:26 后有数据，没拿到数据间隔 20 秒再试；盘后 stk_auction_c、stk_auction_o）

**注意**：实时行情、新闻公告、研报、港美股等独立权限接口不在通用套餐默认范围内。

## 6. 常见问题

- **数据格式和官方 Tushare 一样吗？** 一致。响应使用 Tushare 标准 JSON 结构（`data.fields` + `data.items`），SDK 自动转 DataFrame。
- **批量下载变慢/超时？** 间隔至少 0.2 秒、降低并发、分批保存、网络波动重试，不要持续重复提交。
- **返回空数据？** 检查代码/日期/接口名/必填参数；该日期无数据返回空列表；接口不在套餐内也不返回。
- **到期怎么办？** 访问 `/redeem` 输入兑换码查看到期时间；到期联系卖家购买新兑换码。
- **API Key 安全？** 不要提交到 Git 仓库、截图或公开聊天记录；泄露后联系售后。
