# 浏览器自动化与恢复

使用用户点名的已连接浏览器；优先 Edge，实际绑定 ID 来自工具清单。操作前读当前浏览器/电脑工具说明；不要启动第二个浏览器、读取 cookie、复制登录状态或猜测内部接口。

## 单步收发

```text
python -B scripts/run.py web init --run-dir RUN --question question.txt --plan plan-codex-v1.json
python -B scripts/run.py web queue --run-dir RUN --phase B
```

queue 生成 prompt.txt 与 browser-request.json。每个 B/C/D 新建空白 Gemini 会话，观察实际输入框、模式菜单及无消息历史，再 web attach --tab-id ID --source-url URL --model-observed LABEL --fresh-context-observed。只按页面显示记录模式，不用模型自述推断版本；用户指定的模式缺失时报告，不静默替换。

读取可信本地 browser_bridge.js 的函数声明，用 `createGeminiWebBridge(browser, ui)` 管理 DOM；ui 必须来自新近真实 DOM，名称支持字符串、正则或中英候选数组。选择器需限定用户消息、模型回复、本轮正文与复制按钮。富文本读取优先 contenteditable 的 innerText，普通表单读取 value，保留有意义空白；完整输入必须与冻结消息一致，仅允许 CRLF/LF 规范化。差异时重新填写或观察 DOM，不折叠空白来绕过哈希。

Playwright 不可用或慢时，使用 browser_ax_bridge.js 的 `createGeminiAxSession(request, tab, journalItem, geminiUtf8Sha256, ui)`；同时载入 browser_bridge.js 的公共 JSON 与模式函数。AX 默认支持中文/英文，从绑定记录提取实际模式名或由 ui.mode 指定；覆写不得与绑定模式冲突。DOM 切换到 AX 时可解析完整模式控件标签，收据仍保留原绑定值，防止合法恢复因标签缩写而被拒。其他语言须观察后映射。原始 AX 文本不是结构化 DOM，节点边界含糊或正文无法单值完整读取时拒绝，改用官方 DOM/本轮复制通道，不手拼节点或修补转义。

AX 每次只做一个 UI 操作：inspect → draft → inspect → 本地 web sending → send → inspect。发送前重新检查完整草稿与可见模式；任何 UI 操作后重新观察，不复用失效编号。慢通道给单步调用合理超时（如 60 秒），不把多个二十余秒操作堆在一个调用。40 秒未响应不能证明失败或完成；工具超时/重置后先重新绑定原标签并观察，发送结果未知绝不再点击。

发送前 `web sending` 必须先成功落盘。恢复 SENDING/SEND_UNKNOWN 的 AX 实例只能观察，不能 draft/send。QUEUED 且没有 send_intent_at 可用 adoptFresh（DOM）恢复，必须核对同一请求哈希/标签与空历史。

## 接收与阶段推进

本轮用户回显含正确 task/request ID、仅一组消息、停止控件消失、本轮复制控件可见、正文经两次真实读取一致、JSON 协议及身份正确，才可 capture。首行 Sentinel 防止长消息折叠隐藏 ID；它只证明回显绑定，不证明完整 prompt 未变，发送前仍需全文核对。

capture 原样保留单一完整文本值、UTF-8 SHA-256、实际 URL/标签/模式和完成信号。JSON 可带外围文字/围栏及字符串内嵌代码块；多个对象、截断或非法语法拒收。可选“复制代码”通道的剪贴板必须非空且与当前文本解析结果一致，不能声称未实测平台可用。

```text
python -B scripts/run.py web accept --run-dir RUN --capture capture.json
python -B scripts/run.py web queue --run-dir RUN --phase C --check logs/E1.json
python -B scripts/run.py web queue --run-dir RUN --phase D --plan plan-final.json --ledger ledger.json --check logs/E1.json
python -B scripts/run.py web finish --run-dir RUN --check logs/E1.json
```

D 为新会话，每次修订都重新核验受影响证据。source_manifest 计划在 finish 加 --source-root；研究签字例外加 --waiver。本地进程锁防并发写，进程退出自动释放；残留 lock 文件不是死锁，不要删锁抢占。accept 在 response/receipt/state 间中断时，可从原回复继续接收；已有不同字节的产物绝不覆盖。

## 用户明确授权的轮次调整

默认 C/D 合计三轮，已尝试的失败请求也计数。只有用户明确增加预算后，先解决当前尝试，再调用 `python -B scripts/run.py web budget --run-dir RUN --max-rounds 5 --reason "用户明确授权额外两轮"`。命令记录旧值、新值、时间和原因，不清零 rounds/failures，不释放活动或未知发送；终止为 unresolved 的 run 不能用改预算恢复。web finish 自动将预算传给 gate；直接 gate 须显式给相同 --max-rounds。授权原文另行留档，原因字符串本身不能证明用户真的授权。

## 失败终态

- 未发送：`web abort --reason ...` 只接受没有发送意图的 QUEUED，可用新 request_id 重新排队。
- 已观察到完整结束但内容不可用：保留真实 capture，以 `web abandon --capture capture.json --reason ...` 归档该次尝试，允许新请求；失败/轮次不清零，不重用原 request_id。
- 发送未知且标签不可恢复：`web abandon --reason ...` 结束该 run 为 ABANDONED_UNRESOLVED，禁止本 run 自动重发。这是明确可交付终态；不能把标签关闭视为服务端已停，也不能换 run 规避未知发送限制。
- 格式拒收先对原回复最多再抓两次；可恢复失败用 `web failure --category recoverable` 记录。连续三次后提供人工备选，默认偏好不自动改变。登录、验证码、额度或策略用 blocked，未知发送用 send_unknown。

## 通道排障

`Unable to load browser request-header policy` 出现在页面请求前，不能归因于 Gemini JSON。先核实本次已挂载 @Edge、扩展连接及正确配置文件，读取官方故障说明；记录浏览器通道错误与页面是否可观察。代理/TUN fake-ip 只是可能原因，未经网络诊断不能断言。由用户按其网络策略检查解析、代理及官方服务可达性，不自动关闭保护或改策略。

上传提示扩展缺少 file URL 权限时，不自动扩权；可改为已授权的正文内联，明确记录传输变化并在冻结前加入共同材料。Debugger unattached 可尝试官方 AX；若两者均被策略阻断，保存状态等待恢复，不访问底层端口绕过。中断待恢复标签用工具的 markHandoff 保留。

离线替身测试不证明真实服务可用性。只有本次真实 B/C/D、web receipt 及 gate 均完成才报告该次 E2E；英文 UI、其他操作系统或剪贴板路径未实跑则明确限定。
