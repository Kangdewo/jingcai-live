# T+ 单场比赛情报中枢 v0.5 — 隔离开发包

**状态：已编写本地可运行的基础数据合同/媒体统计骨架和测试；未部署到GitHub；尚未自动抓取新闻、赛果、首发、身价或调用LLM。**

本包为增量模块，不替换已运行的 `tplus_predict`、`tplus_cloud`、`odds_latest.json`，不启用GitHub Actions，更不修改T v6.5。

## 当前包含

- `TPLUS_MATCH_INTELLIGENCE_SPEC_CN.md`：比赛信息全字段、来源方案、媒体风向方法、逐阶段验收。
- `tplus_intelligence/core.py`：时间检查、报道去重、独立来源统计、事实缺失显式标注。
- `tplus_intelligence/cli.py`：将事先核验/标注好的JSON合并为单场研究档案。
- `tests/test_tplus_intelligence.py`：11个独立单元测试（可直接运行）。
- `examples/synthetic_input.json`：**完全合成演示，不是真实比赛或真实新闻。**
- `prompts/news_assessor_zh.md`：将来接入真实LLM审核器时的提示词模板。

## 本地验证

在解压后的目录中打开命令提示符，运行：

```powershell
py -3 -m unittest discover -s tests -p "test_tplus_intelligence.py" -v
py -3 -m tplus_intelligence.cli --input examples/synthetic_input.json --output output/match_dossier.json
```

输出文件应有 `coverage.verified_as_of=0` 和 `media.independent_origins_verified=1`：两个模拟转载站点，只能算作一个独立来源。

## GitHub 安全上线步骤（先隔离，再审核）

1. 提交当前文件到一个新分支，使用Pull Request检查；不要复制旧工作流覆盖现有 `.github/workflows/`。
2. 首先运行单元测试；明确真实数据源许可、账号和匹配ID。
3. 新增合规数据接入适配器，分别检查队史/积分/球员新闻/身价/转会/伤停覆盖率。
4. 接入结构化AI逐篇评审器，保存证据、prompt版本及审核标签，不给出无依据胜负概率。
5. 影子模式积累数据，评估相较于赔率基线是否具有样本外增量，再决定是否引入001—005正式模型。

当前GitHub连接器尝试创建分支、写入文档返回403 `Resource not accessible by integration`；因此本包仅在本地可验证，不能声称仓库已更新。
