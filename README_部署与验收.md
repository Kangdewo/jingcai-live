# T+ 统一数据中枢补丁 v2

## 这包解决什么

1. 增加 `docs/index.html`：一个有导航的统一足球数据中枢，按“总览、赛程赔率、五大玩法、历史研究、AI运行状态、赛果复盘、数据覆盖”分区展示，并精确链接公开 JSON。
2. 增加 `tplus-pipeline.yml`：单一定时流水线依次做 T 源新鲜度检查、测试、生成 Feed、预测基线、五大玩法分析，再一次性提交。
3. 把旧 Feed、预测、五大玩法工作流改为手动触发，避免它们与统一流水线同时写同一批 JSON。
4. AI Runner 默认设为启用；每轮默认最多 2 次 API 调用。若没有配置 `OPENAI_API_KEY` / `GEMINI_API_KEY`，程序不会发出 API 请求，状态应显示 `ENABLED_BUT_NO_PROVIDER_SECRETS`。如不希望产生 API 费用，在仓库工作流中将 `TPLUS_ENABLE_AI` 设为 `0`。
5. 修复 provider 调度顺序：预算允许时先对同一场比赛轮流尝试已配置的 provider，避免第一个 provider 长期占满预算。

## 重要边界

- 这个 AI Runner 只调用 OpenAI/Gemini API，对当前 T 赔率与比赛元数据进行市场基线影子实验。它**不是**用户在其他 ChatGPT 对话中使用的 001—005 模型，也不会自动唤起那些聊天。
- API 模型输出仍依赖市场赔率，不是独立于市场的球队实力预测；没有真实 xG、首发、伤停时，不能让模型编造这些字段。
- 当前公开仓库并未发布真实首发、伤停、球员统计、天气、场地坐标和已验证赛果。因此页面会把这些栏目标成未接入，而不会填假数据。
- API 调用可能产生 OpenAI/Gemini 的单独费用；ChatGPT 订阅不等于 API 额度。
- GitHub Actions 定时属于尽力触发，不保证秒级实时；页面每 60 秒刷新只代表重新读取数据，不代表上游每分钟更新。
- 本补丁没有覆盖原 `竞彩实时.html`、原始赔率文件或既有冻结文件。

## 部署方式

### 如果你有本地 `jingcai-live` Git 仓库

1. 解压本 ZIP 到临时目录。
2. 将包内的 `docs/`、`.github/`、`tplus_predict/agents.py`、`tests/test_agents_runner.py` 复制到本地 `jingcai-live` 仓库根目录，允许覆盖同名工作流文件。
3. 在仓库根目录运行：
   ```powershell
   py -3 -m unittest discover -s tests -p 'test_agents_runner.py' -v
   py -3 -m unittest discover -s tests -p 'test_autopredict.py' -v
   py -3 -m unittest discover -s tests -p 'test_ai_adapters.py' -v
   ```
4. 测试通过后提交并推送这些文件。不要提交 API 密钥。
5. 在 GitHub 仓库 `Settings → Pages` 中选择 `Deploy from a branch`、分支 `main`、目录 `/docs`。如果该设置已存在，不要重复改动。
6. 打开 `Actions → T+ unified data-to-prediction pipeline`，手动运行一次。先看工作流结果，再打开 Pages。

### 如果你没有本地仓库

把解压后的文件按相对路径上传到 `Kangdewo/jingcai-live`，覆盖同名工作流和 `tplus_predict/agents.py`，新增 `docs/index.html` 与 `tests/test_agents_runner.py`。提交后按上面第 5、6 步验收。GitHub 写入连接器当前返回 403，因此此处需要由有仓库写权限的账号完成一次提交。

## AI API 配置

工作流默认使用以下模型名，前提是仓库里有对应 API Secret：
- `OPENAI_API_KEY`（Secret）可使用默认 `gpt-6-luna`，或在 Actions Variables 设置 `TPLUS_OPENAI_MODEL` 覆盖。
- `GEMINI_API_KEY`（Secret）可使用默认 `gemini-3.8-flash`，或设置 `TPLUS_GEMINI_MODEL` 覆盖。
- 可用 `TPLUS_AI_MAX_CALLS_PER_RUN` 限制每轮最多调用次数，默认 2。

密钥只能放在 GitHub Actions Secrets，不能放入 HTML、JSON 或公开仓库。运行后看 `predictions/status.json` 的 `ai_runner_state`、`agent_requests_attempted`、`agent_predictions_saved` 和 `agent_errors`。如果状态为 `ENABLED_BUT_NO_PROVIDER_SECRETS`，表示开关已开但没有可用的密钥/模型组合。

## 1–2 小时内的验收口径

- [ ] Pages 打开后七个导航区都能切换，不出现整段空白。
- [ ] 赛程赔率区展示原始 T 的当前场次，并显示源更新时间。
- [ ] 五大玩法区核对分析与当前赛程 ID；旧数据只显示为过期，不冒充当前预测。
- [ ] AI 状态区能明确区分 `DISABLED`、`ENABLED_BUT_NO_PROVIDER_SECRETS` 和真正保存了预测的 `ENABLED`。
- [ ] 赛果区只展示 `evaluation.json` 中已验证样本；没有样本就不显示虚构命中率。
- [ ] 统一流水线至少手动成功一次，且 `model_feed/latest.json`、`predictions/latest.json`、`predictions/status.json`、`predictions/analysis_latest.json` 的时间相互匹配。
- [ ] 首发、伤停、球员、天气、场地数据需单独接入有授权的数据源后才能验收；本包不伪造这些数据，也不宣称这一部分已完成。
