# US Market Simulation Monitor

这是一个美股监控与模拟盘验证仓库，用于记录每日市场节点、来源、分析、纸面交易计划和绩效。它不接管真实券商账户，不保存账号、Cookie、Token 或 API Key，也不承诺稳定收益。

## 当前边界

- 真实账户：未接入，禁止自动下真实单。
- 模拟盘：以 `journal/paper_trades.csv` 为唯一交易账本，所有交易必须标注 `planned`、`filled`、`canceled` 或 `no_trade`。
- 数据来源：报告必须记录来源 URL 和采集时间；无法采集时必须写明缺口。
- Git 留痕：每日新增或更新报告、账本、快照后提交一次 commit。

## 快速运行

```bash
python3 scripts/market_monitor.py --date 2026-06-19
python3 scripts/event_risk.py --date 2026-06-19
python3 scripts/performance.py --date 2026-06-19
python3 scripts/paper_fill.py --date 2026-06-19
python3 scripts/apply_paper_fills.py --date 2026-06-19
python3 scripts/live_account_gate.py --date 2026-06-19
python3 scripts/audit_monitor.py --date 2026-06-19
python3 -m unittest discover -s tests
```

输出会写入：

- `data/market_snapshots/YYYY-MM-DD.json`
- `data/event_risk/YYYY-MM-DD.json`
- `data/performance/YYYY-MM-DD.json`
- `data/equity_curve.csv`
- `journal/fill_reviews/YYYY-MM-DD.json`
- `journal/apply_logs/YYYY-MM-DD.dry_run.json`
- `data/live_gate/YYYY-MM-DD.json`
- `reports/YYYY-MM-DD.generated.md`

## 每日流程

1. 确认交易日和关键宏观事件。
2. 抓取指数、ETF、波动率和利率代理的公开行情。
3. 更新模拟盘交易账本，只记录纸面操作。
4. 写入报告：事实、来源、分析、风险、下一步动作。
5. 运行测试并用 git 提交。

## 参考仓库吸收点

- `ZhuLinsen/daily_stock_analysis`：采用“每日报告 + 数据源 + 交易纪律”的工作流形态。
- `HKUDS/Vibe-Trading`：采用 paper/live 分离、kill switch、order gate、run card 这类安全边界思想。
