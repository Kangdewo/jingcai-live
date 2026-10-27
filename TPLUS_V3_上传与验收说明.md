# T+ 足球数据中枢 v3：历史、昨日复盘、实单与自动留档

日期：2026-10-27。适用仓库：`Kangdewo/jingcai-live` 的 `main` 分支。**全程可以使用 GitHub 网页版，不需要 Desktop、本地 Git 或 Python。**

## 本次实际完成的功能

1. 替换 `docs/index.html`：保留实时赔率、市场五玩法、AI 状态、历史研究、赛果核验、数据来源，并新增 **昨日复盘、实单账本**。共9个可以切换的栏目。
2. 增加 `docs/data/reviews/2026-10-26.json`：4场外部赛果、2026-10-26赛前市场基线、20:30五项研究初版、19:34和20:26两个盘口快照、7张58注原始冻结票据的**去标识化**复盘，理论返奖112.25元；不含票据照片/个人身份。
3. 增加 `tplus_cloud/archive_daily.py`：将未来每次实际运行中，开赛前的 `market_devig_v1` 概率按比赛日单独归档；首次与最近快照不互相覆盖，不将赛后快照冒充赛前记录。
4. 更新 `.github/workflows/tplus-pipeline.yml`：保留之前已经成功的测试/Feed/预测/五玩法逻辑；增加历史审计测试和每日留档；生成的归档文件一起提交至 `main`。付费 AI 调用默认仍为 `0`，不会未经确认地自动付费。
5. 增加两个测试文件，核对58注SP、票面理论返奖、模型与赛果隔离规则、赛前留档。8项新测试均已在本地运行通过；网页9个栏目及58注渲染已通过模拟数据交互测试。

## 上传方法：两个位置、两次提交

**第1次（仓库根目录）**

1. 解压 ZIP，看到 `docs`、`tests`、`tplus_cloud`、`.github` 四个目录。
2. 打开 `https://github.com/Kangdewo/jingcai-live`，分支保持 `main`；点击 `Add file` → `Upload files`。
3. **只把解压目录中的 `docs`、`tests`、`tplus_cloud` 三个文件夹和 `TPLUS_V3_上传与验收说明.md` 拖到仓库根目录上传页**。不要拖入 `.github`（Chrome可能会忽略以点开头的文件夹，导致 `workflows/` 被放在错误的位置）。不要把 ZIP 文件上传，也不要把最外层的文件夹名作为目录上传。
4. 提交前检查上传列表应是：
   - `docs/index.html`（替换）
   - `docs/data/reviews/2026-10-26.json`（新增）
   - `docs/data/daily/index.json`（新增）
   - `tplus_cloud/archive_daily.py`（新增）
   - `tests/test_daily_archive.py`（新增）
   - `tests/test_historical_review.py`（新增）
   - `TPLUS_V3_上传与验收说明.md`（新增）
5. 填写 `Integrate T+ daily history and ticket review v3`，选择直接提交到 `main`，点击 `Commit changes`。

**第2次（工作流正确目录）**

1. 打开 `https://github.com/Kangdewo/jingcai-live/tree/main/.github/workflows`。
2. 点击 `Add file` → `Upload files`，**只上传补丁的 `.github/workflows/tplus-pipeline.yml` 这个文件**，替换同名文件。
3. 直接提交到 `main`：`Archive pre-match T+ snapshots and validate historical tickets`。

**必须先完成第一次，再完成第二次。** 如果第一次未提交完，就不要改统一工作流。

## 验收

1. `https://github.com/Kangdewo/jingcai-live/actions/workflows/tplus-pipeline.yml` → `Run workflow` → 分支 `main` → 再点 `Run workflow`。
2. 绿色 success 后，打开 `https://kangdewo.github.io/jingcai-live/`，按 Ctrl + F5。
3. 导航应出现9栏，点击“昨日复盘”应出现4场比分与5玩法命中核对；点击“实单账本”应显示A–G共7张票、58注、投入¥116、理论返奖¥112.25；“历史研究”应显示41,514场汇总，以及第一次流水线运行生成的赛前留档日期。
4. AI 运行状态**仍可能为 DISABLED**，真实伤停/首发/xG/天气/赛果自动双源入库**仍可能为空**。这是数据和授权接口未接通，而不是网页渲染失败。

## 目前没有完成、不能用假数据填补的项目

- **正式赛果自动双源入库**：当前公开 `predictions/evaluation.json` 仍为0场。昨日4场是独立历史审计，未写入正式准确率；真正自动验收需要逐场身份证明、两个独立赛果源、完赛时间和比分一致。
- **独立AI API试验**：工作流变量 `TPLUS_ENABLE_AI` 默认0；没有经用户确认的有效API Secret、模型名与额度限制不得开启。ChatGPT对话001—005/006/007模型不会自动加入GitHub Actions。
- **球员、伤停、真实首发、xG、天气和场地坐标**：尚未有当前仓库中可合法/稳定使用的完整授权数据源。即使外部有资料，也要按赛事、球队、比赛ID及更新时间验证。绝不编造。
- **41,514场历史逐场赔率**：现在只有对外可公开的汇总，原始数据授权与时点质量不明；不能将赛后数据用作赛前特征或计算不存在的历史体彩ROI。

### 历史复盘的严格口径

- 2026-10-26 4场比分：001 1:2；002 1:1；003 2:0；004 3:2。市场基线胜平负方向3/4。
- 20:30五玩法初版：胜平负方向3/4；竞彩整数让球0/4；精确比分0/4；总进球0/4；半全场已核3场命中2场（另一场半场比分待核验）。
- 7票58注¥116投入；4注命中；票面SP理论返奖¥112.25；理论盈亏−¥3.75，ROI−3.23%。**不是实际兑奖凭证**。
- 原始票不入公开仓库。D票仅暂定与GPT-6 21:45研究版有关，其他票没有可核验证据证明属于哪一个编号模型。
