# B 域独立审计报告（第三轮）

- 工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v3/head-b`，detached HEAD `4f5a5a1`（`docs: 更新修复提交链与 CI 记录`）。
- 审计方式：只读；实际运行 HTTP/数据库/SSE 探针；对并发窗口与事务中间失败使用故障注入；未修改仓库、未 commit、未联网。
- Python：`/home/ubuntu/venvs/dsh/bin/python`。
- 基线（审计开始时运行）：
  - `PYTHONPATH=backend python -B -X utf8 -m unittest discover -s backend/integration -t backend` → **Ran 1208 tests, OK (skipped=9)**，132.2s。
  - `... -s backend/manager -t backend` → **Ran 222 tests, OK**，125.8s。
  - `git status --porcelain` 仅 `?? node_modules`（工作树既有的未跟踪符号链接，非本次审计产生）。
- 所有探针只写 `/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-b/`；仓库内无新增/修改文件。

## 0. 运行探针的统一命令

```bash
WB=/home/ubuntu/.hermes/cache/scratch/audit-v3/head-b
PB=/home/ubuntu/.hermes/cache/scratch/audit-v3/tmp-b
cd "$PB"
env PYTHONPATH="$WB/backend:$PB" PATH=/home/ubuntu/venvs/dsh/bin:$PATH \
  /home/ubuntu/venvs/dsh/bin/python -B -X utf8 -u <脚本名>.py
```

下文每条 finding 的“探针”给出脚本名（均在 `tmp-b/`）；输出为实际运行结果的关键行。

## 0.1 结论摘要

共 **31 条**：P1 × 5，P2 × 15，P3 × 11。

| 编号 | 级别 | 标题 | 主位置 |
|---|---|---|---|
| B3-01 | P1 | 审批卡绑定字段由 GET 可见，任何本地调用者可读后自批；`resolved_by` 只是声明（B-03R 仍成立） | `api_v085.py:314-351` / `agent_room.py:492-531` |
| B3-02 | P1 | 审批卡不随改令/取消失效：revision 与卡自身比较，`superseded` 从不写入，已取消指令的卡仍可批准 | `agent_room.py:518` / `agent_hub.py:340-343,476-480` |
| B3-03 | P1 | `stage='probe'` 由调用方控制，直接跳过 dsh/ofm/free_pool 的 `allowed_projects` 作品授权 | `provider_client.py:115-130` / `free_pool.py:160-169` / `model_gateway.py:214-215` |
| B3-04 | P1 | B-01R-4：`apply_hunks` 先提交草稿、后写 hunk/账本；第二个事务失败后正文已改、hunk 仍 pending、无法 undo、重试 conflict | `annotations.py:795-819` |
| B3-05 | P1 | 一次失败付费回退写永久 gap；`fallback_budget.reserve` 用全历史 gap + 进程全局计数，之后所有付费回退被永久拒绝 | `fallback_budget.py:11,46-47` / `costs.py:125-137` |
| B3-06 | P2 | SSE 事件模型与设计相反：审批/改令/任务变化不写 `agent_events`，`progress_signal` 等瞬态却被永久落库 | `agent_room.py:408-424` / `agent_hub.py`（无 append_event） |
| B3-07 | P2 | B-14R：fresh 回放按 `latest-seq-200` 截断，稀疏 project 只回放 257..300；溢出后的 full_reload 也补不齐 | `api_v085.py:182-188` / `agent_room.py:613-615` |
| B3-08 | P2 | 文档要求的 `after_seq` 与 `/api/chief/room/stream` 不存在；跨进程 wake 只 publish 到无人订阅的 fanout | `api_v085.py:150` / `app.py:1250-1267` |
| B3-09 | P2 | B-02R-1：count-only 护栏把 `budget_cap_cny` 每笔记 0，正数上限永不可达 | `costs.py:231-236,284-288` |
| B3-10 | P2 | 指令护栏与 AIService 双记 `request_budget`，一次逻辑调用消耗两个 `requests_per_day` | `model_gateway.py:200-208` / `ai_service.py:204,267` |
| B3-11 | P2 | 崩溃后 `reserved` 行无回收；`Attempt` 从不 `mark_dispatched`，五态在真实调用路径缺 dispatched | `costs.py:736-748,812-815` / `costs.py:368-378` |
| B3-12 | P2 | cancel 与 amend/resume 的 TOCTOU：状态检查在事务外，事务内 UPDATE 无 `status!='cancelled'` 条件，取消可被复活 | `agent_hub.py:321-343,476-480,488-495` |
| B3-13 | P2 | `cancel_directive` 漏掉 `awaiting_approval`/`paused_budget`；`resume` 也不释放 `paused_budget`，任务永久活跃 | `agent_hub.py:478-480,496-499` |
| B3-14 | P2 | running→held→release 丢原状态：第二次改令后释放变 pending；pending 任务不被 hold（X-P2-5 仍成立） | `agent_hub.py:354-358,460-462` |
| B3-15 | P2 | `/evaluate` 不传 evaluator，永远走确定性 wait_and_redo；`amendment_fallback` 卡批准后无消费者，任务仍 held | `api_v085.py:285-288` / `agent_hub.py:397-422` |
| B3-16 | P2 | 指令创建输入未校验：`max_calls=0` 变 20；`budget_cap_cny` 为 dict/list 或 `max_calls` 超大直接 HTTP 500 | `api_v085.py:259-260` |
| B3-17 | P2 | `sender_role` 默认 `author`：任何 agent 默认发帖即冒充作者，污染 chat_context/审计 | `api_v085.py:144,238` |
| B3-18 | P2 | `local_route` 否定/长句误判：`继续写所有章节`、`恢复所有角色...` 触发全局解除急停，`不要全局暂停` 触发全局暂停 | `agent_hub.py:192-204` |
| B3-19 | P2 | `approved` 用 `bool()` 弱转：缺字段=拒绝，字符串 `"false"`=批准 | `api_v085.py:346` |
| B3-20 | P2 | 工具表 `risk` 从不被读取：Level 2 DAG 可含 `request_publish_authorization`/`create_book`，不生成任何审批卡 | `agent_hub.py:32,55,126-180` |
| B3-21 | P3 | `bind_session_to_project` 直接写事件、绕过 `broadcaster.publish`，在线 SSE 收不到 `project_bound` | `agent_room.py:295-300` |
| B3-22 | P3 | `events_after`/`max_seq`/`list_tasks`/`pending_approvals` 的 session-only 过滤未统一加 `project_id IS NULL`；接入会话流即跨书 | `agent_room.py:435-436,454-455,369-370,545-546` |
| B3-23 | P3 | 默认 session=`author` 的预建书行可被任一本书认领；400 请求也先 bind 后校验 | `api_v085.py:232-234` / `agent_room.py:283-302` |
| B3-24 | P3 | 超大 `Last-Event-ID` 未钳制 → 流内 `OverflowError`；回放帧不 `ack`，溢出 marker 可能回到 0 | `api_v085.py:153-155,166-177` |
| B3-25 | P3 | 传 `directive_guard` 但 `directive_id=None` 时静默无效，不报错 | `costs.py:226` / `model_gateway.py:203-208` |
| B3-26 | P3 | `op_id` 只是标签：同一 op_id 调两次会真实调用两次、记两行，未接幂等（与 docstring 矛盾） | `model_gateway.py:189-190,203-208` |
| B3-27 | P3 | `invoke_sync` 在已有事件循环中改开线程，`costs.META.db` 不传递，真实 `usage_events` 丢失 | `model_gateway.py:247-267` |
| B3-28 | P3 | `max_chapters` 把 chapter 0 当一章；`tokens()` 对字符串不套 10^12 上限 | `costs.py:273-274,598-599` |
| B3-29 | P3 | `agent_room` 写函数不 `initialize`，新库直接 OperationalError；room 端点不校验 project 存在，ghost identity 可写 | `agent_room.py:194-210,461-477` / `api_v085.py:228-260` |
| B3-30 | P3 | 过期审批仍留在 pending 列表，只有尝试 resolve 时才置 expired | `agent_room.py:539-549` |
| B3-31 | P3 | `ProviderClient._call` 无候选时隐式返回 `None`，调用方可能当成功 | `provider_client.py:193-212` |

---

## 1. P1 详细

### B3-01 [P1] 审批卡绑定字段由 GET 可见，任何本地调用者可读后自批；`resolved_by` 只是声明（B-03R 仍成立）

**位置**
- `backend/manager/api_v085.py:314-318`：`GET /api/projects/{identity}/approvals` 返回 `pending_approvals` 全行，包含 `artifact_fingerprint`、`approved_scope_hash`、`directive_revision`、`detail`。
- `backend/manager/api_v085.py:327-330`：只有调用方主动写 `resolved_by` 且值不是 `"author"` 才 403；省略该字段直接通过。
- `backend/manager/api_v085.py:345-350`：服务端强制把 `resolved_by="author"` 写入，不校验任何作者会话/能力。
- `backend/integration/agent_room.py:498-499`：房间层的 `resolved_by != "author"` 同样只是字符串比较。
- `backend/manager/app.py`：GET 不要求 `X-Novel-Helper`；POST 只要求静态头 `X-Novel-Helper: 1`。`GET /api/projects` 无鉴权即可枚举所有 project identity/path。

**机制**
审批卡的“绑定”字段是服务端数据库里的静态值，而 GET 又把这些值原样返回给任何本地客户端。调用方只要先 GET 卡片，再把 `artifact_fingerprint`/`approved_scope_hash`/`directive_revision` 原样 POST 回来，就能通过 `resolve_approval` 的三项比较；`resolved_by` 由客户端自报或干脆省略，服务端不会也无法证明提交者是作者而不是 agent。所谓“五重校验”中，只有 pending/过期/重放是真正独立的，revision/fingerprint/scope 都是 `stored == stored`，身份校验是声明。

**影响**
- 在项目自己的威胁模型（“严禁 Agent/Worker 伪造审批”）下，agent 或任何本地进程可以自助批准发布授权、全书范围确认等高风险卡。
- `GET /api/projects` 无鉴权即可拿到书 identity；配对到局域网的设备（`--lan` 且未开 pairing 时）同样可读可批。
- 这是已登记的 B-03R-1 残余，本轮复现仍成立；不是测试通过就能豁免的问题。

**最小修复**
- 不要把可回放的绑定值直接暴露给“任意 GET”：给作者 UI 发一次性 approval capability（绑定 approval_id + op_id + 短期 nonce），POST 时验证 capability，而不是让调用方回传库内静态值。
- 服务端在 resolve 前重新计算 artifact fingerprint/scope（或至少校验卡片创建时绑定的 artifact 句柄仍存在且未被替换），不能只比较库内字段。
- 身份走本机 IPC/OS 用户/作者会话 token；不要再用 `resolved_by` 字符串或静态 `X-Novel-Helper` 头。

**探针 / 输出**
`p1_approval.py`：
```text
GET /approvals status: 200
GET exposes fields: {'id': 'apr_8d7697b1', 'artifact_fingerprint': 'fp-secret',
 'approved_scope_hash': 'scope-secret', 'directive_revision': 1, 'detail': {'chapters': [1, 2]}}
self-approve HTTP: (200, 'approved', 'author')
...
same local caller can list A's approvals via URL: ['apr_505c24c9']
```
（`GET /api/projects` 探针输出：`200 list [{'id': '6b1217a443e101ac', 'path': ..., 'title': 'book-a', ...}]`，无任何请求头。）

---

### B3-02 [P1] 审批卡不随改令/取消失效：revision 与卡自身比较，`superseded` 从不写入，已取消指令的卡仍可批准

**位置**
- `backend/integration/agent_room.py:518`：`directive_revision` 比较的是 `item.get("directive_revision")`，即卡片自己存的 revision，不是当前 `agent_directives.directive_revision`。
- `backend/integration/agent_hub.py:340-343`：`start_amendment` 只 UPDATE 指令 revision/status，不 UPDATE `agent_approvals`；`superseded` 状态在全仓从未写入（grep 为空）。
- `backend/integration/agent_hub.py:469-483`：`cancel_directive` 只取消 tasks/amendments，不 expire/supersede pending approval。
- `backend/integration/agent_hub.py:486-504`：`resume_directive` 同样不处理 approval。
- `backend/integration/agent_room.py:539-549`：`pending_approvals` 不按指令状态过滤。

**机制**
设计文档（`docs/plans/v0.8-v0.9/03_...md:240`、`:283-285`，`08_...md:131`）明确要求“改令递增后旧审批卡自动失效”“作废任何未决旧改令确认卡”。当前实现只把新 revision 写进指令；卡片的 revision 没变，resolve 时又只跟卡片自己的 revision 比，于是：
1. 指令 rev1 的 pending 卡 → 改令到 rev2 → 卡仍 pending，用 rev1 回传仍 200 approved；
2. 取消指令 → 卡仍 pending，用 rev1 回传仍 200 approved；
3. 旧改令的 `amendment_fallback` 卡也不会被新改令 supersede，会一直积在“待你决定”。

**影响**
作者在改令或取消后，旧审批仍能授权发布/全书改稿；已取消的指令仍可通过旧卡执行高风险副作用。这是审批与指令生命周期脱钩，属于授权正确性缺陷，不只是 UI 残留。

**最小修复**
- `start_amendment`、`cancel_directive`、`resume_directive` 在同一个 `write_tx` 内把该 directive 的所有 `pending` approval 置为 `superseded`（或 `rejected`，按产品语义），并写 `resolved_at`。
- `resolve_approval` 先在事务内读取 live `agent_directives`：`status == 'cancelled'` 或 `live.directive_revision != card.directive_revision` 直接 409，不要只比卡片。
- `pending_approvals`/`snapshot` 过滤掉 directive 已取消或 revision 落后的卡；补 `superseded` 状态迁移测试。

**探针 / 输出**
`p1_approval.py`：
```text
amendment HTTP: (200, 2)
live directive revision: 2
resolve card after amendment (echo card rev 1): (200, 'approved')
cancel directive HTTP: 200
approve card of cancelled directive: (200, 'approved')
```
`p5_amend.py`（取消后 approval 仍可 resolve）：
```text
approval after directive cancel: approved directive: cancelled
```

---

### B3-03 [P1] `stage='probe'` 由调用方控制，直接跳过 dsh/ofm/free_pool 的 `allowed_projects` 作品授权

**位置**
- `backend/integration/provider_client.py:116-117`（ofm_standalone）：
  `if costs.META.get().get('stage')!='probe' and (not project or project not in permitted): raise ...`
- `backend/integration/provider_client.py:128-130`（dsh_local/dsh_channel）：同样的 `stage != 'probe'` 短路。
- `backend/integration/free_pool.py:160-169`：`is_probe = meta.get('stage') == 'probe'`；probe 时跳过 `not project` 和 `allowed_projects` 两项检查。
- `backend/integration/model_gateway.py:185`：`ModelGateway.invoke(..., stage: str = "other")`；`:214-215` 把调用方传入的 `stage` 直接写进 `costs.scope`。
- `backend/manager/worker.py:68`：连接测试确实用 `@costs.attributed("probe")`，说明 probe 是正常业务阶段；但没有任何“probe 只能发连接测试固定 payload”的限制。

**机制**
`stage` 是 `ModelGateway.invoke` 的公开参数，任何调用方都可以传 `stage="probe"`。dsh_local/dsh_channel/ofm_standalone 的 `allowed_projects` 是“这本书是否允许把正文/记忆送给共享或本机渠道”的最后一道闸；`stage=='probe'` 一短接，任意 `project`（甚至 `project=None`）都能进入 `_scope`。free_pool 的 `_choices` 同样在 `is_probe` 时跳过 `allowed_projects`。

**影响**
- 一个 agent/worker（或任何能调用 ModelGateway 的本地代码）可以把未授权书的正文标成 probe，发送到 dsh 免费渠道/OFM/免费池；隐私分级和 `allowed_projects` 均被绕过。
- 这不是“本地单用户所以无所谓”：设计明确把 `allowed_projects` 当作共享渠道的硬白名单，且模型网关是给 Agent 用的公共出口。
- 当前仓库没有 HTTP 入口直接暴露 `stage`，所以是 latent；但 `ModelGateway.invoke` 是公共 API，接入 agent 后即成立。

**最小修复**
- `stage` 不得作为授权依据。probe 走独立方法（例如 `probe_connection()`），只发送固定极小 payload，且不携带 `project`/正文；或在 `_scope` 中要求一个由连接测试内部生成、调用方不可伪造的 capability。
- 对任何带 project/正文的调用，无论 stage 是什么，都必须校验 `allowed_projects`；free_pool probe 也不能跳过项目检查（最多允许 project=None 的固定探测）。
- 给 `stage` 做 allowlist，并拒绝在 `costs.scope` 外部设置 probe。

**探针 / 输出**
`p29_probe_bypass.py`（dsh_local，`allowed_projects=['/authorized/book']`，实际 project `/unauthorized/book`）：
```text
stage=draft: blocked: 此作品尚未授权免费渠道处理正文与记忆
stage=probe: entered shared dsh_local channel with unauthorized project
```
同一逻辑在 `free_pool.py:160-169` 存在（`is_probe` 跳过 `allowed_projects`），本轮未单独跑免费池网络路径，但代码路径与 dsh 完全同构。

---

### B3-04 [P1] B-01R-4：`apply_hunks` 先提交草稿、后写 hunk/账本；第二个事务失败后正文已改、hunk 仍 pending、无法 undo、重试 conflict

**位置**
- `backend/integration/annotations.py:795-816`：`chapter_editor.save_draft(...)` 独立提交草稿正文（`draft` 分支和“无草稿”分支各一次）。
- `backend/integration/annotations.py:819-841`：随后另开 `with wb.write_tx(project)` 更新 `annotation_hunks` 并插入 `patch_ledger`。
- `backend/integration/annotations.py:886-897`：`undo_apply` 只从 `patch_ledger` 找记录；没有 ledger 就 404 `ledger_entry_missing`。

**机制**
草稿写入与 hunk/ledger 状态写入是两个事务。若第二个事务因进程崩溃、SQLite 锁超时、磁盘错误等失败，草稿已经包含候选文本，但 hunk 仍 `pending`、`patch_ledger` 为空。之后：
- `undo_apply` 找不到 ledger，无法撤销；
- 用新 op_id 重试，`text_merge` 看到当前正文已经包含候选文本，返回 `conflict`/`applied=[]`，hunk 永远 pending；
- UI 显示“待采纳”，但正文已改，状态与正文永久分叉。

这是父任务点名的 B-01R-4； remediation 也把它列为“部分 P2”，但本轮故障注入显示后果是**不可恢复**，不只是窗口不一致。

**影响**
一次第二个事务失败（不必是整机崩溃，DB 锁超时即可）会让该 hunk 永久卡在 pending，作者无法通过 API 撤销或重新采纳；后续 apply 的 ledger 也缺这条记录，可能造成更多冲突。属于状态/正文分叉，需要手工修 DB。

**最小修复**
- 让 `save_draft` 与 hunk/ledger 更新共享同一个 `wb.write_tx`（给 `save_draft` 增加“在既有事务内写入”的入口），或先写一个 `patch_apply_intent` 日志（base snapshot、draft_id、hunk ids、op_id），再提交草稿；失败时由启动/下次 apply 根据日志对账：正文已是 `applied_text` 就补写 hunk/ledger，否则回滚草稿。
- `apply_hunks` 的失败补偿应显式回滚刚保存的草稿到调用前内容（带 revision CAS），不能只 `_idempotency_fail`。
- 给 ledger 增加 `op_id` 唯一键，重试时按 op_id 幂等补齐而不是报 conflict。

**探针 / 输出**
`p18_apply_atomic.py`（在 `save_draft` 返回后、hunk/ledger 事务入口抛错）：
```text
apply failed: simulated crash before hunk/ledger commit
draft after crash: '开头。\n她轻轻推开门。\n结尾。\n'
hunk after crash: pending
ledger rows: 0
undo after crash raised: AnnotationError ledger_entry_missing
retry status: conflict applied: [] clean: False
draft after retry: '开头。\n她轻轻推开门。\n结尾。\n'
hunk after retry: pending
```

---

### B3-05 [P1] 一次失败付费回退写永久 gap；`fallback_budget.reserve` 用全历史 gap + 进程全局计数，之后所有付费回退被永久拒绝

**位置**
- `backend/integration/fallback_budget.py:11`：`if not db_path or not project or costs.ledger_gaps(db_path) or costs.MISSED_EVENTS: raise ValueError('成本记录不完整，禁止自动付费回退')`。
- `backend/integration/fallback_budget.py:46-47`：`settle` 对 `not selected` 或任一事件 `cost_cny is None`/`metering != 'reported'`/`status == 'pending'` 一律 `costs.record_gap('fallback_settlement_unknown')`。
- `backend/integration/costs.py:125-137`：`record_gap` 只增 `MISSED_EVENTS` 并写 `.gaps/*.json`，从不清理/标记解决。
- `backend/integration/costs.py:137-155`：`ledger_gaps` 的 `within_hours` 只被 `report()` 使用；`fallback_budget` 调用的是无窗口版本。
- `backend/integration/costs.py:885`：`report` 的 `missed_events = max(gaps_recent, MISSED_EVENTS)` 还是进程全局值。

**机制**
任何一次付费回退请求失败（网络错误、流中断、供应商未返回 usage、settle 时事件仍未 `reported`）都会写一个 gap。之后：
1. `fallback_budget.reserve` 用 `costs.ledger_gaps(db)`（全历史）或 `MISSED_EVENTS`（进程全局），一次失败就永久拒绝所有后续付费回退；
2. `report()` 已经按 24h 窗口判断 `complete`，所以会出现“报表 complete=True，但付费回退永久被拒”的自相矛盾；
3. 即使删掉 gap 文件，`MISSED_EVENTS` 仍然 >0，直到进程重启；重启后若 gap 文件还在仍拒绝；
4. `MISSED_EVENTS` 是进程全局，A 书的一次失败会拒绝 B 书的回退。

**影响**
付费回退是主通道故障/限流时的恢复路径；一次普通网络失败就会让它在无 UI 提示的情况下永久失效。触发频率高（回退本身就是在故障时使用），属于“恢复路径自毁”。

**最小修复**
- gap 要可解决：记录 `resolved_at`/`kind`/`project`，或按 24h 窗口/最近 N 次判断；`fallback_budget.reserve` 与 `report` 使用同一判据。
- 对“已确认未计费”的失败（Attempt released、无 cost）在 `settle` 里把 fallback reservation 标 `cancelled`/`unknown`，不要写全局 gap。
- 把 `MISSED_EVENTS` 改为按 DB/project 的计数，或至少让 fallback gate 只看该 project 的近期未解决 gap。
- 提供 UI/维护操作清除已解决 gap，而不是让用户手工删文件。

**探针 / 输出**
`p17_fallback_gap.py`（48 小时前的旧 gap）：
```text
report complete with old gap: True
gaps total / recent: 1 0
fallback reserve refused: 成本记录不完整，禁止自动付费回退
MISSED_EVENTS: 1
```
`p19_fallback_poison.py`（一次失败回退的正常 settle）：
```text
gap files before/after failed fallback settle: 0 1
second reservation refused: 成本记录不完整，禁止自动付费回退
...
reserve after 48h: 成本记录不完整，禁止自动付费回退
```

---

## 2. P2 详细

### B3-06 [P2] SSE 事件模型与设计相反：审批/改令/任务变化不写 `agent_events`，瞬态事件却被永久落库

**位置**
- `backend/integration/agent_room.py:408-424`：`append_event` 无条件 `INSERT INTO agent_events`，然后 `broadcaster.publish`。
- `backend/integration/agent_room.py:27`：`TRANSIENT_KINDS = {"progress_signal", "live_preview_delta", "draft_updated"}`，但该集合只在 `BoundedBroadcaster.publish` 的溢出分支使用（`:724`），没有“只广播不落库”的入口。
- `backend/integration/agent_hub.py`：`create_directive`/`create_task`/`update_task`/`start_amendment`/`evaluate_amendment`/`cancel_directive`/`resume_directive` 全部没有调用 `agent_room.append_event`；`create_approval`/`resolve_approval` 也没有。
- 设计文档 `docs/plans/v0.8-v0.9/03_...md:301-303`： “业务成果、对话、审批、改令等持久化写入 `agent_events`”；“高频瞬态信号…仅走内存广播…绝不永久塞进 `agent_events`”。

**机制**
当前唯一的 `agent_events` 生产者是 chat 消息（API `chief_message`）和 `bind_session_to_project` 的 `project_bound`。审批卡创建/批准、改令、任务状态变化都只改各自的表，SSE 订阅者永远收不到，也无法从 `agent_events` 回放；反过来，`progress_signal`/`draft_updated`/`live_preview_delta` 这些应该只走内存的瞬态事件，却全部 INSERT 到 `agent_events`，会无限增长并挤占 `snapshot` 的 100 条/SSE 的 200 条窗口。

**影响**
- “四通道实时事件流”实际只有 `chief_chat`/`project_bound`；审批、任务、改令没有任何实时/回放事件，UI 只能轮询 snapshot。
- 高频进度事件会永久落库；在长篇生成时，`agent_events` 膨胀，`snapshot` 最近 100 条可能全是 `progress_signal`，真正的任务/审批事件被挤出窗口。
- 与设计文档直接矛盾；现有的 `TRANSIENT_KINDS` 是死配置。

**最小修复**
- 增加 `publish_transient(event)`：只 `broadcaster.publish`，不 INSERT，不分配 `seq`（或分配仅内存的负/临时 id）；`append_event` 遇到 `TRANSIENT_KINDS` 时拒绝或改走该入口。
- 在 `create_approval`/`resolve_approval`、`create_task`/`update_task`、`start_amendment`/`evaluate_amendment`/`cancel`/`resume` 内写对应的持久事件（`approval_card`、`approval_resolved`、`task_update`、`amendment_started`…），最好与状态变更同事务（outbox）后 publish。
- 给 `agent_events` 加保留/归档策略；`snapshot` 不应被瞬态事件挤占。

**探针 / 输出**
`p24_events_missing.py`：
```text
events after directive/task/approval lifecycle: []
max seq: 0
persisted progress_signal rows: ['progress_signal', 'progress_signal',
 'progress_signal', 'progress_signal', 'progress_signal']
TRANSIENT_KINDS: ['draft_updated', 'live_preview_delta', 'progress_signal']
```

---

### B3-07 [P2] B-14R：fresh 回放按 `latest_seq-200` 截断，稀疏 project 只回放 257..300；溢出后的 full_reload 也补不齐

**位置**
- `backend/manager/api_v085.py:158`：`page_size = 200`。
- `backend/manager/api_v085.py:182-188`：
  ```python
  if after == 0:
      latest = agent_room.max_seq(room_db, project_id=identity)
      start = max(0, int(latest) - page_size)
  else:
      start = after
  ```
- `backend/integration/agent_room.py:613-615`：`snapshot` 的 events 上限是 100（`min(int(limit), 500)`，默认 100）。
- `backend/integration/agent_room.py:724-738`：溢出 marker 的 `seq=last delivered`，`full_reload=True`；没有“从 0 重放全部”的服务端能力。

**机制**
`latest - 200` 假设 project 的 `seq` 是稠密的。但 `agent_events.seq` 是全局 AUTOINCREMENT，多本书共享；project A 的 seq 会与 B 的大量事件交错。只要 A 的总事件数 < 200、但 latest A > 200，fresh 客户端就会从 `latest-200` 开始，只拿到 A 的最后一小段。
- 例：A 先写 100 条（seq 1..100），B 写 156 条（seq 101..256），A 再写 44 条（seq 257..300）。A 总 144 条，latest A=300，start=100；`events_after(100, project=A)` 只返回 A 的 257..300（44 条），A 的 1..100 完全没发。
- 溢出后：若客户端尚未收到任何事件（last=0），marker `seq=0/full_reload`；它按 `after=0` 重连仍只拿 101..300（200 条），第 1..100 丢；若它按 snapshot 的 `snapshot_seq=300` 重连则 0 条，而 snapshot 只给 201..300（100 条），101..200 仍丢。**没有任何一条客户端路径能恢复 300 条历史**；`full_reload` 承诺无法兑现。

**影响**
长时间离线/慢客户端/多书共享库时，SSE 会静默丢失事件；对 `task_update`/`approval` 这类持久事件（一旦按 B3-06 补上生产者）就是任务状态/审批丢失。B-14R 的“按 full_reload 重载”在当前 snapshot 100 条上限下不成立。

**最小修复**
- fresh 页按 project 自己的事件取：`SELECT seq FROM agent_events WHERE project_id=? ORDER BY seq DESC LIMIT 1 OFFSET 199`，start 取该 seq 前一条；或直接 `ORDER BY seq DESC LIMIT 200` 再 reverse。
- 回放循环从 0 开始分页直到 latest（或提供 `after_seq` 明确从 0 开始），不要用 seq 窗口近似事件条数。
- 溢出 marker 应携带 `oldest_available_seq`/`snapshot_seq`，并让 `snapshot` 至少覆盖与 page_size 相同的事件数（或提供分页 snapshot），否则不要声称 full_reload 能恢复。

**探针 / 输出**
`p2_sse_sparse.py`：
```text
first/last A seq: 1 100 257 300
A total: 144 B total: 156
latest A: 300 start=latest-200: 100 replayed: 44 range: (257, 300)
HTTP endpoint fresh replay count: 44
HTTP endpoint first/last: 257 300
A events available: 144
```
`p8_sse_overflow.py`：
```text
overflow marker: {'kind': 'resync_required', 'seq': 0, 'full_reload': True, 'resync_required': True}
snapshot_seq: 300 events: 100 range: (201, 300)
SSE fresh(after=0): 200 range: (101, 300)
SSE resume(snapshot_seq): 0
SSE explicit after=1: 299
```

---

### B3-08 [P2] 文档要求的 `after_seq` 与 `/api/chief/room/stream` 不存在；跨进程 wake 只 publish 到无人订阅的 fanout

**位置**
- `backend/manager/api_v085.py:150`：`room_stream(identity, request, last_event_id: str = "")`，没有 `after_seq` 参数；FastAPI 会忽略 `?after_seq=`。
- `backend/manager/api_v085.py:149` 仅注册 `/api/projects/{identity}/room/stream`；没有 `/api/chief/room/stream`。
- `docs/plans/v0.8-v0.9/03_...md:298-300`：明确要求“支持 `Last-Event-ID` HTTP 请求头与 `after_seq` 参数”，并列出“未建书会话流 `GET /api/chief/room/stream?session_id=prebook_xxx&after_seq=0`”。
- `backend/manager/app.py:1250-1267`：`/internal/events/notify` 只 `fanout.publish(...)`；`app.state.event_fanout` 在启动时没有任何订阅者，`room_stream` 也只订阅 `agent_room.broadcaster`。
- `backend/manager/api_v085.py:199`：live 等待是 `queue.get(timeout=15.0)`，没有计划中的 500ms DB 短读兜底。

**机制**
1. 按文档使用 `?after_seq=1` 的客户端会被当成“无 cursor”：路由签名没有该参数，FastAPI 会忽略它，等价于空 cursor，只拿到最新 200 条；空 cursor 实测 101..300，而显式 `last_event_id=1` 才得到 2..300。
2. 零作品开书流根本不存在，预建书阶段无法实时收消息。
3. 子进程按计划写 `agent_events` 后 POST `/internal/events/notify`，事件被 publish 到一个没有订阅者的 `EventFanout`；manager 的 SSE 不会醒，也不会短读 DB，所以子进程产生的事件在 manager 的流上永远不出现（除非客户端主动重连/轮询）。
4. 这解释了为什么“四通道流”目前只在 manager 进程内 `append_event` 时有效。

**影响**
按文档接入的前端会静默丢 cursor；预建书对话无实时流；多子进程（计划中的 worker）产生的任务/审批/改令事件无法实时到达 UI。B-14R 修复只覆盖了“同进程 + 客户端带对 cursor”的情况。

**最小修复**
- 增加 `after_seq: int = 0` 参数，与 `last_event_id` 合并（header 优先，query 次之）。
- 增加 `/api/chief/room/stream?session_id=...`，内部使用 `events_after(session_id=..., ...)` 且必须加 `project_id IS NULL`（见 B3-22）。
- 让 `room_stream` 订阅 `app.state.event_fanout`（或专门的 wake Event），在 wake 时做一次短读 `events_after(after)`；或让 `/internal/events/notify` 直接调用 `agent_room.broadcaster.publish` 从 DB 取该 seq 的事件。加 500ms 短读兜底，避免只依赖进程内 publish。

**探针 / 输出**
`p25_after_seq.py`：
```text
stream with empty cursor (what ?after_seq=1 becomes): 200 (101, 300)
stream with explicit cursor 1: 299 (2, 300)
stream route: /api/projects/{identity}/room/stream ['GET']
room_stream signature: (identity: 'str', request: 'Request', last_event_id: 'str' = '')
session stream route exists: False
```
`p26_wake_orphan.py`：
```text
fanout subscriber queues at startup: 0
notify HTTP: 200 {'ok': True, 'subscribers_dropped': 0}
fanout subscriber queues after notify: 0
```

---

### B3-09 [P2] B-02R-1：count-only 护栏把 `budget_cap_cny` 每笔记 0，正数上限永不可达

**位置**
- `backend/integration/costs.py:231-236`：`count_only and amount is None` → `reserve_amount = Decimal(0)`、`unknown_cost = 0`。
- `backend/integration/costs.py:284-288`：`cap is not None and usage['cost_cny'] + reserve_amount > Decimal(str(cap))`。
- `backend/integration/model_gateway.py:203-208`：网关对 `directive_guard` 永远用 `count_only=True, cost_cny=None`。

**机制**
`count_only` 的每一行 `cost_cny='0'`；`_directive_usage_db` 把非 released 行的 `cost_cny` 相加也是 0。于是 `budget_cap_cny=1` 时，每次检查都是 `0 + 0 > 1` → False，永远不拦。`max_calls` 仍有效（用 attempts），但人民币上限变成装饰。若 cap=0，`0 > 0` 也为 False，等于无限。

**影响**
指令的 `budget_cap_cny` 在唯一的网关计数路径上完全失效；调用方以为设了 1 元上限，实际可以无限调用（只受 max_calls）。这正是 remediation 里登记的 B-02R-1 残余，本轮复现仍成立。

**最小修复**
- 二选一：count-only 时拒绝 `budget_cap_cny`（明确报“无法在无金额模式下执行人民币上限”），或为每次调用传一个保守的 `cost_per_call`/`reserve_cost`，用调用次数×单价估算。
- 更好：让网关从 `Attempt`/AIService 拿到真实 `cost_cny` 后在 `settle` 时写回 link 行，用真实金额做 cap；但这需要单行会计（见 B3-10）。
- 至少不要在 `guard` 里保留一个永远不会触发的 `budget_cap_cny`。

**探针 / 输出**
`p3_budget.py`：
```text
count-only cap=1 allowed calls: 10
directive usage: {'calls': 10, 'attempts': 10, 'chapters': [1], 'tokens': 0,
 'cost_cny': '0', 'states': {'reserved': 10, ...}}
real-cost second call blocked: 该指令费用已到上限
```
`p4_gateway_budget.py`：
```text
gateway calls with cap=1: {'calls': 10, 'attempts': 10, ..., 'cost_cny': '0', 'states': {'settled': 10}}
```

---

### B3-10 [P2] 指令护栏与 AIService 双记 `request_budget`，一次逻辑调用消耗两个 `requests_per_day`

**位置**
- `backend/integration/model_gateway.py:200-208`：注释承认“AIService already reserves ... Reserve here only when a directive-level guard...”，但 guard 分支仍插入一行 `count_only` 的 `request_budget`。
- `backend/webnovel-writer/backend/services/ai_service.py:204,267`：每次网络尝试创建 `costs.Attempt` 并 `finish`，即每 attempt 一行 `request_budget`。
- `backend/integration/costs.py:245,250`：`today_rows` 统计所有非 released 行，`requests_per_day` 用 `len(today_rows)`。

**机制**
一条带 `directive_guard` 的逻辑调用：
1. 网关先 `reserve_request(count_only=True)` → 1 行；
2. `AIService.chat` 再 `Attempt` → 1 行（重试则 N 行）；
3. 两行都计入 `requests_per_day`。
用 `requests_per_day=3` 时，第一条逻辑调用占 2 行，第二条的网关预留占第 3 行，随后 `Attempt` 预留看到 3 行已用、请求 1 → 4>3 被拒，于是**第一条逻辑调用成功后，第二条就失败**。这不是“重试多算”，而是同一逻辑调用被两个模块各记一次。

**影响**
指令护栏一开，全局请求日限额实际减半（有重试时更糟）；被拒的第二次调用还会留下一个 `unknown_charge` 网关行，进一步占额度。`max_calls` 与 `requests_per_day` 的口径不一致。

**最小修复**
- 单行会计：网关不再为 directive guard 单独 `reserve_request`；在 `costs.scope` 里把 `directive_id`/`guard` 传给 `Attempt`，让 `Attempt` 的同一行同时承担全局和指令护栏（`directive_budget_links` 绑定该 request_id）。
- 或者网关成为唯一预留者，AIService 在该 scope 下跳过 `Attempt` 的预算预留（只保留 usage 记账）。
- 保证一条逻辑调用只占一个 `requests_per_day` 槽；重试按 attempt 另计时要有明确产品口径并写进测试。

**探针 / 输出**
`p10_double_count.py`（`AttemptingService` 复刻 AIService 的 `Attempt` 会计；`requests_per_day=3`）：
```text
logical call 0: ok '好的'
logical call 1: BudgetExceeded 今日请求次数已到上限
 {'limit': 'requests_per_day', 'limit_value': '3', 'used': '3', 'requested': '1'}
request_budget rows: 3
 ('settled', 0, '0', 0, 'dc-0')
 ('settled', 20, '1', 1, '')
 ('unknown_charge', 0, '0', 0, 'dc-1')
budget_status requests_today: 3
```

---

### B3-11 [P2] 崩溃后 `reserved` 行无回收；`Attempt` 从不 `mark_dispatched`，五态在真实调用路径缺 dispatched

**位置**
- `backend/integration/costs.py:736-748`：`Attempt.__init__` 调 `reserve_request` 后 `self.persist()`；没有 `mark_dispatched`。
- `backend/integration/costs.py:785-815`：`finish` 直接 `settle_request`；没有 dispatched 转换。
- `backend/integration/costs.py:368-378`：`mark_dispatched` 只被 `model_gateway.py:212` 调用（且仅网关自己的 count-only 行）。
- `backend/integration/costs.py:245,250`：`reserved` 行被计入 `requests_per_day`/`chapter_tokens`/`project_tokens`/cost。
- `backend/integration/maintenance.py:174`：只有读取状态计数，没有恢复/清扫。
- 设计文档 `08_...md:97-103`、`03_...md:337-338`：要求 `reserved → dispatched → settled|unknown_charge`，崩溃恢复时 `reserved` 释放、`dispatched` 标 unknown。

**机制**
真实模型调用走 `AIService → Attempt`；`Attempt` 只 `reserved`，从不 `dispatched`。进程在 `finish` 前崩溃/被强杀，行永远是 `reserved`：
- 没有任何清扫函数，日/章/书限额一直被占；
- 即使以后加“恢复时释放 reserved”的清扫，由于 `Attempt` 从不 dispatch，已发出的请求也被当成“未发出”释放，少记成本；
- 反过来，现在不释放则可能永久卡额度。

**影响**
一次进程崩溃/强杀会让当日请求上限和项目 Token/费用永久被占，直到手工改库或跨日；五态预算状态机在真实调用路径上只有三态（reserved/settled/unknown_charge/released via finish），`dispatched` 永远为 0。设计中的崩溃恢复没有实现。

**最小修复**
- `Attempt` 在真正发 HTTP 之前调 `mark_dispatched`；`finish` 失败时至少保留 `dispatched`。
- 增加 `recover_stale_reservations(db, older_than)`：`reserved` 超时→released，`dispatched` 超时→unknown_charge；在 app 启动和定时任务中调用；记录 `expires_at`/heartbeat。
- `settle_request` 失败时不要只 `record_gap` 后静默，至少保留可重试状态；给 `request_budget` 加 `updated_at`/`last_attempt_at` 便于清扫。

**探针 / 输出**
`p14_stale_reserved.py`（模拟进程在 `Attempt.__init__` 后被杀）：
```text
reservation: c66764ea8a044bfc8f0eb4ac3c9f9684
after restart budget_status: {'requests_today': 1, 'pending': 1, 'dispatched': 0,
 'settled': 0, 'unknown_charge_requests': 0, 'released': 0}
second request blocked: 今日请求次数已到上限
rows: [('reserved', 1000, '1')]
recovery helper exists: []
```
`grep -n mark_dispatched` 只命中 `costs.py`（定义）、`model_gateway.py:212`、`test_costs_five_state.py:119`；`ai_service.py` 路径没有调用。

---

### B3-12 [P2] cancel 与 amend/resume 的 TOCTOU：状态检查在事务外，事务内 UPDATE 无 `status!='cancelled'` 条件，取消可被复活

**位置**
- `backend/integration/agent_hub.py:321-324`：`start_amendment` 先 `get_directive`，只在这里检查 `status == 'cancelled'`。
- `backend/integration/agent_hub.py:340-343`：随后 `BEGIN IMMEDIATE` 里 `UPDATE agent_directives SET ... status='amended' WHERE id=?`，没有 `AND status!='cancelled'`。
- `backend/integration/agent_hub.py:469-477`：`cancel_directive` 同样先 `get_directive` 再 `UPDATE ... status='cancelled' WHERE id=?`（没有条件，但取消是幂等的）。
- `backend/integration/agent_hub.py:488-495`：`resume_directive` 先检查 cancelled，随后 `UPDATE ... status='running' WHERE id=?` 无条件。

**机制**
两个请求可以交错：
1. `start_amendment` 读到 `running`（未取消）；
2. `cancel_directive` 提交 `status='cancelled'`，取消所有任务；
3. `start_amendment` 进入写事务，把状态改回 `amended`、创建 pending amendment。
反之：
1. `resume` 读到 `running`；
2. `cancel` 提交 cancelled；
3. `resume` 写 `running`，取消被覆盖。
SQLite 的 `BEGIN IMMEDIATE` 只保证写串行，不保证“读-检查-写”原子；`write_tx` 内没有重新 SELECT 或条件 UPDATE。

**影响**
作者点了取消，另一个并发的 amend/resume 请求可以把指令复活为 amended/running；任务已被 cancel，指令却 active，形成僵尸指令/待处理 amend。对“取消是终态”的产品承诺是破坏性的。当前 UI/agent 可能并发发起这些请求；无 executor 时是 latent，但状态机本身不成立。

**最小修复**
- 把检查和写放进同一个 `BEGIN IMMEDIATE`：`UPDATE ... SET status='amended' WHERE id=? AND status!='cancelled'`，`rowcount==0` 时 409；resume 用 `WHERE status!='cancelled'`；必要时 `SELECT` 当前 revision/status 重新校验。
- 对同一 directive 的 amend/cancel/resume 串行化（每 directive 的锁行或 `BEGIN IMMEDIATE` + 条件更新）。
- 补并发测试：两个线程同时 cancel 和 amend/resume，断言最终状态是 cancelled 或明确的 409。

**探针 / 输出**
`p15_cancel_race.py`（在 `start_amendment`/`resume` 的写事务入口注入一次 cancel，模拟真实并发窗口）：
```text
SCENARIO 1 (cancel then amendment write)
  amendment created: amd_957cec68
  directive after: amended revision: 2
  task after: cancelled
  amendment after: pending
SCENARIO 2 (cancel then resume write)
  resume returned: running
  directive after: running
  task after: cancelled
```

---

### B3-13 [P2] `cancel_directive` 漏掉 `awaiting_approval`/`paused_budget`；`resume` 也不释放 `paused_budget`，任务永久活跃

**位置**
- `backend/integration/agent_hub.py:478-480`：`UPDATE agent_tasks SET status='cancelled' ... WHERE status IN ('running','waiting','held','pending')`。
- `backend/integration/agent_room.py:372`：`active_only` 包含 `awaiting_approval`/`paused_budget`。
- `backend/integration/agent_hub.py:496-499`：`resume` 只释放 `status='held'`。
- `backend/integration/agent_hub.py:469-470` docstring：“Cancel a directive and every task/amendment it owns atomically.”。

**机制**
`awaiting_approval` 和 `paused_budget` 是任务状态机里的活跃状态（`list_tasks(active_only=True)` 会返回），但 cancel 的 IN 列表没有它们；resume 也不处理 `paused_budget`。于是：
- 取消后，快照仍显示该指令下有 `awaiting_approval`/`paused_budget` 任务；
- `resume` 对 cancelled 指令 409，无法恢复；
- 没有任何 API 能单独取消/恢复这两个状态（`update_task` 不暴露），任务永久悬挂。

**影响**
取消不是“取消全部”，留下活跃任务；作者看到已取消的指令仍在“进行中/待预算”，且无法清理。`paused_budget` 在预算恢复后也不会自动继续；`awaiting_approval` 的卡可能仍 pending（见 B3-02）。

**最小修复**
- cancel 覆盖所有活跃状态：`running, waiting, held, pending, awaiting_approval, paused_budget`（以及产品定义的 recovery 状态），并清 wait_reason。
- resume 对 `paused_budget` 做“重新排队”（或明确要求先补预算再 resume）；对 `awaiting_approval` 保持等待但重新检查卡状态。
- 补 cancel/resume 全状态矩阵测试。

**探针 / 输出**
`p5_amend.py`：
```text
after cancel: 等审批 -> awaiting_approval
after cancel: 等预算 -> paused_budget
after cancel: 等改令 -> cancelled
active tasks of cancelled directive: [('等审批', 'awaiting_approval'), ('等预算', 'paused_budget')]
directive status: cancelled
resume cancelled: directive_cancelled 409
```

---

### B3-14 [P2] running→held→release 丢原状态：第二次改令后释放变 pending；pending 任务不被 hold（X-P2-5 仍成立）

**位置**
- `backend/integration/agent_hub.py:352-358`：hold 时 `previous = status`（`rows` 是 `(directive_id, status)`），写入 `wait_reason = f"{previous}|已收到改令..."`，并把 `status='held'`。
- `backend/integration/agent_hub.py:460-462`：release 时 `original = reason.split("|",1)[0]`，只有 `running/waiting` 恢复，否则 `pending`。
- hold 的 WHERE 只含 `status IN ('running','waiting','held')`，`pending` 不被 hold。
- `agent_tasks` schema 没有设计文档要求的 `hold_amendment_id`/`hold_requested` 列（`workbench_db.task_queue` 有，agent_tasks 没有）。

**机制**
第一次改令把 running 写成 `held`，wait_reason 记住 `running`。第二次改令读到的 status 已经是 `held`，于是 previous 变成 `held`，覆盖 wait_reason。释放第二次改令时 `held` 不在 `{running, waiting}`，任务被置为 `pending`。原运行中的 worker 可能仍在写；pending 可被再次 claim，造成重复执行。同时，affect 的 pending 任务完全没被 hold，评估期间可以直接开跑旧方向。

**影响**
- 连续两次改令后，原 running 任务变 pending，存在双跑/重复计费风险；
- 改令期间 pending 任务不受冻结，可能在评估完成前用旧指令执行；
- 这是 remediation 明确承认的 X-P2-5（“agent_hub running 仍按 held 语义”），本轮仍复现。

**最小修复**
- 给 `agent_tasks` 增加 `hold_requested`/`hold_amendment_id`/`original_status`（或复用 workbench 的协作式 hold），不要用 `status='held'` 覆盖 running；release 恢复 original_status。
- 对 `pending` 的受影响任务也置 hold 标志（或明确拒绝 task_ids 含 pending，让调用方先处理），避免评估期间启动。
- 对 running 任务发协作式停止信号，worker 在安全检查点暂停；release 恢复后从 checkpoint 续跑，而不是 pending 重跑。

**探针 / 输出**
`p5_amend.py`：
```text
after A1: held 'running|已收到改令 amd_d018e29f，等待影响评估'
after A2: held 'held|已收到改令 amd_44485247，等待影响评估'
release A2: 1
after release A2: pending (original was running)
```
pending 任务不被 hold：
```text
held list: [] task status: pending wait_reason: ''
```

---

### B3-15 [P2] `/evaluate` 不传 evaluator，永远走确定性 wait_and_redo；`amendment_fallback` 卡批准后无消费者，任务仍 held

**位置**
- `backend/manager/api_v085.py:285-288`：`agent_hub.evaluate_amendment(room_db, amendment_id=..., directive_id=..., context=...)`，没有 `evaluator`。
- `backend/integration/agent_hub.py:397-410`：`evaluator is None` 时使用确定性结果：`keep=completed`、`update=[]`、`wait_and_redo=所有 held`。
- `backend/integration/agent_hub.py:411-422`：只有 evaluator 抛异常才创建 `amendment_fallback` 卡；HTTP 路径不会抛（因为没有 evaluator）。
- `backend/integration/agent_room.py:492-531`：resolve 只改卡状态；没有消费者根据 `decision.choice` 释放/重评/取消。

**机制**
API 的 evaluate 是“无模型”的确定性释放：它把所有 held 任务直接标成 `wait_and_redo` → pending，没有 Role E 影响分析，也不会生成 fallback 卡。直接调用 hub 并传入一个会抛错的 evaluator 才能得到 fallback 卡；但即使作者批准该卡，`resolve_approval` 只把卡置 approved，没有任何代码读取 `decision.choice`，任务仍 held、amendment 仍 fallback。

**影响**
- 作者改令后的“影响评估”实际是空操作，所有被 hold 的任务无条件重排，可能按旧方向重跑、浪费模型调用；
- 唯一的人工兜底卡是死胡同：三个按钮（放行/重评/取消）都没有实现；
- 与设计文档 03 §2.4（Role E 评估 + 三按钮兜底）直接矛盾。

**最小修复**
- API 注入 Role E evaluator（通过 ModelGateway，带 directive guard），解析结构化 `keep/update/wait_and_redo/preserve_versions`；失败时创建 fallback 卡。
- 增加 `amendment_fallback` 决策消费者：`放行已暂停结果` → release holds；`作废暂存并按新方向重试评估` → 清 checkpoint + 重评；`取消本次改令恢复原计划` → 取消 amendment + 恢复原 hold 状态；并在同一事务里更新 amendment/任务。
- 在没有消费者之前，不要暴露这张卡，或让它明确只作记录。

**探针 / 输出**
`p23_evaluate_no_model.py`：
```text
evaluate HTTP: 200 keys: ['amendment_id', 'keep', 'preserve_versions', 'status', 'update', 'wait_and_redo']
keep/update/wait_and_redo: [] [] ['tsk_1c2c7e8d']
task after: pending
pending approvals: []
amendment status: evaluated
```
`p31_amendment_fallback.py`：
```text
card: apr_7c8222ea amendment_fallback pending choices: ['放行已暂停结果', '作废暂存并按新方向重试评估', '取消本次改令恢复原计划']
resolved: approved {'choice': '放行已暂停结果'}
task after card approval: held
amendment after card approval: fallback
```

---

### B3-16 [P2] 指令创建输入未校验：`max_calls=0` 变 20；`budget_cap_cny` 为 dict/list 或 `max_calls` 超大直接 HTTP 500

**位置**
- `backend/manager/api_v085.py:259`：`budget_cap_cny=body.get("budget_cap_cny")` 原样入库，没有类型/范围校验。
- `backend/manager/api_v085.py:260`：`max_calls=int(body.get("max_calls") or 20)`：
  - `0` 是假值 → 20；
  - 负数原样接受（fail-closed，但语义错误）；
  - `10**30`/`1e30` 通过 `int()` 后绑定 SQLite INTEGER → `OverflowError` → 500。
- `backend/integration/agent_room.py:203-209`：`budget_cap_cny` 直接绑定参数；dict/list 不支持 → `sqlite3.ProgrammingError`。
- `backend/manager/api_v085.py:33-38` 的 `guard` 只捕获 `TypeError/ValueError/KeyError`，不捕获 `OverflowError/sqlite3.ProgrammingError`；`app.py` 全局 handler 也不覆盖这两个异常 → `internal_error` 500。

**机制 / 影响**
- `max_calls=0` 被静默改成 20，调用方以为“禁用”实际允许 20 次；
- `budget_cap_cny="not-a-number"` 能创建成功，之后 `reserve_request` 里 `Decimal(str(cap))` 抛 `InvalidOperation`，被 generic except 转成 `BudgetExceeded + record_gap`，又触发 B3-05 的永久 gap；
- dict/list/huge 直接 500，破坏 `{code,message}` 4xx 契约，并留下未处理 traceback。B-15 的“参数错误不 500”只修了部分字段，这是新向量。

**最小修复**
- 用 Pydantic 模型定义创建指令：`max_calls: int = Field(default=20, ge=1, le=10**6)`、`budget_cap_cny: Decimal | None = Field(default=None, ge=0, le=10**6)`；不要用 `or 20`，显式判断 `None`。
- 在 `agent_room.create_directive` 内用 `costs.number()` 校验 `budget_cap_cny`，统一存 `str()`；拒绝 dict/list/bool。
- `api_v085.guard` 增加 `OverflowError`、`sqlite3.Error` → 400 `invalid_request`（或 422），确保没有 500。

**探针 / 输出**
`p3_budget.py`：
```text
API max_calls=0 -> 200 20
API max_calls=-1 -> 200 -1
API budget_cap_cny='not-a-number' -> 200 not-a-number
```
`p6_isolation.py` / `p9_fuzz_api.py`：
```text
budget_cap_cny= {} -> 500 internal_error
budget_cap_cny= [] -> 500 internal_error
max_calls 10**30 -> 500 internal_error
max_calls 1e30 -> 500 internal_error
max_calls 2**63 -> 500 internal_error
```

---

### B3-17 [P2] `sender_role` 默认 `author`：任何 agent 默认发帖即冒充作者，污染 chat_context/审计

**位置**
- `backend/manager/api_v085.py:144`（无项目版）：`sender_role=str(body.get("sender_role") or "author")`。
- `backend/manager/api_v085.py:238`（项目版）：同样默认 `author`。
- `backend/integration/agent_room.py:574-576`：`chat_context` 把 `sender_role` 原样作为 `role` 返回，供 Role E/UI 使用。

**机制**
房间没有调用方身份；`sender_role` 完全由 body 决定，默认又是 `author`。任何 agent/worker 只 POST `{"text": "..."}` 就会以作者身份写入 `agent_events`，并进入 `chat_context` 的 `role` 字段。显式传 `sender_role="author"` 也可；但默认值让“无意冒充”变成常态。

**影响**
- 主编对话上下文会把 agent 消息当成作者指令，Role E 可能据此执行高风险动作；
- 审计/回放无法区分作者与 agent；
- 与“严禁 Agent/Worker 伪造审批提交”的四主体身份模型不一致（审批是另一条路，但聊天同样是指令入口）。

**最小修复**
- 不使用 body 的 `sender_role` 作为身份；从服务端会话/调用方上下文取角色（作者 UI token/agent worker 身份）。
- 默认改为 `system` 或 `chief`，`author` 只允许作者会话；对角色做 allowlist。
- 在事件里记录 `actor_id`/`actor_kind`，不要只靠字符串。

**探针 / 输出**
`p21_misc.py`：
```text
chief message default sender_role: author
prebook message default sender_role: author
```
（`chat_context` 输出：`[{'seq': 1, 'role': 'author', 'kind': 'message', 'summary': '我批准发布'}]`。）

---

### B3-18 [P2] `local_route` 否定/长句误判：`继续写所有章节`、`恢复所有角色...` 触发全局解除急停，`不要全局暂停` 触发全局暂停

**位置**
- `backend/integration/agent_hub.py:192-195`：
  ```python
  if re.search(r"(全局|所有).{0,6}(暂停|急停)", text):
      return {"action": "system_ai_pause", "params": {"paused": True}}
  if re.search(r"(恢复|继续).{0,6}(全局|所有)", text):
      return {"action": "system_ai_pause", "params": {"paused": False}}
  ```
- `backend/integration/agent_hub.py:203-204`：`(执行|处理).{0,6}(本章|全部).{0,4}批注` 不看否定。
- `backend/manager/api_v085.py:359-366`：`/chief/commands` 直接返回该 action；如果前端执行，就有副作用。

**机制**
正则匹配的是任意位置、任意长度文本，没有锚定“命令句”，也不处理“不要/别/勿”否定。于是：
- “继续写所有章节”匹配 `继续.{0,6}所有` → `system_ai_pause(paused=False)`，把全局 AI 解除急停；
- “恢复所有角色的默认设置”同样；
- “不要全局暂停”匹配 `全局.{0,6}暂停` → 暂停；
- “不要执行本章批注”匹配 `执行...本章...批注` → 执行批注。

**影响**
作者一句普通创作指令可能意外暂停/恢复全站 AI，或执行批注；这是有副作用的 Level 0 路由。若 `/chief/commands` 只是预览、不执行，则是误导；但接口名与计划都把它当命令执行入口。

**最小修复**
- 命令解析锚定短句/句首（例如 `^` 或“请/帮我”前缀），限制总长度；对“所有/全部”动作要求明确命令词（“全局暂停”四字连写）。
- 先检测否定前缀（`不要|别|勿|无需`）并返回 `None`/确认，不要执行。
- 对 `system_ai_pause`、`run_annotations` 这类副作用动作返回 `requires_confirmation=True`，由作者二次确认。
- 增加否定/长句回归测试。

**探针 / 输出**
`p21_misc.py`：
```text
local_route '继续写所有章节' -> {'level': 0, 'action': 'system_ai_pause', 'params': {'paused': False}}
local_route '恢复所有角色的默认设置' -> {'level': 0, 'action': 'system_ai_pause', 'params': {'paused': False}}
local_route '不要全局暂停' -> {'level': 0, 'action': 'system_ai_pause', 'params': {'paused': True}}
local_route '不要执行本章批注' -> {'level': 0, 'action': 'run_annotations', 'params': {}}
```

---

### B3-19 [P2] `approved` 用 `bool()` 弱转：缺字段=拒绝，字符串 `"false"`=批准

**位置**
- `backend/manager/api_v085.py:346`：`approved=bool(body.get("approved"))`。
- `backend/manager/api_v085.py:331-339`：只强制要求 `artifact_fingerprint`/`approved_scope_hash`/`directive_revision`，不要求 `approved` 存在或为 bool。

**机制**
Python `bool("false") == True`、`bool("0") == True`；`body.get("approved")` 缺失/None/0/[] → False。API 没有 Pydantic 模型或显式类型检查，所以：
- 客户端发了绑定字段但漏了 `approved` → 卡片被永久置 `rejected`（不是 400）；
- 客户端发 `"approved": "false"` → 卡片 `approved`。

**影响**
一个字段类型错误就会做出与意图相反的不可逆审批决定（approve/reject 都是终态，重放 409）；字符串 `"false"` 是最危险的静默批准。

**最小修复**
- 要求 `approved` 必须存在且 `type(value) is bool`，否则 400 `invalid_request`；Pydantic `approved: bool` 会拒绝字符串（严格模式）。
- `decision`/`note` 也做类型校验；缺 `approved` 不应默认 reject。
- 补 `"false"`、缺失、0、null 四类测试。

**探针 / 输出**
`p13_approved_coercion.py`：
```text
missing approved -> 200 rejected {'note': ''}
approved='false' -> 200 approved
approved=0 -> 200 rejected
approved=null -> 200 rejected
```

---

### B3-20 [P2] 工具表 `risk` 从不被读取：Level 2 DAG 可含 `request_publish_authorization`/`create_book`，不生成任何审批卡

**位置**
- `backend/integration/agent_hub.py:32`、`:55`：`TOOLS` 给 `create_book`、`request_publish_authorization` 标 `"risk": "high"`；`execute_book_directive`/`update_creative_brief` 标 `"medium"`。
- `backend/integration/agent_hub.py:126-180`：`validate_dag` 只检查工具白名单、角色、环、节点数、深度；从不读 `TOOLS[tool]["risk"]`。
- `backend/integration/agent_hub.py:260-301`：`route` 的 Level 2 直接返回 planner 节点，不附加 `requires_approval`，也不调用 `agent_room.create_approval`。
- 设计文档 `03_...md` 工具表：真实发布/排期写入强制走确认卡片；`08_...md` 高风险门禁。

**机制**
`risk` 是死元数据。一个 Level 2 planner（模型输出）可以返回 `request_publish_authorization` 或 `create_book` 节点，`validate_dag` 认为合法，`route` 返回 `level=2`；没有任何审批卡或 `requires_approval` 标记。如果执行器按 route 结果直接派活，就绕过了高风险确认。

**影响**
高风险工具可以在“受限自由 DAG”里无审批执行；工具表的 risk 分级给维护者/前端一个错误的安全感。当前仓库没有任务执行器，所以是 latent；但 plan 的 Level 2 是面向模型的，正是需要门禁的地方。

**最小修复**
- `validate_dag` 对 `risk in {"high","medium"}` 的节点返回 `requires_approval`，或直接拒绝 Level 2 使用 high 风险工具。
- `route` 输出每个节点的 `risk`；执行器在派活前为 high/medium 节点创建 `agent_approvals` 卡并等待 author。
- 至少把 `request_publish_authorization` 从 Level 2 白名单移除，只允许确定性模板 + 审批卡路径。

**探针 / 输出**
`p22_high_risk.py`：
```text
validate_dag: {'order': ['a', 'b'], 'depth': {'a': 0, 'b': 0}}
route: {'level': 2, ..., 'nodes': [{'id': 'a', 'tool_name': 'request_publish_authorization', ...},
                                   {'id': 'b', 'tool_name': 'create_book', ...}], ...}
high-risk tools: {'create_book': 'high', 'request_publish_authorization': 'high'}
route keys: ['autonomy', 'level', 'nodes', 'order', 'slots', 'template']
```
（`route` 返回键里没有 `risk`/`requires_approval`；`validate_dag` 没有 db/approval 参数。）

---

## 3. P3 详细 / 清单

### B3-21 [P3] `bind_session_to_project` 直接写事件、绕过 `broadcaster.publish`，在线 SSE 收不到 `project_bound`

**位置**：`backend/integration/agent_room.py:295-300` 使用 `_append_event_db`（纯 INSERT），而不是 `append_event`（`:408-424`，末尾 `broadcaster.publish`）。

**机制/影响**：绑定事件持久化成功，但在线的项目流不会收到；只有之后重连回放才看得到。绑定瞬间的 UI 不会切换/刷新。

**最小修复**：在事务提交后调用 `broadcaster.publish(event)`（或直接复用 `append_event` 的 publish 部分；注意不要在一个事务里 publish 未提交事件）。

**探针 / 输出**：`p16_bind_publish.py`：
```text
live queue empty after bind: True
durable project_bound rows: [(1, 'text', 'p1'), (2, 'project_bound', 'p1')]
live queue after append_event: 1
```

### B3-22 [P3] `events_after`/`max_seq`/`list_tasks`/`pending_approvals` 的 session-only 过滤未统一加 `project_id IS NULL`；接入会话流即跨书

**位置**：
- `agent_room.py:435-436`（`events_after` 只加 `session_id`）
- `agent_room.py:454-455`（`max_seq` 只加 `session_id`）
- `agent_room.py:369-370` + `:357`（`list_tasks` 需要 `unbound_only=True` 才加 `project_id IS NULL`）
- `agent_room.py:545-546` + `:543-544`（`pending_approvals` 同理）
- 对照 `snapshot` 在 `:597-599`、`:607-609`、`:626-629` 明确加 `project_id IS NULL`。

**机制/影响**：`snapshot` 已按 B-05 修好，但其他 session-only 读取器仍会返回所有书。计划中的 `/api/chief/room/stream?session_id=` 一旦直接调用 `events_after(session_id=...)`，就会把 p1/p2 的所有事件推给预建书会话流。当前 API 只用了 project 流和 snapshot，所以是 latent。

**最小修复**：所有 session-only 查询统一加 `project_id IS NULL`，或把 `unbound_only` 默认设为 True；新增会话流时强制使用。

**探针 / 输出**：`p30_session_readers.py`：
```text
events_after(session only): [('p1', 'A'), ('p2', 'B'), (None, 'unbound')]
max_seq(session only): 3
list_tasks(session only): [('p1', 'A-task'), ('p2', 'B-task')]
pending_approvals(session only): [('p1', 'A-card'), ('p2', 'B-card')]
snapshot(session only): [(None, 'unbound')]
```

### B3-23 [P3] 默认 session=`author` 的预建书行可被任一本书认领；400 请求也先 bind 后校验

**位置**：`backend/manager/api_v085.py:232-234` 在 `append_event` 之前调用 `bind_session_to_project`；两者是独立事务。`agent_room.py:283-302` 把该 session 所有 `project_id IS NULL` 的 directives/tasks/events/approvals 一次性改成目标 project。

**机制/影响**：
- 所有书的默认 session 都是 `author`；先建的书 B 发第一条消息，会把为 A 准备的未绑定对话/指令/审批全部认领到 B。
- 发送非法 channel 的消息：`append_event` 返回 400 `invalid_channel`，但 bind 已经提交；失败请求仍然改写了数据归属。
- 当前预建书流程没有大量生产者，所以是 P3；一旦接入开书引导，就是跨书串数据。

**最小修复**：预建书 session 用 `prebook_<uuid>` 而不是共享 `author`；先校验 channel/kind 并成功 append，再 bind（或同一事务）；bind 只允许当前 session 的未绑定行，且由作者会话发起。

**探针 / 输出**：`p6_isolation.py`：
```text
pre-book directive project: None event: None
B first message HTTP: 200
directive adopted by: ecdb79539532fdeb event project: ecdb79539532fdeb
B room contains pre-book text: ['开书前私密对话：结局是双胞胎']
A room contains it: []
invalid channel HTTP: 400 invalid_channel
pre2 directive project after 400: 3ac497deb3b79abd
```

### B3-24 [P3] 超大 `Last-Event-ID` 未钳制 → 流内 `OverflowError`；回放帧不 `ack`，溢出 marker 可能回到 0

**位置**：
- `api_v085.py:153-155`：`after = max(0, int(header or 0))`，没有 int64 上限。
- `agent_room.py:439-440`：`seq > ?` 绑定超大 int → `OverflowError: Python int too large to convert to SQLite INTEGER`，整个 SSE 生成器抛错。
- `api_v085.py:166-177`：`replay_from` yield 后没有 `broadcaster.ack(token, cursor)`；只有 live 循环 `:210-212` ack。

**机制/影响**：恶意/损坏的 cursor 会让流在 `retry:` 之后直接异常（已实测）；回放帧未 ack 使 `_last_seq` 仍为 0，若随后溢出，marker 用 0，客户端会重复回放（不会丢，但重复渲染/重复 ack；此半句为读码确认，未单独构造溢出后回放探针）。

**最小修复**：clamp 到 `[0, 2**63-1]` 或 `max_seq`；`replay_from` 在 token 存在时对每个 yield 的 seq 调 `ack`；补畸形 header 测试。

**探针 / 输出**：`p28_misc2.py`：
```text
stream with cursor 999999999999999999999999999 raised:
 OverflowError Python int too large to convert to SQLite INTEGER
```

### B3-25 [P3] 传 `directive_guard` 但 `directive_id=None` 时静默无效，不报错

**位置**：`costs.py:226` `guard = dict(guard or {}) if directive_id else {}`；`model_gateway.py:203-208` 允许 `directive_id=None` 同时传 `directive_guard`。

**机制/影响**：`guard` 被丢掉；若没有全局 cap，`reserve_request` 直接返回 None，网关以为在护栏下运行，实际 0 行、无限制。调用方少传一个 id 就静默失去 `max_calls`/`budget_cap_cny`。

**最小修复**：`reserve_request` 在 `guard` 非空但 `directive_id` 为空时 raise `ValueError("directive_id_required")`；`ModelGateway.invoke` 同样在 `directive_guard` 且无 `directive_id` 时抛 `GatewayError`。

**探针 / 输出**：`p11_guard_silent.py`：
```text
guard without directive_id: calls all succeeded; rows: 0
reserve_request guard without directive_id returned: None
```

### B3-26 [P3] `op_id` 只是标签：同一 op_id 调两次会真实调用两次、记两行，未接幂等（与 docstring 矛盾）

**位置**：`model_gateway.py:1-8` 头注释“mandatory op_id so every billed call is idempotent”；`:189-190` 只校验非空；`:203-208` 把 op_id 写进 `operation` 字段；没有任何 `idempotency_keys`/唯一约束。

**机制/影响**：重试/双击会真实调用两次、计费两次；`op_id` 不能防重。当前无生产调用方，但这是网关的核心契约。

**最小修复**：在 `workbench_db.idempotency_begin`（或 costs 表唯一键 `(project, op_id, stage)`）中登记；完成时 `complete`，重复 op_id 返回缓存结果或 409；或在 docstring 明确它只是 tracing id。

**探针 / 输出**：`p20_minor.py`：
```text
same op_id service calls: 2
rows for same op_id: 2
```

### B3-27 [P3] `invoke_sync` 在已有事件循环中改开线程，`costs.META.db` 不传递，真实 `usage_events` 丢失

**位置**：`model_gateway.py:247-267`：在 running loop 中 `threading.Thread(target=worker)`；新线程不继承 `contextvars`。`model_gateway.py:214-215` 的 `costs.scope` 只设置 stage/project/chapter/role，不设置 `db`；`costs.Attempt` 用 `META.get().get("db") or env`（`costs.py:709`）。

**机制/影响**：从 async 上下文调用 `invoke_sync` 时，`Attempt` 拿不到 db_path，`usage_events` 为空；只有网关的 count-only 行被记录。成本报表丢失真实调用。当前 `annotation_generator` 多在 sync 线程池，故 latent。

**最小修复**：`invoke` 的 `costs.scope` 加 `db=str(self.db_path)`（如果设置）；或用 `contextvars.copy_context().run` 在新线程中运行，确保 META 复制。

**探针 / 输出**：`p27_invoke_sync_meta.py`：
```text
request_budget rows: [('settled', 0, '0', 'async-1')]
usage_events rows: []
```

### B3-28 [P3] `max_chapters` 把 chapter 0 当一章；`tokens()` 对字符串不套 10^12 上限

**位置**：
- `costs.py:273-274`：`len(usage['chapters'])` 包含 chapter 0（gateway 默认 chapter=0）。
- `costs.py:598-599`：字符串分支 `re.fullmatch(r"\d{1,13}")` 后直接 `int`，没有 `0 <= value <= 10**12` 上限；int 分支 `:593` 有。

**机制/影响**：
- 前置 planning/全书调用（chapter=0）会占掉 `max_chapters` 的一个名额；`max_chapters=1` 时“先规划再写第1章”被误拒。
- 供应商把 token 报成字符串 `"9999999999999"` 时被接受为 9.9e12，超出设计的 1e12 上限，可放大成本/预算。

**最小修复**：`chapters` 统计排除 0（或只对 chapter>0 计 max_chapters）；字符串分支复用同一个 0..10^12 范围检查。

**探针 / 输出**：`p21_misc.py` / `p20_minor.py`：
```text
max_chapters: chapter 1 blocked after chapter-0 call: {'limit': 'max_chapters', 'limit_value': '1', 'used': '1'}
tokens int 10^13: None
tokens str '9999999999999': 9999999999999
```

### B3-29 [P3] `agent_room` 写函数不 `initialize`，新库直接 OperationalError；room 端点不校验 project 存在，ghost identity 可写

**位置**：
- `agent_room.py:194-210` `create_directive`、`:305-321` `create_task`、`:461-477` `create_approval`、`:283-302` `bind_session_to_project`、`:338-354`/`:225-235` update 系列、`:492-531` resolve：直接 `write_tx`，没有先 `initialize`。
- 对照 `get_directive`/`get_task`/`get_approval` 都先 `initialize`。
- `api_v085.py:228-260`、`:116-135`、`:314-318`、`:149-221` 不调用 `project(identity)`；只有 annotations 端点经 `_book` 校验。

**机制/影响**：库调用方在全新 DB 上 `create_directive`/`create_approval` 直接 `no such table`；API 进程启动时 `install` 会 initialize，所以 HTTP 正常。room/directive 端点可以用不存在的 identity 写入/读取，产生孤儿数据，且与 annotations 的 404 行为不一致。

**最小修复**：所有写函数开头 `initialize(db_path)`（或让 `write_tx` 保证 schema）；room/directive 端点先 `project(identity)` 验证（或明确允许 ghost 但文档化）。

**探针 / 输出**：`p28_misc2.py` / `p6_isolation.py`：
```text
create_directive on fresh db: OperationalError no such table: agent_directives
create_approval on fresh db: OperationalError no such table: agent_approvals
ghost project message: 200 not-a-project
ghost project directive: 200 not-a-project
ghost snapshot: 200 1
```

### B3-30 [P3] 过期审批仍留在 pending 列表，只有尝试 resolve 时才置 expired

**位置**：`agent_room.py:539-549` `pending_approvals` 只按 `status='pending'` 过滤，不看 `expires_at`；`resolve_approval` 在 `:512-517` 才把过期卡置 `expired`。

**机制/影响**：过期卡一直出现在“待你决定”，UI 无法自动清理；直到作者点击才 409 并变成 expired。`snapshot` 也返回这些卡。

**最小修复**：`pending_approvals` 过滤 `expires_at > now`（或定期扫过期置 expired）；`snapshot` 同样；UI 显示 expired 历史另查。

**探针 / 输出**：`p20_minor.py`：
```text
pending list includes expired card: ['apr_c3f8bac2']
```

### B3-31 [P3] `ProviderClient._call` 无候选时隐式返回 `None`，调用方可能当成功

**位置**：`provider_client.py:193-212`：`for index,binding in self._candidates(): ...`，循环体没有 `else`/`raise`；`_candidates` 在共享 pin 越界（`_pinned`/`shared` >= len(options)）时返回 `[]`（`:73-75`）。

**机制/影响**：`chat()` 返回 `None` 而不是抛错；上层 `str(reply or "")` 可能变成空串，`ModelGateway` 会转成 `empty_model_output`，但直接调用 ProviderClient 的代码可能把 None 当成功/空回答。

**最小修复**：`_call`/`chat_stream` 在无候选时 `raise RuntimeError("no_model_candidate")`；`_candidates` 对越界 pin 回落/清理并记录。

**探针 / 输出**：`p20_minor.py`：
```text
candidates with out-of-range pin: []
chat returns: None
```

---

## 4. 已知残余复测结论（父任务点名项）

| 项 | 本轮结论 | 证据 |
|---|---|---|
| **B-03R 审批身份** | **仍成立（P1）** | B3-01：GET 卡片字段后可自批；`resolved_by` 省略即通过；GET /api/projects 无鉴权枚举 identity。 |
| **B-02 `budget_cap_cny` 被 count-only 清零** | **仍成立（P2）** | B3-09：`count_only` 每笔 cost=0，cap=1 允许 10/10；网关同。 |
| **B-11 双改令交叉释放** | **交叉释放已修复；但有新的状态机缺陷** | `p5_amend.py`：older release 0、newer release 1（不再交叉）；但 running→pending（B3-14）、cancel 漏状态（B3-13）、TOCTOU（B3-12）。 |
| **B-14R 溢出** | **部分修复，仍不完整（P2）** | B3-07：稀疏 project fresh 只回放 257..300；溢出后 full_reload（snapshot 100）补不齐 300 条。 |
| **B-01R-4 `apply_hunks` 两事务** | **仍成立（P1）** | B3-04：故障注入后正文已改、hunk pending、ledger 0、undo `ledger_entry_missing`、重试 conflict。 |
| **B-04 通用回环代理隐私判定** | **已修复（对照通过）** | `p12_privacy.py` / `p32_controls.py`：generic loopback→private_api；dsh_channel→free_pool_shared；paid→free/chan 拒绝；fallback options 只留 paid+local。 |
| **B-11R-2 改令 fallback 审批无消费者** | **仍成立** | B3-15/`p31`：卡批准后 task 仍 held、amendment 仍 fallback。 |
| **X-P2-5 `agent_hub` running 按 held 语义** | **仍成立** | B3-14：连续两次改令后 release 变 pending；pending 任务不被 hold。 |
| **X-P2-6 独立 SSE 无生产者** | **仍成立/更广** | B3-06：审批/任务/改令也不写 `agent_events`；B3-08：无会话流、跨进程 wake 孤儿。 |

## 5. 对照设计文档的矛盾清单

| 设计文档 | 代码现状 | 对应 finding |
|---|---|---|
| `03_...md:240` “改令递增后旧审批卡自动失效” | 只 bump directive revision，不 update approvals；resolve 比卡自身 revision | B3-02 |
| `03_...md:283-285` “作废任何未决旧改令确认卡”；`08_...md:131` 五重校验含身份 | 无 `superseded` 写入；身份是自报 | B3-01/B3-02 |
| `03_...md:301-303` 业务/对话/审批/改令写入 `agent_events`；瞬态只走内存 | 只有 chat/project_bound 写；瞬态也落库 | B3-06 |
| `03_...md:298-300` 支持 `after_seq` 与 `/api/chief/room/stream` | 只有 `last_event_id` + 项目流 | B3-08 |
| `03_...md:305-310` worker 写事件后 `/internal/events/notify` 唤醒 SSE | fanout 无订阅者；无 500ms 短读 | B3-08 |
| `08_...md:97-103`、`03_...md:337-338` 五态 `reserved→dispatched→settled/unknown_charge` | `Attempt` 不 dispatch；无崩溃回收 | B3-11 |
| `03_...md:283` `hold_amendment_id` 只挂 running，保留原状态 | agent_tasks 无此列，直接覆盖 running→held | B3-14 |
| `03_...md:302-303` 慢客户端先丢瞬态，持久溢出 resync | 瞬态先落库；overflow 后 full_reload 补不齐 | B3-06/B3-07 |
| `08_...md:131` 审批身份必须来自作者会话 | 静态头 + 自报 `resolved_by` | B3-01 |
| `03_...md` 高风险工具需确认 | `risk` 元数据从未读取 | B3-20 |

## 6. 覆盖矩阵

| 审计项 | 探针/方式 | 结论 |
|---|---|---|
| 审批身份、自批、GET 字段 | `p1_approval.py` | B3-01 仍成立 |
| 审批 revision/取消/`superseded` | `p1`/`p5` | B3-02 成立 |
| 审批重放/过期/跨项目 | `p32_controls.py` | 重放 409、过期 409、跨项目 404 正常 |
| `approved` 弱类型 | `p13` | 缺=reject、`"false"`=approve |
| 改令 hold/release/cancel/resume | `p5`/`p15` | B3-12/13/14 成立；B-11 交叉释放已修 |
| evaluate/fallback 消费者 | `p23`/`p31` | B3-15 成立 |
| 指令创建输入/500 | `p3`/`p6`/`p9` | B3-16 成立 |
| `local_route` 误判 | `p21` | B3-18 成立 |
| `sender_role` 身份 | `p21` | B3-17 成立 |
| 高风险工具 risk | `p22` | B3-20 成立 |
| 成本失败/取消结算 | `p32` | 已修复（对照） |
| count-only cap | `p3`/`p4` | B3-09 成立 |
| 双记账 requests/day | `p10` | B3-10 成立 |
| reserved 崩溃回收/五态 | `p14` | B3-11 成立 |
| 回退 gap 自毁 | `p17`/`p19` | B3-05 成立 |
| SSE 稀疏回放/溢出 | `p2`/`p8` | B3-07 成立 |
| SSE `after_seq`/会话流/跨进程 | `p25`/`p26` | B3-08 成立 |
| 事件模型（持久 vs 瞬态） | `p24` | B3-06 成立 |
| bind 未 publish | `p16` | B3-21 成立 |
| session-only 跨书读取 | `p30` | B3-22 潜在成立 |
| 预建书认领/400 先 bind | `p6` | B3-23 成立 |
| 超大 cursor | `p28` | B3-24 成立 |
| guard 无 directive | `p11` | B3-25 成立 |
| op_id 幂等 | `p20` | B3-26 成立 |
| invoke_sync META | `p27` | B3-27 成立 |
| max_chapters/tokens | `p20`/`p21` | B3-28 成立 |
| schema init/ghost project | `p28`/`p6` | B3-29 成立 |
| 过期卡 pending | `p20` | B3-30 成立 |
| 无候选返回 None | `p20` | B3-31 成立 |
| 隐私分级/回退 | `p12`/`p32` | B-04 已修复；B3-03 probe 旁路成立 |
| 跨项目 cancel/resume/amend | `p32` | 404 正常（B-20 已修） |
| 现有测试基线 | integration/manager discover | 全绿，不能覆盖上述盲区 |

## 7. 复现脚本清单

| 脚本 | 覆盖 |
|---|---|
| `p1_approval.py` | B3-01/B3-02：GET 字段、自批、改令后旧卡、取消后旧卡、`approved` 弱类型、跨项目 404 |
| `p2_sse_sparse.py` | B3-07：100 A + 156 B + 44 A 的稀疏 fresh 回放 257..300 |
| `p3_budget.py` | B3-09/B3-16：count-only cap、max_calls=0/-1、非法 budget |
| `p4_gateway_budget.py` | B3-09：真实 `ModelGateway` 路径 cap=1 仍 10 次 |
| `p5_amend.py` | B3-12/13/14：cancel 漏状态、running→pending、duplicate task_ids、空改令 |
| `p6_isolation.py` | B3-16/B3-23/B3-29：budget 500、预建书认领、400 先 bind、ghost 写入 |
| `p7_events.py` | B3-06 早期版本（事件表为空） |
| `p8_sse_overflow.py` | B3-07：溢出 marker、snapshot 100、fresh 200、resume 0 |
| `p9_fuzz_api.py` | B3-16：directive 字段 500 扫描 |
| `p10_double_count.py` | B3-10：一次逻辑调用 3 行/日限额 used=3 |
| `p11_guard_silent.py` | B3-25：guard 无 directive 静默无效 |
| `p12_privacy.py` | B-04 对照：隐私域与 fallback 过滤 |
| `p13_approved_coercion.py` | B3-19：缺省/`"false"`/0/null |
| `p14_stale_reserved.py` | B3-11：reserved 崩溃后占额度、无恢复函数 |
| `p15_cancel_race.py` | B3-12：cancel/amend、cancel/resume TOCTOU |
| `p16_bind_publish.py` | B3-21：bind 事件不入 live queue |
| `p17_fallback_gap.py` | B3-05：旧 gap + report complete + reserve 拒绝 |
| `p18_apply_atomic.py` | B3-04：apply_hunks 两事务故障注入 |
| `p19_fallback_poison.py` | B3-05：失败回退写 gap、后续永久拒绝 |
| `p20_minor.py` | B3-24/26/28/30/31：op_id、tokens、过期卡、无候选 |
| `p21_misc.py` | B3-17/18/28：sender_role、local_route、max_chapters |
| `p22_high_risk.py` | B3-20：high-risk DAG 无审批 |
| `p23_evaluate_no_model.py` | B3-15：API evaluate 确定性 wait_and_redo |
| `p24_events_missing.py` | B3-06：状态变化 0 事件、transient 5 行落库 |
| `p25_after_seq.py` | B3-08：`after_seq` 缺失、无会话流、dense cursor 对照 |
| `p26_wake_orphan.py` | B3-08：fanout 0 订阅者、notify 丢弃 |
| `p27_invoke_sync_meta.py` | B3-27：usage_events 为空 |
| `p28_misc2.py` | B3-24/B3-29：超大 cursor、fresh DB 写 |
| `p29_probe_bypass.py` | B3-03：stage=probe 绕过 allowed_projects |
| `p30_session_readers.py` | B3-22：session-only 跨书读取 |
| `p31_amendment_fallback.py` | B3-15：fallback 卡批准后无消费者 |
| `p32_controls.py` | 对照组：failed/cancelled 结算、跨项目指令、审批重放/过期、隐私 |

## 8. 未覆盖 / 限制

- 未修改仓库、未联网；所有真实 HTTP 探针使用 FastAPI TestClient/ASGI，未启动实际 8765 端口。
- `agent_hub`/`agent_room` 目前**没有生产执行器/审批 UI 生产者**：任务创建、approval 创建、amend 执行都只在测试/直接库调用中出现。因此 B3-02/10/12/13/14/15/20 等涉及任务执行的项是“状态机/库级已成立，HTTP 端到端需接入执行器后才可完全触发”；报告已逐条标注 latent/当前无调用方。
- B3-04 和 B3-12 的“第二个事务失败/并发窗口”使用故障注入/交错注入；真实崩溃/DB 锁超时是同一代码路径，但未做 OS 级 kill/锁压测。
- 未做 Windows 路径大小写、真实局域网配对设备、前端 SSE 解析器的端到端；这些属于其他域或需要真实设备。
- 未复核 annotations/text_merge 的其余 B-01/B-09 修复；B3-04 只针对父任务点名的 B-01R-4。
- 测试基线全绿不表示上述缺陷已修；现有测试反而固化了部分行为（`test_v085_api.py:80-94` 自批、`:172-214` 无模型 evaluate、`test_costs_five_state.py:169-180` count-only cost 0、`test_v085_api.py:259-280` 只测稠密 230 条）。

## 9. 优先级建议

1. **B3-01/B3-02/B3-19**：审批身份与生命周期；这是安全边界，且改动集中在 `api_v085.resolve_approval`、`agent_hub.start_amendment/cancel`、`pending_approvals`。
2. **B3-03**：`stage='probe'` 授权旁路；改动在 `provider_client._scope` 和 `free_pool._choices`，影响隐私硬边界。
3. **B3-04**：apply_hunks 单事务/补偿日志；影响正文与状态一致性。
4. **B3-05**：gap 可解决 + fallback 判据统一；否则一次失败永久关闭付费回退。
5. **B3-07/B3-08**：SSE 稀疏/full_reload/会话流/跨进程；这是“实时事件总线”的核心承诺。
6. **B3-09/B3-10/B3-11**：单行预算会计 + dispatched + 崩溃清扫；否则指令护栏不可信。
7. **B3-12/B3-13/B3-14/B3-15**：改令状态机；在接入执行器前修，避免双跑/僵尸指令。
8. 其余 P2/P3 按迭代处理；B3-20 高风险 DAG 在接入执行器前必须有门禁。
