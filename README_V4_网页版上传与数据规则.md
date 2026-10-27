# T+ 长期复盘与盈亏中枢 v4 — GitHub 网页版部署

版本：2026-10-27。保留 v3 九个历史数据/归档组件并增加日期、日账、资金图和模型—实单映射。

## 请先确认：这个是完整包，不要求先上传 v3

GitHub 仓库 `Kangdewo/jingcai-live`，分支 `main`。

### 第一次上传（仓库主页）

1. 打开 <https://github.com/Kangdewo/jingcai-live>，确认 `main`。
2. `Add file` → `Upload files`。
3. 从解压后的文件夹里拖入 `docs`、`tests`、`tplus_cloud` **三个文件夹中的本包文件**，以及这份 README。特别确认显示 `docs/index.html`、`docs/data/ledger/index.json`、`docs/data/ledger/days/2026-10-24.json` 至 `2026-10-27.json`、`docs/data/reviews/2026-10-26.json`、`tplus_cloud/archive_daily.py`、`tplus_cloud/build_ledger_index.py` 和两个测试文件。
4. `Commit changes` 到 `main`；不要删除、覆盖本包以外的旧项目文件。
5. **不要把 ZIP 上传为仓库文件；不要把本包整个外层文件夹拖进去。**

### 第二次上传（工作流正确目录）

1. 打开 <https://github.com/Kangdewo/jingcai-live/tree/main/.github/workflows>。
2. `Add file` → `Upload files`。
3. 从本包 `.github/workflows/` 选择 **两个**文件：`tplus-pipeline.yml` 与 `tplus-ledger-index.yml`，上传至此目录，提交到 `main`。
4. 不要把它们错放到仓库根目录的 `workflows/`。

### 今日实单与模型方案：不用手写 JSON

- 在网页点击 **今日账本** → **新实单登记**，输入票号、注数、过关方式、出票时间（**北京时间**）、模型/组别与证据等级，按 **加入当日草稿**。
- 同页的 **今日模型方案登记** 可以输入模型名称、同场编号、玩法、赛前具体选择、冻结时间和原始证据编号。无法核验的草稿不会自动变成正式预测或“未买”。
- 点击 **导出当日 JSON**，浏览器保存 `YYYY-MM-DD.json`；然后在 GitHub 网页对应 `docs/data/ledger/days/` 中上传、提交。GitHub Pages 静态网页不能直接写回仓库，刷新之前必须先导出本地草稿。
- 已登记但还没完赛的票据只有本金和注数、无已知返奖，结算字段保持 `null`。**这天不能计算盈亏，更不能算全军覆没。**
- 赛后可依据原始票面SP、比赛身份、双源赛果和冻结版本另行生成完整结算 JSON。不得直接把未结票补写为0返奖。

### 验收

1. GitHub `Actions`：检查新增 `T+ daily ticket ledger index (no paid API)` 是否绿色；已有 `T+ unified data-to-prediction pipeline` 是否可手工触发。不必反复触发并发任务。
2. 打开 <https://kangdewo.github.io/jingcai-live/>，`Ctrl+F5`。
3. 检查 11 栏：总览、赛程赔率、五大玩法、今日账本、往日复盘、往日实单、盈亏统计、历史研究、赛果评估、AI运行状态、数据来源。
4. 在盈亏统计中应看到：10/24 投入68、返62.38；10/25 投入58、返20.85；10/26 投入116、返112.25；累计投入242、返195.48、理论净亏46.52。10/27尚无人工冻结结算时标为未登记，绝不能算作0投注或全军覆没。
5. 在往日复盘选2026-10-26，能筛选 `模型给了 · 实单没买`；在往日实单显示7张/58注并可看完整58注。

## 此后每一天的同步方式

- 当天实际票据、出票时间、模型冻结稿、原始SP和结算核验都必须先按真实来源保留私有原稿，形成**去标识化**的 `docs/data/ledger/days/YYYY-MM-DD.json`。
- 每个 `recommendations[]` 表示赛前模型针对“同一比赛/同一玩法”的具体选择；`purchase_status` 区分 `purchased_choice_only`、`purchased`、`not_purchased`、`evidence_insufficient`。没有票据和冻结证明时禁止宣称“没买”。
- `tickets[]` 内只存脱敏的票号、出票时间、SP核算、本金、理论返奖、模型归属**证据等级**。勿上传票据照片、二维码、个人资料、API Token。
- 某日没有可公开记录：`summary: null, tickets: []`；有待结票据则记录 `summary.fully_reconciled: false`、实际已登记本金和注数，返奖/净盈亏字段为 `null`。只有 `fully_reconciled: true` 的日期进入累计净值。
- 在 GitHub 网页 `docs/data/ledger/days/` 上传新日JSON后，`tplus-ledger-index.yml` 自动校验并重建 `docs/data/ledger/index.json`，Pages 更新后按日读取。必须先确保自动测试通过。如果 GitHub Actions 没有写权限会失败，需检查 Settings → Actions → General → Workflow permissions 的 `Read and write permissions`；勿在未核实情况下声称自动成功。
- 实单跨日结算仍以**出票日**记账。新数据不应覆盖此前冻结原始票据/预测文件；公开派生文件需保留审计版本与来源。
- 历史4.15万场目前仅许可使用汇总，不能凭汇总反推没有存档的单场历史赔率、模型预测或实盘净值。

## 安全和归属纪律

- `model_devig_v1` 是盘口去水市场基线，不是 001—005 独立模型，也不是 ChatGPT 对话自动运行。
- 10/25 `01/001/002` 是**组别归属**，不能算单独001或002 ROI。D01整票相联但不能等同于005/06。
- 10/26 D 票暂定关联 GPT-6 研究版，其余不强制归属。历史 T研究初版是非独立综合预测。
- 10/24 的 C 票仅已知 **部分选项一致**，不能声称 ChatGPT 原样推荐该整票。
- ROI 为按票面 SP 重建的**理论**值，没有体彩兑奖凭证。正式 `predictions/evaluation.json` 必须经过双独立来源和同场映射验证后才计入模型评价；此系统不修改它。
- 真实首发、球员伤停、独立xG、天气、场地仍受外部授权/数据接入约束；本包不伪造。AI API 使用仍须明确开关、密钥、费用审批，不在本包自动打开。

## 文件清单

`docs/index.html`、`docs/data/daily/index.json`、`docs/data/reviews/2026-10-26.json`、`docs/data/ledger/index.json`、`docs/data/ledger/days/{2026-10-24,2026-10-25,2026-10-26,2026-10-27}.json`、`tplus_cloud/archive_daily.py`、`tplus_cloud/build_ledger_index.py`、`tests/test_daily_archive.py`、`tests/test_historical_review.py`、`tests/test_ledger_v4.py`、`.github/workflows/tplus-pipeline.yml`、`.github/workflows/tplus-ledger-index.yml`。

`docs/index.html` 是一个可直接部署的完整网页，公开 JSON 接口仍使用原仓库路径。
