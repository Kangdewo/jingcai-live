# T+ v0.6.2 — 周一003双来源赛果与研究复盘（独立增量包）

## 当前状态

- **已确认比赛身份**：T `t:2026-10-27:周一003` → OpenLigaDB `85433`。北京时间2026-10-27 04:00开赛。代码中保留身份证据和赛前球队数据。
- **第二数据源 football-data.org**：API程序已接入，但需要用户自己的 `FOOTBALL_DATA_API_KEY`，且比赛ID尚未经过人工/官方证据核定。不能宣称已经完成双来源赛果核验。
- **预测基准**：旧仓库 `market_devig_v1` 2026-10-26T14:54:13Z记录的市场赔率去水概率。非001—005正式模型，也没有真实T-15冻结。此包只可做研究回顾。
- **赛果**：当前测试及保存的赛前快照为 null。不能凭预测或已知赛程填造赛果。

## 文件及放置

把 ZIP 解压后，把其**内容**叠加复制到已经安装 v0.6 的程序根目录（原目录中有 `tplus_realdata/`，即 `RUN_V06_DEMO.cmd` 旁边）。或者上传下列文件到 GitHub 的 `feat/tplus-match-intelligence-v05` 开发分支根目录，保留路径：

```
tplus_resultlink/__init__.py
tplus_resultlink/core.py
tplus_resultlink/cli.py
tests/test_tplus_resultlink.py
.github/workflows/tplus-resultlink-tests.yml
evidence/match003_config.json
evidence/match003_prematch_evidence.json
evidence/match003_openliga_prematch.json
evidence/match003_primary_identity.json
RUN_MATCH003_CHECK.cmd
README_V062_CN.md
```

不要上传 `output/`、令牌、`.pyc` 或 `__pycache__`，不要覆盖 T v6.5 或现有生产工作流。

## 1. 本地只需一次命令

在 v0.6 程序根目录打开 CMD：

```cmd
py -3 -m unittest discover -s tests -p "test_tplus_resultlink.py" -v
```

然后双击 `RUN_MATCH003_CHECK.cmd`。脚本会按需尝试读取 OpenLigaDB 85433 并保存一个 append-only 快照及最新检查报告；未配置第二家API时应提示 `FOOTBALL_DATA_API_KEY_NOT_CONFIGURED`，这是正常且保守的状态。

结果放在：`output/match003_result_review/latest_review.json`。每次检查另保存一份 `snapshots/` 归档，不能重写赛前证据。

## 2. 第二来源启用方式

football-data.org 官方文档：https://www.football-data.org/documentation/api

先注册并获取API token。出于安全，不要把它提交到公开仓库或发到聊天。仅在自己Windows CMD临时设置：

```cmd
set FOOTBALL_DATA_API_KEY=这里填写你自己的密钥
py -3 -m tplus_resultlink.cli check
```

程序会尝试读取 `PD`（西甲）2026赛季的数据，按球队名称和开赛时间筛选候选。**如果产生一个或多个 `second_source_candidates`，只是候选，不会自动把ID批准。** 比赛ID仍需要经可信赛事页面/提供商核对，才允许在 `evidence/match003_config.json` 中填写：

```json
"football_data_approved_link": {
  "provider_match_id": "核对后的数字ID",
  "identity_verified": true,
  "evidence_url": "https://可信赛程/比赛详情链接"
}
```

如果没有Token、接口不覆盖、返回401/403/429，或者没找到唯一的匹配比赛，保持待核验，不要随意猜ID。

## 3. 双源一致才能核算

双源身份+FT比分一致 → `FT_VERIFIED_TWO_SOURCES`。双方半场比分也一致 → `FT_AND_HT_VERIFIED_TWO_SOURCES`；如果半场缺失或冲突，只核FT，不计算半全场。

若身份不符、两家赛果冲突，自动拒绝评分。报告中的市场基准Brier/LogLoss/Top1，仅属于**赛前市场基准历史研究**；正式005准确率仍为空，没有有效冻结时不得报正式命中率。

## 4. 后续无人值守

只有在第二家比赛ID正式核定、合法API可稳定访问后，才适合把本地Windows任务计划或GitHub Actions改成赛后定时核验。当前云端工作流**只做离线单元测试，不携带API token，不发起真实抓取**。生产定时任务需要额外校验密钥保护、速率限制、失败退避、时间区及审计；不能通过单纯把 `on: schedule` 加进去就宣称完成自动化。

## 5. 后续迭代

扩展覆盖四场比赛、建统一 `match_id` 表、双源结果归档、逐场比分/半全场/总进球/让球核验；同步处理实际原始T-15冻结、模型版本与媒体情报的时间隔离。
