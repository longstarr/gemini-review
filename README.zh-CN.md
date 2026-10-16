# gemini-review v2.3.1

[English](README.md)

Codex 与真实 Gemini 分别提出独立基线，再进行对抗审查、实际核验及新会话终审。双方一致不等于证据。默认通过**已连接的 Edge 全自动完成 B → C → D**；当前 Codex 会话负责浏览器操作，技能不是独立后台服务，也不会安装浏览器控制器。

## 使用前提与验证范围

| 条件 | 要求 |
| --- | --- |
| 宿主 | 桌面 Codex 环境须提供兼容浏览器工具、本地文件及脚本执行能力。纯 CLI、远程容器和其他 Agent 不保证兼容。 |
| Edge | 在正确配置文件安装并连接宿主扩展，完成站点授权，按宿主要求提供 @Edge。默认 Edge 不替代首次连接、登录与授权。 |
| Gemini | 在该配置文件登录网页；账号、地区、组织政策、模式权限及额度须满足任务。不统一要求某个付费套餐。 |
| Python | Python 3.10+，依赖 `jsonschema>=4.23,<5`。创建自己的虚拟环境，不复制他人运行时。 |
| 权限 | 能读完整技能目录、执行 Python，并在任务工作区写审查记录。宿主的其他权限限制仍有效。 |
| 语言 | 中英文选择器契约有离线测试；其他语言需观察后映射 ui，AX 模式菜单语法也需适配。 |
| 实机 | 已验证 Windows 中文 Edge/Gemini 的真实 B/C/D。原生 macOS/Linux、真实英文 UI 和剪贴板备选不声称实跑。 |
| 开发测试 | Node.js 22+ 仅供 JS 离线测试；宿主已提供 JavaScript/浏览器工具时，普通用户无需另装。 |

官方说明：[浏览器连接](https://learn.chatgpt.com/docs/chrome-extension)、[技能发现](https://learn.chatgpt.com/docs/build-skills)、[Gemini 账号](https://support.google.com/gemini/answer/13275745?hl=en)、[额度](https://support.google.com/gemini/answer/16275805?hl=en)。客户端能力受分批开放及组织策略影响，目前没有经过版本矩阵验证的最低桌面应用／扩展版本。

## 安装

完整仓库内容放入用户级 `~/.agents/skills/gemini-review/` 或项目级 `.agents/skills/gemini-review/`。SKILL.md 须直接在该目录下，不能多套一层仓库目录；保留 scripts/、references/、schemas/、preferences.json。避免多个发现位置的同名副本；未显示时刷新或重启 Codex。下载安装包不要求 Git；克隆需要 Git。

在安装后的技能目录执行：

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:GEMINI_REVIEW_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
.\.venv\Scripts\python.exe -B scripts/run.py doctor
```

### macOS / Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export GEMINI_REVIEW_PYTHON="$(pwd)/.venv/bin/python"
.venv/bin/python -B scripts/run.py doctor
```

直接调用解释器，无需激活 venv 或修改 PowerShell 执行策略。缺少 Python／venv 时先按系统官方方式安装。移动目录后重新创建环境并更新设置。

变量只对当前 shell 及子进程生效。已在别处启动的桌面 Codex 不一定继承它；让宿主脚本执行环境看到同一配置，或显式使用该解释器调用技能命令，并在代理实际执行环境运行 doctor 验证。

解释器优先级：显式 `GEMINI_REVIEW_PYTHON`（须指向存在的可执行文件）→ 已存在的用户级 `.agents/runtimes/gemini-review`（Windows 为 `Scripts/python.exe`，POSIX 为 `bin/python`）→ 运行 scripts/run.py 的当前解释器。激活另一套 venv 不覆盖更高优先级设置。选中解释器出错时不自动切换或安装依赖；含空格路径需按 shell 正确引用。

`doctor` 报告实际解释器、Python 版本和 jsonschema，成功返回 0，失败返回 2。不联网、不读取 API 凭据、不检查 Edge 登录／模式／额度或授予权限；它的 `OK` 不是审查 gate 的 `READY`。分享输出前对本机路径脱敏。

## 调用

先连接 Edge 并登录 Gemini，再输入问题：

```text
$gemini-review 帮我审查这个方案及实施风险：……
```

也支持 `gemini-review`、“帮我双模型审一下这个问题”“用双专家把关这个方案”。自然语言匹配受宿主发现和调用设置影响；未自动识别时显式选择技能。关键词不能绕过浏览器挂载要求。

- B：新会话只收原始问题和共同事实，不看 Codex 方案。
- C：新会话对抗审查两份独立基线。
- D：新会话终审最终计划、异议及真实验证证据。

正常执行须有真实终审 APPROVED、匹配的本地 READY 和用户授权；不是正确性保证，也不扩大工具权限。见 [SKILL.md](SKILL.md) 和 [协议](references/protocol.md)。

发行版默认 Edge/web、禁用 API，`requested_gemini_web_model` 为 null。按页面选择并记录实际可用模式；null 不证明模型身份。指定模式不可用时报告、恢复或获取明确变更，不静默降级。默认无需 Gemini API Key；可选 API 另行授权，不属于本次真实浏览器验证范围，网页会员也不代表 API 权限。升级时保留用户自己的偏好。

默认 C/D 合计三轮，B 不计；失败的已尝试审查也消耗轮次。只有用户明确授权增加后，才调用 `python -B scripts/run.py web budget --run-dir RUN --max-rounds 5 --reason "用户明确授权额外两轮"`。先解决当前尝试；命令保留已消耗轮次、失败历史及原因，不能释放未知发送。直接 gate 须传相同的 --max-rounds，web finish 会自动使用日志中的预算。原因文字是操作者记录，不是人类授权的密码学证明。

## 排障

| 表现 | 检查与处理 |
| --- | --- |
| 未发现技能／未自动触发 | 发现路径、目录层级、启用状态；显式选择技能。 |
| 装过依赖仍缺包 | 在代理实际环境运行 doctor，将依赖装入选中的解释器或更正变量。 |
| Edge 手动可用，代理却找不到 | 扩展／宿主连接、配置文件、@Edge、站点授权和管理员策略。 |
| request-header policy 错误 | 先查浏览器连接和策略，再按自身网络政策检查代理、DNS、TUN/fake-IP；它们只是可能原因，不自动关闭保护或改代理。 |
| 上传缺少 file URL 权限 | 是上传路径的条件性权限；可改合适的已授权正文内联，冻结前纳入材料，不偷偷扩权。 |
| 40 秒无响应／工具重置 | 观察原标签；超时不证明失败或完成，未知发送不重复点击。 |
| 登录、验证码、额度、模式变化 | 保存状态，恢复条件或取得明确变更；不绕过、不静默换模型。 |
| 可见 JSON 校验失败 | 代码块外的 Markdown 可能改变转义；要求完整 JSON 代码块，不手改字段，不把空剪贴板当成功。 |
| lock 文件残留 | 进程退出会释放内核锁；文件存在不代表死锁，不删锁抢占运行中的任务。 |

大任务受宿主/Gemini 输入输出限制和额度约束。单条原始证据序列化后超过 131072 字符会拒绝打包，不静默截断；保留来源清楚、相关且可检查的证据。失败记录仍保留，见 [恢复说明](references/browser-automation.md)。

## 测试、隐私及升级

将 python 替换为已配置的实际解释器：

```sh
python -B -m unittest discover -s scripts -p 'test_*.py' -v
node --test scripts/test_browser_bridge.js scripts/test_browser_ax_bridge.js
python -B scripts/audit_package.py .
```

原 v2.3 有 101 项测试，本补丁增加本地诊断与审查预算回归。离线浏览器夹具不调用 Gemini，不能证明真实服务或原生跨平台浏览器可用；仓库没有云端 E2E 运行器或自动发布器。

发送 Gemini 前检查源码和日志是否可披露。不要提交 work/、执行日志、凭据、.env、虚拟环境、缓存、安装备份；忽略规则不是完整防泄漏，仍须检查暂存清单。公开 issue 只提供脱敏最小复现及系统、Python、宿主／扩展版本、UI 语言，不贴私人审查原文。

.gitattributes 统一 LF，避免 Git 换行转换破坏哈希。自举升级在独立候选中修改，绑定完整清单，终审后再次核验，保留偏好和已核验备份。两步目录改名加异常回滚是可恢复事务，不是跨平台单次原子交换。

[MIT License](LICENSE)。本项目不是 Google 或 OpenAI 官方产品。
