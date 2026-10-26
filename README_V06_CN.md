# T+ v0.6 实际赛程/赛果与近期战绩数据适配器（独立增量包）

**状态：离线程序已测试，外部真实采集需要在可联网的用户电脑上执行。**

目标：用两个已文档化的数据服务建立比赛信息来源、近期战绩、初步H2H及谨慎的赛果核验入口。保留 T v6.5 和 v0.5 所有文件，不改变 main 分支或正式模型。本包不包含未经授权的赔率爬虫、球员xG或模型001—005。

## 0. 文件放置

在仓库独立分支 `feat/tplus-match-intelligence-v05` 的仓库根目录增加以下内容：

- `tplus_realdata/__init__.py`, `core.py`, `cli.py`
- `tests/test_tplus_realdata.py`
- `examples/fictional_football_data.json`, `fictional_openligadb.json`, `fictional_links.json`
- `.github/workflows/tplus-realdata-tests.yml`
- `README_V06_CN.md`

**所有 examples/fictional_* 都是虚构样例，绝不能作为比赛真实赛果导入生产仓库。** 不要上传 `output/` 的真实接口响应、API密钥或个人数据。当前测试工作流只做离线验证，不会自动向外部接口请求或写入正式预测文件。

## 1. 运行本地验证

从仓库根目录打开 Windows CMD，执行：

```
py -3 -m unittest discover -s tests -p "test_tplus_realdata.py" -v
```

GitHub Actions 会在新增/修改该模块时自动执行同类离线测试。

## 2. 免费接口试运行（真实数据，需联网）

OpenLigaDB 官方接口 https://api.openligadb.de/index.html 声明免密钥、限制每IP每分钟60次、建议低频使用。这是社区维护的数据，数据内容和可靠度需要核验；不保证你T表格中的全部联赛覆盖。

```
py -3 -m tplus_realdata.cli fetch --provider openligadb --league bl1 --season 2026 --output output/openligadb_bl1_2026.json
```

此命令读取德国甲级联赛 2026 赛季（OpenLigaDB 使用赛季开始年），输出标准化档案。请注意2026赛季在远程端是否发布，以及实际返回场次；若未覆盖，保持缺失，不造数据。

之后获取“现在时间点已知的近期战绩”，例如将以下2026-10-27的日期调整为真实本地时间：

```
py -3 -m tplus_realdata.cli report --input output/openligadb_bl1_2026.json --cutoff 2026-10-27T08:00:00+08:00 --output output/form_studies.json
```

它仅能分析该数据包内已知的同联赛比赛；不能假冒全赛事H2H、历史赛季排名或真实xG。

## 3. 第二数据源（可选，需要账户密钥）

服务说明 https://www.football-data.org/documentation/api 。套餐限制和赛事授权请以提供方为准，免费版本约10次每分钟。建议先不买套餐，只试支持联赛；比赛表的国家队、欧战和国内杯赛覆盖依接口而定。

申请有效密钥后，在本地临时CMD环境：

```
set FOOTBALL_DATA_API_KEY=在此输入自己的密钥（不要截图、不要上传）
py -3 -m tplus_realdata.cli fetch --provider football_data --league BL1 --season 2026 --output output/football_data_BL1_2026.json
```

`--league` 可以使用提供方开放的 PL、BL1 等代码。密钥只用于本地HTTP请求头，不会写入文件，勿使用系统的公开Github变量存密钥。

## 4. 正式赛果与T预测如何关联

不能通过中文队名模糊连接。需要至少有用户或可靠官方链接确认 `t_match_id -> provider/provider_match_id`，将真实证据URL写在独立 `links.json`。每条映射需要：

```
{
  "t_match_id":"t:YYYY-MM-DD:周一001",
  "provider":"football_data",
  "provider_match_id":"真实提供商ID",
  "identity_verified":true,
  "evidence_url":"https://真实有效的赛事详情链接"
}
```

至少两个**不同提供方**对同一完赛赛果一致、且开球时间相差不超过10分钟，核验器才能输出 `VERIFIED_TWO_SOURCES`。来源冲突、半场矛盾、比赛中止或单来源全部保持待核验。仅显式通过的T映射才可进入评分。

```
py -3 -m tplus_realdata.cli reconcile --input output/openligadb_bl1_2026.json --input output/football_data_BL1_2026.json --links links.json --output output/result_review.json --verified-output output/results_verified.json
```

**注意：** `results_verified.json` 是兼容原 runner 的候选输出。仅在你已经人工或审计程序确认映射证据，以及保留真实赛前冻结记录后，才可考虑导入正式 `predictions/results_verified.json`。当前基础预测 `new_freezes=0`，不能通过赛后重新运行“补冻”来制造前瞻准确率。

## 5. 下一阶段

1. 对真实T比赛逐场建立 provider-ID 映射表（经证据确认）。
2. 先打通一个有两个来源的真实完赛比赛，进行赛果比对、可追溯记录。
3. 加入最近5/10场、主客战绩、H2H和积分榜（必须按赛前可见时间快照）。
4. 与 T v0.5 情报档案合并，接球员/阵容与媒体 AI 影子研究。
5. 单独建设不会越权覆写赛前预测的自动评分、训练候选和X审批。

**本包只完成程序与接口对接能力，不代表已经获取到当前4场的真实赛果或全联赛数据。**

### 赛制与数据准确性补充

计算出的“积分榜”是同一提供商、同一联赛、同一赛季已观察到的完赛数据合成的临时积分表；不代表官方积分榜，无法覆盖扣分、特殊同分规则以及数据源缺失。最终正式积分与球员身价需要额外字段/来源适配器。

对 football-data.org 明确标记了 EXTRA_TIME 的比赛，当前保守跳过自动FT结算，不将加时比分冒充竞彩90分钟比分。对其他杯赛或OpenLigaDB比赛仍需人工核验赛制和是否含加时。

## 一键演示（更方便）

Windows解压本包后，也可以直接双击 `RUN_V06_DEMO.cmd`，它将顺序执行离线测试、**一次** OpenLigaDB 德甲赛季数据采集，以及以当前时间为截止点的近期战绩/临时积分表报告。结果位于 `output/openligadb_bl1_2026.json` 和 `output/form_studies.json`。

脚本不会自动同步T比赛ID，不会覆盖 `predictions/`，也不会在GitHub Actions后台无限爬取。下载失败时会报错，不会造出假的真实结果。
