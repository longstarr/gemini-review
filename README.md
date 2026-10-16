# gemini-review v2.3.1

[中文说明](README.zh-CN.md)

## 给 AI 的答案，找一个会挑刺的搭档

AI 的方案看起来头头是道，真要照着做，心里还是没底：**它有没有漏掉关键问题？**

于是，我把 **Codex + Gemini 的交叉审查流程**做成了一个开源技能：`gemini-review`。

你提出问题，Codex 通过已连接的 Edge，把方案交给真实的 Gemini 网页端审查，自动完成这三步：

1. **先各自想。** Codex 和 Gemini 分别给出思路；Gemini 先不看 Codex 的答案，保留独立视角。
2. **再互相挑刺。** 对照两份方案，追问隐藏前提、失败场景和遗漏的风险，把异议留下来。
3. **最后换新会话把关。** 带着修改后的方案、未解决的问题和验证记录，交给新会话终审。关键前提仍要通过查资料、运行代码或测试等方式核验。

代码准备上线、开源项目准备发布、技术方案准备落地时，都可以先多走这一遍。审查结果会说明依据、风险与待验证事项，方便你判断下一步。

🔎 **两个 AI 都同意，也可能一起漏掉问题。** 这个项目想做的，是让质疑和验证更有章法；重要决定仍需要你判断。

完成[安装与环境配置](README.zh-CN.md#安装)后，在 Codex 中这样试：

```text
$gemini-review 帮我审一下这个方案，重点找出我没想到的风险：……
```

**使用前要准备：** 支持兼容浏览器工具的桌面 Codex、已连接的 Edge、可用的 Gemini 网页账号，以及 Python 3.10+ 和项目依赖。默认无需 Gemini API Key；网页额度和模式权限仍受账号限制。目前真实浏览器流程已在 Windows 中文环境验证，其他环境的验证范围见下方。

项目采用 MIT 许可证开源。欢迎试用，也欢迎带着脱敏后的真实案例提 Issue，一起把它打磨得更好用。

---

A Codex skill for independent Codex/Gemini baselines, adversarial review, evidence checks and a fresh final review. Model agreement is never evidence. The default is **automatic B → C → D through a connected Microsoft Edge browser**. The active Codex chat controls the browser; this package does not install a browser controller or run as a background service.

## Requirements and support

| Component | Requirement / verified scope |
| --- | --- |
| Host | A desktop Codex environment exposing compatible browser tools, local files and script execution. Installing the skill does not grant these capabilities. CLI, remote containers and other agents are not assumed compatible. |
| Edge | Complete the host's browser-extension connection in the correct profile, site authorization, and @Edge selection when required by the host. |
| Gemini | Sign in at gemini.google.com/app in that profile. Account, region, organization policy, available modes and quota must permit the task. No particular paid plan is universally required. |
| Python | Python 3.10+ and `jsonschema>=4.23,<5` from requirements.txt; create your own venv. |
| Permissions | Read the complete skill directory, execute Python, write task-workspace audit records. Additional host permissions remain in force. |
| UI language | Chinese and English selector contracts have offline tests. Other languages require observed `ui` mappings; AX mode-menu syntax also needs adaptation. |
| Live platform | Real B/C/D has been exercised on Windows with a Chinese Edge/Gemini UI. Native macOS/Linux, live English UI and clipboard fallback are not claimed verified. |
| Developer tests | Node.js 22+ for JS adapter tests only; ordinary users need not separately install it when the host supplies JavaScript/browser tools. |

See official [browser setup](https://learn.chatgpt.com/docs/chrome-extension), [skill discovery](https://learn.chatgpt.com/docs/build-skills), [Gemini account requirements](https://support.google.com/gemini/answer/13275745?hl=en) and [usage limits](https://support.google.com/gemini/answer/16275805?hl=en). Host availability can depend on rollout/workspace policy. A minimum supported desktop/extension build has not been established by a version matrix.

## Install

Put the complete repository contents in user scope `~/.agents/skills/gemini-review/`, or project scope `.agents/skills/gemini-review/`. The directory must directly contain SKILL.md, scripts/, references/, schemas/ and preferences.json; avoid an extra nested repository directory. Avoid duplicate same-name skills in discovered locations. Refresh/restart Codex if the skill does not appear. Git is optional when using an extracted repository download.

Run these commands **from the installed skill directory**:

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

Direct interpreter calls require neither venv activation nor a PowerShell execution-policy change. Install OS Python/venv support first if missing. Recreate the venv and update its setting if you move the skill directory.

The variable applies only to that shell and its child processes. A desktop app already running elsewhere may not inherit it. Make the setting visible to the host's script-execution environment, or explicitly invoke that interpreter for skill commands; verify with doctor from the same environment the agent uses.

### Runtime selection and doctor

The launcher chooses: `GEMINI_REVIEW_PYTHON` if set to an existing executable file → existing per-user `.agents/runtimes/gemini-review` interpreter (Windows `Scripts/python.exe`, POSIX `bin/python`) → the interpreter running scripts/run.py. Activating another venv does not override higher-priority choices. An invalid selected runtime errors rather than silently switching or installing packages. Quote paths with spaces according to your shell.

`python -B scripts/run.py doctor` reports selected interpreter, Python version and jsonschema support. Exit 0 means local success, 2 means a local problem. It does not contact Google, inspect API credentials, grant permissions or verify browser/login/model/quota availability. Doctor's `OK` is **not** the review gate's `READY`. Redact local paths before sharing diagnostic reports.

## Use

Complete browser connection and Gemini login first, then invoke with your question:

```text
$gemini-review Review this design and its implementation risks: ...
```

`gemini-review` and natural-language requests for two-model review are also supported. Implicit discovery depends on the host's skill matching/settings; explicitly select the skill if it is not chosen. A trigger cannot bypass browser connection or @-mention requirements.

- **B:** a new conversation receives the original question/common facts, without Codex's baseline.
- **C:** a new conversation challenges both independent baselines.
- **D:** a fresh conversation reviews the final plan, all objections and actual verification evidence.

Every critical premise needs relevant checks. Normal execution requires a complete real final Gemini `APPROVED`, matching local `READY`, and user authorization. This is not a correctness guarantee or a new tool permission. See [SKILL.md](SKILL.md) and [protocol](references/protocol.md).

preferences.json ships with Edge/web default, API disabled and `requested_gemini_web_model: null`. Select and record an actually visible available mode; null does not verify model identity. Report an unavailable configured mode instead of silently switching. No Gemini API key is needed by default. Optional API use requires separate authorization and is outside the live browser validation scope. Preserve user preferences when upgrading.

The default C/D review budget is three rounds; B does not count. Failed attempted reviews still consume rounds. Only after explicit user authorization may the agent record a larger limit with `python -B scripts/run.py web budget --run-dir RUN --max-rounds 5 --reason "User explicitly authorized two extra rounds"`. Resolve the active attempt first. The journal preserves consumed rounds, failure history and the reason; this command cannot release an unknown send. Use the same limit with a direct `gate --max-rounds` call; web finish forwards the journal's limit automatically. A reason string records the operator's assertion, not cryptographic proof of human authorization.

## Troubleshooting

| Symptom | Check / expected behavior |
| --- | --- |
| Skill missing / natural language not recognized | Discovery path, direct SKILL.md placement, enabled state, explicit invocation. |
| jsonschema missing despite installation | Run doctor in the agent's environment; install requirements into its selected interpreter or correct GEMINI_REVIEW_PYTHON. |
| Edge installed but unavailable to Codex | Host/extension connection, correct profile, @Edge, site permissions and organization policy. |
| `Unable to load browser request-header policy` | Check browser connection/policy before blaming JSON. Proxy, DNS or TUN/fake-IP are possible factors, not a diagnosis. Follow your network policy; the skill does not change proxies or disable protection. |
| File upload lacks file-URL permission | This permission is conditional on upload, not mandatory for every user. Authorized inline text can be used when suitable, frozen before sending; do not silently broaden permissions. |
| Slow page / tool timeout | Observe the original tab. Forty seconds is not proof of failure or completion. Unknown sends are never blindly repeated. |
| Login, CAPTCHA, quota or changed mode | Pause and restore the condition or obtain explicit mode-change authorization; do not silently continue on a cheaper model. |
| Visible JSON rejected | Markdown outside a code block can alter escapes. Request a complete JSON code block; never hand-repair a review or count an empty clipboard as success. |
| Lock file remains | Kernel locks release on process exit; a file alone is not a deadlock. Do not delete it to steal a live run. |

Host/Gemini input/output limits and quotas still bound large tasks. A single serialized raw evidence artifact over 131072 characters is rejected rather than silently truncated. Supply relevant inspectable evidence. Failed attempts remain recorded; see [browser recovery](references/browser-automation.md).

## Tests and privacy

Use the configured interpreter for Python commands:

```sh
python -B -m unittest discover -s scripts -p 'test_*.py' -v
node --test scripts/test_browser_bridge.js scripts/test_browser_ax_bridge.js
python -B scripts/audit_package.py .
```

The original v2.3 suite has 101 tests; this patch adds local diagnostic and review-budget regressions. Synthetic browser tests make no Gemini requests and do not prove native cross-platform browser availability. No cloud E2E runner or automatic publisher is bundled.

Review what you send to Gemini, especially private code/logs. Do not commit work/, execution logs, credentials, .env files, venvs, caches or installation backups. Ignore rules are not complete data-loss prevention: inspect the exact staged tree. Public issues should contain only a minimal redacted reproduction and OS/Python/host/extension versions and UI language.

.gitattributes enforces LF checkouts to preserve source-manifest hashes across Git settings. For self-upgrades, use an independent candidate, bind the complete reviewed tree, verify before installing, and preserve preferences/verified backups. Two directory renames with exception rollback are a recoverable transaction, not a portable single atomic exchange.

MIT licensed; see [LICENSE](LICENSE). Not an official Google or OpenAI product.
