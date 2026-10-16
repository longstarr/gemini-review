# 请求模板与材料去重

`web_flow.queue` 生成可直接发送的冻结消息；首行含任务/请求标识，随后是指令和紧凑 JSON。不要在发送后重写冻结消息。共同原始材料应在 B 前冻结并记录来源、哈希；B 不得含 Codex 派生意见。大规模审计可直接内联原文，或用已授权的文件上传，并核对实际传输。

## B：独立基线

根据用户原始问题及必要共同原始材料独立提出方案，不假设另一模型立场。只返回 baseline Schema 的完整 JSON，version=gemini-baseline-v1，列 proposal、稳定 critical_assumptions 和 failure_modes。未运行的测试不称已验证。

## C：反证

优先尝试证伪 current_plan，同时检查 Gemini 独立基线。不把一致意见当证据，不为反对编造缺陷。按 B/V/D 保留阻断、核验请求及分歧，说明可复核理由与修复条件。未知盲区审计类任务还需独立发现用户清单之外的问题，逐项评价对方新增发现是真问题、待证风险还是过度设计；按用户要求的数量执行。

## D：新上下文终审

审查当前最终方案及所有未解决事项，逐项判断实际证据的支撑范围。完整收到问题、两基线、最终方案、历史审查、台账与证据；相同基线与当前方案可引用同一 payload 内已有全文，不使用只有哈希而没有正文的外部引用。

仅条件满足时 APPROVED；否则 CONDITIONAL_PASS 或 REJECTED，列待解决事项。签字例外遵守 protocol，不能覆盖真实 blocker。所有 review 原样回传 header 标识，critical_assumptions_checked 恰好覆盖当前计划每个 ID 一次；baseline 的 CA 编号只能在正文讨论。evidence_ids 只用当前日志 ID。complete=true 与 END_REVIEW 只表示输出完整，不授予执行权限。

## 瘦身边界

请求用 separators=(',', ':')；当前方案与 Codex 基线字节哈希相同时以显式 ref 去重。保留所有异议与证据原文，不因先前“已通过”而省略。prompt.txt 是审计正文，browser-request.json 保留完整 prompt 以兼容独立桥接器与中断恢复；这份本地重复不增加 Gemini 的消息字符数，故不为省少量磁盘空间破坏接口。
