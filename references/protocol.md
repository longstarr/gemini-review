# 协议、证据与 gate

所有协议数据使用 `gemini-review/2`；v2.3 保持旧记录兼容。`schemas/` 为权威字段定义：plan 与 baseline 共用结构，baseline 文件是 plan 的本地引用；`workflow.schema_for()` 展开此引用用于模型请求，不获取远程 Schema。

## 记录

- plan：问题哈希、版本、方案、稳定 critical_assumptions 与 failure_modes。可选 task_kind（默认 implementation）及 source_manifest。源码清单用相对路径和 SHA-256，gate 提供 --source-root 后逐项核验；它不等于完整依赖封存。
- review：task_id/request_id/plan_sha256/round/phase、complete、blockers、verification_requests、divergences、critical_assumptions_checked、verdict 与 END_REVIEW。当前计划的全部假设编号必须各出现一次，证据只引用当前计划日志。
- check：实际时间、方法、目标、预期、观察、状态、假设 ID、原始产物路径及哈希。产物必须在日志目录内。command 的退出码必须为 0 且未超时；断言须实际证伪所列主张，空成功不能替代验证。
- web 来源至少一个 HTTP(S) URL、访问时间、支持范围和限制；literature 至少两个不同来源。来源元数据不能证明实际访问或内容真实，仍由 Codex 核查并保存工具原文。
- receipt：真实接入、来源、可见模式、新上下文和完成观察、回复字节哈希。人工转贴必须标 manual，身份无法独立验证时明确说明。

严格拒绝重复键（包括 Unicode 转义后的同名键）、非标准常量、未知字段与不完整对象。JSON 提取仅剥离外围文字/围栏：多个顶层对象、有歧义、非法语法均拒收，不按“哪个像 APPROVED”择取。

## 常用命令

```text
python -B scripts/run.py hash plan-final.json
python -B scripts/run.py check --plan plan-final.json --id E1 --assumption A1 --expected "asserted behavior" --out logs/E1.json --cwd project -- python -B meaningful_test.py
python -B scripts/run.py gate --question question.txt --plan plan-final.json --review review-final.json --receipt receipt.json --check logs/E1.json
```

每次使用新日志文件。check 使用 shell=False、UTF-8，保存实际输出与超时状态；脚本不能判断测试的语义覆盖范围。发送日志前审查隐私；超过单条 131072 字符的证据拒绝打包，要求有来源的精简证据记录，绝不静默截断或用哈希冒充原文。

审查轮数默认三轮；仅用户明确增加后，网页可用 `web budget --max-rounds N --reason ...` 留痕调整。既有轮次、请求和失败记录保留，不靠新建 run 或清零绕过未知发送。web finish 使用该预算；独立 gate 的 --max-rounds 须与授权相同。

## 研究签字例外

仅 research/planning 可对确实无法验证的前提建立 waiver，列当前计划哈希、假设 ID、风险、advisory_only 或 bounded_research 范围。用户原文须包含署名、真实哈希、各编号和“同意放行”或 ACCEPT_UNVERIFIED，原文及哈希一并留档。笼统赞同、模型推荐和配置豁免功能都不是具体签字。版本改变即失效。

终审保留 CONDITIONAL_PASS，请求状态 USER_ACCEPTED_UNVERIFIED 引用 waiver ID；gate 或 web finish 加 --waiver。READY_WITH_WAIVER 列出未验证项，不把它们变成 PASS；真实 blocker、失败检查、REJECTED 和 implementation 不能豁免。

## 可选 API

只有用户明确启用 API 后才允许 --send、读取 GEMINI_API_KEY 或 key-status。无历史 Interactions 请求不传 previous_interaction_id，不附工具、不自定义 temperature。默认 dry run 零网络，不自动重试可能计费的超时/429/5xx，不静默换模型。仅 status=completed 且严格校验成功才接收；完整原文始终保留。API 可用性与模型支持须在实际使用时核实，不能用网页会员推断。

```text
python -B scripts/run.py api --model ACTUAL_MODEL --kind baseline --system system.txt --prompt request.txt --out-dir dry-run
```

只有 APPROVED、完整身份/哈希/收据匹配、全部前提有相关 PASS、所有核验请求有覆盖证据且轮数有效，gate 才给 READY。脚本仅提供本地预检，不是不可绕过的授权执行器。
