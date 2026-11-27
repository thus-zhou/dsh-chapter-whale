# 独立审计报告 · B 部分
## 批注 / 三方合并 / 主编室 / Agent / 成本 / 模型网关

- 审计对象：`/home/ubuntu/.hermes/cache/scratch/audit-v2-head`，detached HEAD `5e8a2d0`（只读审计，未向仓库写入任何文件；`git status` 里唯一未跟踪项 `node_modules` 是外部工具放置的符号链接，见 §6 末尾）。
- 审计方式：逐行读码 + 独立编译复现脚本（不引用 `docs/audits` 旧报告，不依赖旧测试结论）。
- 运行环境：`PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8`；脚本全部落在 `/home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-*.py`。
- 基线：`unittest integration.test_annotations test_text_merge test_agent_room test_agent_hub test_model_gateway test_costs_five_state` → 64 tests OK；`manager.test_v085_api manager.test_v08_api` → 11 tests OK。**下列缺陷全部存在于当前 HEAD 且不影响现有测试通过**，即测试盲区。

---

## 0. 结论摘要

共 **29 条**：P1 × 6，P2 × 14，P3 × 9。

| 编号 | 级别 | 标题 | 主位置 |
|---|---|---|---|
| B-01 | P1 | 补丁账本无坐标空间，B′ 基线被旧 revision 区间写坏，正常编辑被判"作者已改" | `text_merge.py:243-274,323` / `annotations.py:591-618,662-671` |
| B-02 | P1 | 失败/中断请求无法结算预留（`state='failed'/'cancelled'` 被拒），日限额被失败请求吃光，成本报表永久 incomplete | `costs.py:368-383,742-775,125-138` |
| B-03 | P1 | 审批"五重校验"在 API 层被自身默认值抹平，`resolved_by` 只是字符串，任何本地进程可自助批准高风险卡 | `api_v085.py:220-235` / `agent_room.py:443-478` |
| B-04 | P1 | 回环 `dsh_channel`（正文转往第三方免费渠道）被判为最严格域 `local_offline`，私有主通道可"升级性"回退到共享渠道 | `model_gateway.py:49-69` / `provider_client.py:39-51` |
| B-05 | P1 | 跨作品隔离缺失：room state 按共用 session 聚合全部作品；SSE 把 `project_id=NULL` 事件广播到所有作品流；指令端点无项目绑定 | `agent_room.py:504-564,602-635` / `api_v085.py:101-104,192-212` |
| B-06 | P2 | XML `<patch>` 格式实际不可用：多块必被 `unknown_patch_id` 全拒；单块也会忽略 `start_para/end_para` 改错段落 | `annotations.py:299-311,489-494` |
| B-07 | P2 | `custom_text` 从不落库：作者微改被记成"作者已改"，删除型补丁永远 `committed_modified` | `annotations.py:619-622,655-660,777,782` |
| B-08 | P2 | 作者改写选区（`overlap_conflict`）不跳过，模型被喂错文本，产出永远无法应用的预览 | `annotations.py:430-436` / `model_gateway.py:250-254` |
| B-09 | P1 | 纯删除 hunk 不参与重叠检测：同一对编辑的合并结果随机（双写或冲突），双写时静默吃掉后续正文 | `text_merge.py:229-240,340-341,361-383` |
| B-10 | P2 | 删除型补丁撤销按过期 offset 盲插，把原文插到作者新写内容之前 | `text_merge.py:405-414` / `annotations.py:724-730` |
| B-11 | P2 | 改令先 bump revision 后校验参数（400 也让 revision+1，废掉所有待批卡）；改令正文从不落库；`update` 被忽略致任务永久 held | `agent_hub.py:306-365` |
| B-12 | P2 | 已 `rejected` 的批注仍可 apply，落盘后翻成 `partially_applied` | `annotations.py:569-601` |
| B-13 | P2 | 任一快照文件缺失 → 整章批注列表 404 | `annotations.py:254-262` |
| B-14 | P2 | SSE 回放上限 200 且无续传标记；背压 `resync_required` 帧带最新 seq，重连即永久丢事件 | `api_v085.py:129-148` / `agent_room.py:378-397,602-635` |
| B-15 | P2 | 4 个端点在校验型字段传标量时抛 `TypeError` → HTTP 500，破坏统一错误码约定 | `api_v085.py:23-33,59,83,166` |
| B-16 | P2 | 批注预览可走 `revision_plan.accept` 二次提交：正文已改，hunk/preview/annotation 状态全不动 | `api_v08.py:158-166` / `revision_plan.py:391-411` |
| B-17 | P2 | 指令护栏双记账：每次调用按 `unknown_reserve_cny`（默认 1 元）计入指令预算，2 元预算只够 2 次调用（目前无生产调用方，latent） | `model_gateway.py:180-215` / `costs.py:288-310` |
| B-18 | P2 | `override_binding` 只做隐私校验、不改变实际路由，"手动授权换通道"是空操作 | `model_gateway.py:171-175` |
| B-19 | P2 | 批注生成与调用方 `op_id` 脱钩：同一 `op_id` 重跑两次计费两次、生成两份预览；`idempotency_keys` 未接入 | `model_gateway.py:265-267` / `annotations.py:390-392` |
| B-20 | P2 | `amend/cancel/resume` 无项目绑定，可跨作品取消他人指令 | `api_v085.py:192-212` |
| B-21 | P3 | `triage.independent` 同时列出 `coupled_batch` 成员，客户端可能重复执行 | `annotations.py:355-378` |
| B-22 | P3 | apply 信封 `status="applied"` 但 `applied=[]`、草稿未变 | `annotations.py:699-701` |
| B-23 | P3 | hunk 六态中 `rejected` 无任何写入点，逐 hunk 拒绝不可用 | `annotations.py:27-31,796-817` |
| B-24 | P3 | 被 A/B 覆盖掉的变体预览永远停在 `pending` | `annotations.py:686-697` |
| B-25 | P3 | gap 文件永不清理，一次瞬时故障永久标记报表不完整 | `costs.py:125-138,828-840` |
| B-26 | P3 | `/chapters/{ch}/previews` 的 `merge_state` 对 revision 预览恒为 `unknown` | `api_v08.py:158-166` / `annotations.py:556-564` |
| B-27 | P3 | `agent_hub.untrusted()` 是死代码；批注提示词手拼 `<UNTRUSTED_MATERIAL>` 且不转义内层闭合标签 | `agent_hub.py:64-68` / `model_gateway.py:255-263` |
| B-28 | P3 | 死代码/死常量：`merge_preview`、`locate_hunk`、`ModelGateway._budget`、`ROLE_PRIVACY_DEFAULT` | `text_merge.py:199,439` / `model_gateway.py:33,130-145` |
| B-29 | P3 | `mark_committed` 逐条自动提交，非原子；中途失败留下半提交状态 | `annotations.py:771-793` |

---

## 1. P1 详细

### B-01 [P1] 补丁账本没有坐标空间，B′ 被旧 revision 的区间写坏，正常编辑被判"作者已改"

**位置**
- `backend/integration/text_merge.py:243-274` `build_intermediate_base()`：把 `ledger` 与 `already_applied` 的 `(char_start, char_end, applied_text)` 直接 `points[start:end] = replacement`。
- `backend/integration/text_merge.py:323`：`intermediate = build_intermediate_base(base, already_applied, ledger=ledger)`，其中 `base` 是**当前预览的 base 快照**。
- `backend/integration/annotations.py:591-618`：读取**整章**的 `patch_ledger`；`:662-671` 写入账本时只存 `applied_range_json / before_quote / applied_text`，**不存 draft_id / draft_revision / base_snapshot_id**。
- `backend/integration/annotations.py:607-609`：`already` 只从本次 `hunk_ids` 里取（`rows` 已被 `id IN (selected)` 过滤），所以 `already_applied` 恒为空——B′ 完全依赖账本。

**机制**
账本里的 `applied_range_json` 是"当时那一版草稿"的坐标。作者只要在该区间**之前**插入/删除过文字，下一次 apply 时该区间已整体平移；`build_intermediate_base()` 却把它原样回放到新的 base 快照上，于是 B′ 既不是 base 也不是 current，"B。" 被覆盖、`C1。` 被复制。接下来 `_prepare_hunk()` 的第一跳（base → B′）就找不到原始 quote，`_range_in_replace()` 命中那段被写坏的区域，直接返回 `overlap_conflict / selection_changed`；即使侥幸绕过第一跳，`delta_ranges = diff(B′ → current)` 也会把这段"账本制造出来的差异"当成作者独立编辑，在第二跳或 `_overlaps(start, end, delta_ranges)` 处拒绝。

**影响**
最常见的正常操作序列——"采纳一块 → 手打几笔 → 再采纳下一块"——会出现**假冲突**，且被拒的编辑是作者根本没有动过的段落。`apply_hunks` 还会把这类假冲突与真冲突混在同一个 `conflicts` 数组里，前端无法区分；作者只能反复重试或放弃候选。这是"三方合并"的正确性核心。

**最小修复**
给 `patch_ledger` 增加 `base_snapshot_id`（或至少 `draft_id, draft_revision`），`build_intermediate_base()` 只回放"与当前 base 同一坐标系"的条目；跨坐标系的条目先用 `before_quote/applied_text` 做 `relocate_anchor` 式重定位，定位不唯一就跳过并记入诊断，而不是盲写。

**复现**
```
cd /home/ubuntu/.hermes/cache/scratch/audit-v2-head
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-15-ledger.py
```
**实际输出**
```
draft after apply1: 'A。\nB。\nC1。\n'
ledger: [{'applied_range_json': '[6, 9]', 'applied_text': 'C1。'}]
draft after author prefix: 'X。\nA。\nB。\nC1。\n'
B'  : 'X。\nA。\nC1。C1。\n'          ← 账本按旧 offset 回放，吞掉 "B。"、重复 "C1。"
real : 'X。\nA。\nB。\nC1。\n'
```
同一场景下对**从未被作者改动**的 "B。" 发起批注并 apply（内联脚本 tmp-b-15 第二段）：
```
status: applied clean: False applied: []
conflicts: [{'status': 'overlap_conflict', 'reason': 'selection_changed',
             'start': 6, 'end': 8, 'current_text': 'B。', 'candidate_text': 'B1。'}]
draft: 'X。\nA。\nB。\nC1。\n'      ← 一个字节都没动
hunk: ['pending']
```

---

### B-02 [P1] 失败/中断请求无法结算预留，日限额被失败请求吃光，成本报表永久不完整

**位置**
- `backend/integration/costs.py:381`：`if state not in {'settled', 'unknown_charge', 'released'}: raise ValueError('budget_state_invalid')`
- `backend/integration/costs.py:772`：`state={"success":"settled","interrupted":"cancelled"}.get(self.event["status"],"failed")` —— `interrupted → "cancelled"`、`failed → "failed"`，两者都不在白名单。
- `backend/integration/costs.py:773-775`：`except Exception: record_gap(...)` 吞掉异常。
- `backend/integration/costs.py:125-138, 828-840`：`record_gap` 只写文件，`ledger_gaps()` 统计全部历史文件，`summary["complete"] = ... and not gaps`。

**机制**
`Attempt.finish()` 对失败（无 usage、无输出）与中断（有部分输出）的请求分别调用 `settle_request(state='failed'/'cancelled')`，`settle_request` 直接 `ValueError` 回滚。于是 `request_budget` 永远停在 `reserved`（AIService 路径不调用 `mark_dispatched`），该行仍被 `reserve_request` 计入 `requests_per_day` 与 `chapter/project_tokens`，其 `cost_cny` 仍是 `unknown_reserve_cny`（默认 1 元）。同时每个失败请求落一个 `.gaps/*.json`，永不清理。

**影响**
1. 网络抖动/超时在高频重试下会**耗尽当日请求上限**，而实际一次都没成功；作者看到"今日请求次数已到上限"，却全是失败尝试。
2. 失败请求按 1 元/次占用章节/全书费用上限（`chapter_cost_cny` 只按 `cost_cny` 求和），把付费预算提前打满。
3. `report()["summary"]["complete"]` 一旦为 false 就**永久**为 false，`missed_events` 单调递增，"可能漏记"告警从此常亮，真正的漏记被淹没。

**最小修复**
`settle_request` 接受 `failed`/`cancelled` 并映射到 `released`（失败未产生费用）或 `unknown_charge`（中断可能已计费），二者都置 `tokens=0`、`cost_cny='0'`/保留未知；`record_gap` 只在"写库失败"时调用，结算状态非法不应算作 gap；`ledger_gaps()` 按时间窗口（如最近 24h）统计或归档。

**复现**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-03-costs.py    # 单元级
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-03b-costs.py   # 端到端（requests_per_day=3）
```
**实际输出**
```
settle(settled) -> <request_id>
settle(cancelled) raised ValueError: budget_state_invalid
settle(failed) raised ValueError: budget_state_invalid
state after probes: {'dispatched': 1, 'settled': 0, 'pending': 0}

attempt 0/1/2: reservation=<id>   [费用记录] 无法完成记录；保留待核对状态
4th attempt blocked: 今日请求次数已到上限 {'limit':'requests_per_day','limit_value':'3','used':'3'}
request_budget rows: [{'state':'reserved','tokens':5,'cost_cny':'1','unknown_cost':1} ×3]
gap files: 3
report.complete: False missed_events: 3
```

---

### B-03 [P1] 审批"五重校验"被 API 自身默认值抹平；身份是声明而非证据

**位置**
- `backend/manager/api_v085.py:225-235`：`artifact_fingerprint=str(body.get("artifact_fingerprint") or current.get("artifact_fingerprint") or "")`，`approved_scope_hash` 同理，`directive_revision=body.get("directive_revision", current.get(...))`。
- `backend/integration/agent_room.py:443-478`：五重校验（pending / 过期 / revision / fingerprint / scope）。
- `backend/integration/agent_room.py:449-450`：`if resolved_by != "author": raise agents_cannot_approve`。
- `backend/manager/api_v085.py:229`：`resolved_by=str(body.get("resolved_by") or "author")` —— 由调用方自报。

**机制**
服务端没有"产物句柄"，无法自行重算 fingerprint/scope；它把客户端**没传**的字段用库内值补齐，于是"校验"退化为 `stored == stored`。`resolved_by` 只做字符串比较，任何进程只要写 `{"approved": true, "resolved_by": "author"}` 就能消费任何 `pending` 卡（仅需本地 `X-Novel-Helper: 1` 头）。仓库自带测试 `test_v085_api.py:80-93` 正是**不带任何绑定字段**提交并断言 200，等于把该行为固化。

**影响**
在系统自己的威胁模型里（"agents cannot approve"），agent 或任何本地进程可自助批准发布/建书这类高风险卡；过期与 revision 是唯一真正生效的两道闸。artifact 被替换后旧的批准仍然可用，`approval_artifact_changed` / `approval_scope_mismatch` / `approval_directive_revision_stale` 三个错误码在生产调用路径上不可达。

**最小修复**
端点在缺字段时**拒绝**（400 `approval_binding_required`），由调用方从卡片里读出并回传；服务端对 `artifact_fingerprint` 至少要求等于库内值**且**由卡片创建时绑定的操作句柄重新计算一次（例如 `hash(artifact_ref)`）；审批消费走独立鉴权通道（如本地 IPC token / OS 用户校验），不把 `resolved_by` 当身份。

**复现**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-04-api.py
```
**实际输出**
```
-- approval for artifact 'fp-BEFORE-EDIT' (artifact later changed), resolve with NO binding fields --
HTTP 200 approved | resolved_by author
card fingerprint still: fp-BEFORE-EDIT
-- same card resolved by a *second* review of a stale revision, also no fields --
HTTP 200 approved
```

---

### B-04 [P1] 回环 `dsh_channel` 被判为最严格的 `local_offline`，私有主通道可"升级性"回退到第三方共享渠道

**位置**
- `backend/integration/model_gateway.py:49-64` `privacy_of()`：只有 `localhost/127.0.0.1/::1` 判 `local_offline`，其余一律 `private_api`；`protocol == 'free_pool'` 才判 `free_pool_shared`。
- `backend/integration/model_gateway.py:67-69`：`privacy_allowed(source, target) = rank(target) >= rank(source)`。
- `backend/integration/provider_client.py:39-51`：回退候选按该函数过滤。
- `backend/integration/free_channels.py:70-75`：`dsh_channel` 端点被强制为 `http://127.0.0.1:<owned_port>/v1`。
- `backend/integration/free_channels.py:17-30`：这些渠道是 CodeArts / WorkBuddy / Qoder / TRAE / Cline 等第三方"免费编码渠道"。

**机制**
`dsh_channel` 的 base_url 必然是回环地址，所以 `privacy_of()` 给出 `local_offline`（rank 3，最严格）。但该回环网关的作用正是把正文转发给腾讯/阿里/字节等第三方免费渠道。于是 `privacy_allowed(private_api(2) → local_offline(3)) == True`：一个配置了 `private_api` 主通道的角色，会自动回退到事实上最"共享"的通道，而系统认为这是一次隐私域**升级**。反向也被锁死：`local_offline` 主通道永远不会回退到付费 API（这一点符合预期，但原因是错的）。

**影响**
隐私分级无法区分"真正本地模型（`dsh_local`/`ofm_standalone`）"与"本机转发的第三方共享渠道"，自动降级护栏在唯一需要它的方向上失效。目前唯一实际闸门是 provider 的 `allowed_projects` 静态白名单（`provider_client.py:115-130`），它是粗粒度的、按书授权、与本次调用内容无关。`ROLE_PRIVACY_DEFAULT`（`model_gateway.py:33`）定义了按角色默认域却从未被引用，说明设计意图没有落地。

**最小修复**
`privacy_of()` 按 `protocol` 判定：`dsh_channel → free_pool_shared`（或新增 `third_party_channel`，rank 0/1）；只有 `dsh_local`/`ofm_standalone` 且端点回环才是 `local_offline`；把 `ROLE_PRIVACY_DEFAULT` 纳入 `_binding_for()` 的默认值。

**复现**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-13-privacy-sse.py
```
**实际输出**
```
privacy paid: private_api
privacy dsh_channel(loopback): local_offline
privacy dsh_local: local_offline
paid -> dsh_channel fallback allowed: True
```

---

### B-05 [P1] 跨作品隔离缺失（room state / SSE / 指令端点）

**位置**
- `backend/manager/api_v085.py:101-104`：`GET /api/chief/room/state?session_id=author` → `agent_room.snapshot(room_db, session_id=session_id)`，**路径里没有 project**。
- `backend/integration/agent_room.py:525-564`：`snapshot()` 用 `session_id` 过滤 `agent_events / agent_directives / list_tasks / pending_approvals`；所有写入端点的 `session_id` 默认值都是 `"author"`（`api_v085.py:110,163,185`）。
- `backend/integration/agent_room.py:602-635`：`publish()` 的过滤是 `if wanted and event.get("project_id") not in {None, wanted}: continue` —— `project_id IS NULL` 的事件会送到**每一个**项目订阅者。
- `backend/integration/agent_room.py:378-397`：`events_after(project_id=...)` 又用 `project_id=?` 精确过滤，NULL 事件不会被回放。
- `backend/manager/api_v085.py:192-212`：`amend / cancel / resume` 只按 `directive_id` 操作，不校验 `project_id == identity`。

**机制**
三处叠加：
1. `snapshot(session_id="author")` 返回全部作品的 `events（含 chat 正文）、directives、tasks、approvals`，因为所有书共用默认 session id；
2. `POST /api/chief/messages`（无 project 版，`api_v085.py:106-116`）写入 `project_id=None`，这些聊天被 SSE 广播到所有书的 `/room/stream`，但永远不会被 `events_after` 回放（重连即消失）；
3. `cancel_directive` 等端点不校验归属，任何书可以取消另一本书的指令（实测见下）。

**影响**
- 书的私密情节/指令出现在另一本书的主编室里；换书不重连就串台。
- 一本长篇的 `directive_id` 可从任一书的 room state 里读到（因为 snapshot 不按项目过滤），随后被另一本书取消或改令，任务状态机被跨作品劫持。
- 由于本地单用户，这不是权限提升，而是产品承诺的"每书隔离"失效；对作者而言等同于草稿串书。

**最小修复**
`snapshot()` 必须至少一个 `project_id`（无 project 时返回 400）；`/api/chief/room/state` 删除或改为 `session_id + project_id` 双参；`publish()` 对 `project_id IS NULL` 只投递给**同 session 且未绑定项目**的订阅者（订阅时记录 session）；`amend/cancel/resume` 先 `get_directive()` 并校验 `project_id`。

**复现**
```
PATH=... python3 -B -X utf8 /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-18-room-leak.py
PATH=... python3 -B -X utf8 /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-06-sse.py
PATH=... python3 -B -X utf8 /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-16-misc.py
```
**实际输出**
```
# tmp-b-18：两本书各发一条 chief 消息（都用默认 session_id），再读 room state
events via /api/chief/room/state: ['A 书机密：结局是双胞胎', 'B 书机密：结局是双胞胎']
projects represented: ['5d1567b8ae88d880', 'df0ddb1f78b96ce6']

# tmp-b-06
published event project_id: None seq: 1
book-A subscriber received: 书 B 的私密情节：主角其实是反派
replay for book-A returns: []

# tmp-b-16 (2)
B cancels A's directive -> 200 cancelled
directive now: cancelled
```

---

### B-09 [P1] 纯删除 hunk 不参与重叠检测：同一对编辑有时双写、有时冲突，双写时静默吃掉后续正文

**位置**：`text_merge.py:229-240` `_overlaps()`、`:361-369`（新增的 `applied_ranges` 冲突判定）、`:383`（`applied_ranges.append((start, start + len(replacement)))`）、`:340-341`（`prepared.sort` 对同 start 的 hunk 依赖稳定排序，而输入顺序来自 `SELECT ... WHERE id IN (...)` 按 TEXT 主键的扫描顺序）。

**机制**：删除型 hunk 的 `replacement == ""`，记入 `applied_ranges` 的区间是 `(start, start)`（零长）。后续 hunk 与它做 `_overlaps(start, end, [(start,start)])`：`left == right and start == end` 要求新 hunk 也零长（否），`start < right` 为假（`start < start`），第三条要求新 hunk 零长（否）→ 判无重叠。于是哪个先被处理决定结果，而处理顺序由**随机 annotation id 的字典序**决定：替换先 → 正确报 `hunk_overlap`；删除先 → 两者都 `applied`、`clean=True`，并且删除已经把 10 个字移走，随后替换仍按**删除前**的 `[start,end)` 写入，直接吞掉后面的"结尾。"。

**影响**：同一对编辑在 8 次重复中 3 次双写、5 次冲突（脚本输出见下），即**合并结果不可复现**；双写分支造成真实数据丢失（正文少了"结尾。"），却返回 `clean=True`，账本两行都记成功，两条批注都被记为已落地。这已经超出记账错误，是静默的内容破坏。

**最小修复**：`_overlaps` 在比较时把零长区间视为占一个点：`if start == end or left == right: return left <= start <= right` 之类的保守判定（零长与自己同点必冲突，零长落在区间端点也冲突），或对删除型记录 `(start, start + codepoint_length(before_text))` 作为占用区间；同时给 `prepared` 的排序键补上 `hunk_id` 让顺序确定（确定性只是让 bug 可复现，不能替代重叠检测）。

**复现 / 输出**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-19-nondeterministic.py
```
```
trial 0: applied=1 clean=False conflicts=['hunk_overlap'] draft='甲句。\n她撞开门，寒气扑面。\n结尾。\n'
trial 3: applied=2 clean=True  conflicts=[]                      draft='甲句。\n她撞开门，寒气扑面。'   ← 结尾。被吃掉
trial 4: applied=2 clean=True  conflicts=[]                      draft='甲句。\n她撞开门，寒气扑面。'
trial 6: applied=2 clean=True  conflicts=[]                      draft='甲句。\n她撞开门，寒气扑面。'
both-applied: 3 one-conflict: 5
```
单元级最小复现（两个 hunk 顺序固定为"删除在前"）：
```
$ ... tmp-b-07-overlap.py
text: 'NEW' clean: True conflicts: []
results: [('hk_a', 'applied'), ('hk_b', 'applied')]
```

---

## 2. P2 详细

（B-06 ~ B-08、B-10 ~ B-20；B-09 因端到端复现出数据丢失已上移为 P1，见 §1。）

### B-06 [P2] XML `<patch>` 格式实际不可用；`start_para/end_para` 被忽略导致改错段落

**位置**：`annotations.py:299-311`（解析 + `expected_ids` 校验）、`:489-494`（每一块都套用批注整体区间）、`:450`（`expected_ids=[item["id"]]`）。

**机制**：`run_annotations` 一次只处理一条批注，却把 `expected_ids=[item["id"]]` 传给解析器；而 `<patch>` 的 id 是模型自定的块 id，`set(ids) - set(expected_ids)` 非空即 `unknown_patch_id`，因此**任何多块输出整体失败**（`run_annotations` 返回 `status:"failed"`，批注退回 open）。即使模型把 id 写成批注 id，`_build_candidate` 也不看 `start_para/end_para`，把每块的 `char_start/char_end` 都设成批注区间，`before_text` 也是同一段原文；多块时第二块必然与第一块重叠被判冲突，单块时"第 N 段"的内容会替换到批注选区，造成重复/错位。

**影响**：声明支持"按段落打补丁"的弱模型路径完全不可用；误打误撞通过的单块会把段落内容写到错误位置（实测把第 3 段写进第 1 段并保留原第 3 段，产生重复文本）。默认提示词只要求 `<replacement>`，所以触发依赖模型自由发挥，但解析器与文档都宣称支持。

**最小修复**：`expected_ids` 改为"块 id 可缺失/任意，但不得重复"，或把批注 id 作为它们的前缀；`_build_candidate` 按 `start_para/end_para` 用 `revision_plan.paragraphs()` 解析出真实区间（并校验 `end_para >= start_para`）。

**复现 / 输出**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-01-patches.py
```
```
multi-patch: status failed previews 0 errors ['unknown_patch_id']
single-patch: status proposed errors []
  hunk start/end: 0 5 before: '第一段甲。' after: '改好的第三段。'
  candidate: '改好的第三段。\n第二段乙。\n第三段丙。\n'
  the declared target paragraph 2 was: '第三段丙。'
```
（单块场景：`start_para=2` 完全被忽略，第 3 段的新文本写进了第 1 段，原第 3 段仍留在正文里 → 重复。）

### B-07 [P2] `custom_text` 从不落库：作者微改被记成"作者已改"，删除型补丁永远 committed_modified

**位置**：`annotations.py:619-622`（只写进内存行）、`:655-660`（UPDATE 不含 `custom_text`）、`:777`（`mark_committed` 读 `custom_text`）、`:782`（`committed if applied_text and ...`）、`workbench_db.py:232`（列存在）。

**机制**：`apply_hunks` 把作者的 `custom_texts` 放在 `pending_rows` 的临时字典里，落库时只更新 `applied_draft_id/revision/range/sha`，`custom_text` 列为 NULL。`mark_committed` 因此回退到 `after_text`（模型原文），与实际写入草稿的文本不同，`applied_text in window` 判否 → `committed_modified`。删除型补丁 `applied_text == ""`，`if applied_text and ...` 直接为假 → 必然 `committed_modified`。

**影响**：`mark_committed` 的统计从此不可信（"采纳未改"与"作者改写"无法区分）；`preview_index` 被置 `committed`，批注被置 `accepted`，但溯源记录错误；后续若以 hunk 行为 B′ 依据（当前被 `already` 过滤掉，见 B-01）会写入模型原文而非作者文本。第 407aaa0 提交把 `mark_committed` 改成读 `custom_text`，属于**无效修复**——写入侧从未补上。

**最小修复**：`apply_hunks` 的 UPDATE 增加 `custom_text=?`（有 custom 时写，无则 NULL）；`mark_committed` 对空 `applied_text`（删除型）用 `before_text not in window` 判 `committed`。

**复现 / 输出**
```
$ ... tmp-b-02-custom.py
draft after apply: '开头一句。\n她轻轻推开门。\n结尾一句。\n'
hunk.custom_text in DB: None
ledger: {'applied_text': '她轻轻推开门。', 'custom': 1, 'applied_range_json': '[6, 13]'}
mark_committed on the *unchanged* draft: {'committed': 0, 'committed_modified': 1}
hunk status: ['committed_modified']
```

### B-08 [P2] 作者改写选区时不跳过，模型被喂错文本，产出永远无法应用

**位置**：`annotations.py:430-436`（只处理 `relocated_needed`，不处理 `overlap_conflict`）、`model_gateway.py:250-254`（用 `context["range"]` 去切 `current_text`）。

**机制**：`relocate_anchor` 第 3 级返回 `{"status": "overlap_conflict", "start": base_start, "end": base_end}`（**base 坐标**）。`run_annotations` 不拦，`context["range"]` 就是 base 坐标，生成器用它去切**当前草稿**，于是模型看到的 `TARGET` 是另一段文字（可能被截断在句子中间）；预览的 `before_text` 却是旧选区。apply 时 quote 已不存在 → `overlap_conflict`，预览永远 pending。

**影响**：一次真实计费的模型调用（`variant=2` 时两次）产出一份不可用的候选；作者看到"针对某段"的建议但指向别处；`preview_index` 与 `pending_hunks` 长期挂起。

**最小修复**：`if located["status"] in {"relocated_needed", "overlap_conflict"}:` 标记并跳过（`overlap_conflict` 建议单独状态 `author_rewrote_selection`，让作者决定是否重选）。

**复现 / 输出**
```
$ ... tmp-b-10-overlap.py
relocate status: overlap_conflict selection_changed start/end: 5 15
run status: proposed errors: []
range given to model: [5, 15]
TARGET text the model was asked to rewrite: '她站在门口，雨声很大'   ← 截断在句中
hunk before_text (base coords): '她推开门，屋里很冷。'
apply: applied clean: False applied: []  conflicts: ['selection_changed']
```

### B-10 [P2] 删除型补丁撤销按过期 offset 盲插

**位置**：`text_merge.py:405-414`（`applied` 为空且 `before` 非空时 `points[position:position] = before`，无任何上下文校验）；`annotations.py:724-730`（`undo_apply` 直接调用）。

**机制**：账本对删除型补丁记录的 `applied_range_json` 是 `[start, start]`（`apply_hunks` 返回的 `end = start + len("")`）。撤销时把 `before_quote` 插到 `start`，既不验证该位置周围是否仍是当年的文本，也不走唯一引用重定位。作者在区间之前输入任何内容，原文就会被插到新前缀之前。

**影响**：撤销"删除"会破坏草稿：实测把 "甲乙丙丁戊" 插到 "前言。" 之前。`undo_apply` 返回 `status: "reversed"`，UI 认为成功。对比非空 `applied_text` 的分支（`:416-421` 先精确比对，再 `:422-434` 唯一引用搜索），删除分支完全没有防护。

**最小修复**：删除型记录 `before_prefix/before_suffix` 上下文（或至少记录 `before_quote` 前后各 32 字），撤销时用 `context_similarity` 定位插入点，不唯一则返回 `relocated_needed`；或直接复用 `relocate_anchor` 的空 quote 分支。

**复现 / 输出**
```
$ ... tmp-b-07-overlap.py
-- undo of the deletion after the author typed in front --
reverse_patch: '甲乙丙丁戊前言。NEW。\n' reversed
```

### B-11 [P2] 改令：先改状态后校验、正文不落库、`update` 被忽略

**位置**：`agent_hub.py:309`（`revision = room.bump_directive_revision(...)`）、`:312-313`（随后才校验 `fallback`）、`:306-324`（返回体带 `amendment_text` 之外什么都不存）、`:356-365`（只处理 `keep`/`wait_and_redo`，忽略 `update`）。

**机制**：`bump_directive_revision` 把 `directive_revision+1` 且 `status='amended'` 提交之后，才发现 `fallback` 非法并抛 400。`agent_*` 五张表里没有 amendment 表，`amendment_text` 只在函数参数里存在过，`evaluate_amendment()` 也不接收它，所以"改令内容"无法审计、无法重放、无法在评估时读取。`evaluate_amendment` 对 `result["update"]` 完全不做处理，被列为 `update` 的任务永远停在 `held`。

**影响**：一次参数写错的改令请求（400）会悄悄推进 revision，使所有 `pending` 审批卡的 `directive_revision` 失效（`approval_directive_revision_stale`），作者必须重新发卡；改令正文永久丢失；`update` 类任务永久冻结，只能靠 `release_holds_for_current`（需要 amendment_id）人工解冻。`start_amendment` 的 `task_ids` 也未校验属于该 directive（`UPDATE ... WHERE id=?`），可冻结别的指令的任务。

**最小修复**：把校验提到 `bump_directive_revision` 之前；新增 `agent_amendments(id, directive_id, revision, raw_text, fallback, status, created_at)` 并在同一事务里写入；`evaluate_amendment` 对 `update` 执行 `status='pending'` + `wait_reason`，对未分类的 held 任务给出明确终态。

**复现 / 输出**
```
$ ... tmp-b-11-amend.py
before: 1 planning | task: running
rejected: invalid_amendment_fallback
after rejected amendment: 2 amended | task: running     ← 400 之后 revision 仍 +1
tables: ['agent_directives','agent_tasks','agent_events','agent_approvals','agent_meta']
held task: held 已收到改令 amd_...
evaluate result keys: [... 'update' ...] | task after: held
```

### B-12 [P2] 已 `rejected` 的批注仍可 apply

**位置**：`annotations.py:569-601`（`apply_hunks` 只按 hunk id 与 hunk 状态筛选，从不看 `annotations.status`）。

**机制**：`update_annotation(status='rejected')` 只改批注行，hunk 仍是 `pending`。`apply_hunks` 的 SQL 是 `SELECT * FROM annotation_hunks WHERE chapter_id=? AND id IN (...)`，没有任何 join/状态判断，于是被拒批注的候选可以照常写入草稿；`_recompute_annotation_status` 随后把它改成 `partially_applied`。

**影响**："拒绝"没有约束力；一次误点/旧页面就能把已否决的修改落盘；状态机出现"rejected → partially_applied"的反向迁移。

**最小修复**：`apply_hunks` 查询时 join `annotations` 并过滤 `a.status NOT IN ('rejected')`，或把拒绝动作做成"hunk → rejected"（见 B-23），拒绝后 `pending` 计数归零。

**复现 / 输出**
```
PATH=/home/ubuntu/venvs/dsh/bin:$PATH PYTHONPATH=backend python3 -B -X utf8 \
  /home/ubuntu/.hermes/cache/scratch/audit-v2/tmp-b-12-reject.py
```
```
after PATCH rejected: rejected ['pending']
apply of a rejected annotation: applied True '甲改。\n乙句。\n'
annotation after: partially_applied
```
（附注：同一脚本的早期变体还观察到——若先拒绝某条批注、再应用**它自己的** hunk，批注会从 `rejected` 直接翻成 `partially_applied`。）

### B-13 [P2] 任一快照文件缺失 → 整章批注列表 404

**位置**：`annotations.py:254-262`（`list_annotations` 对每一行 `read_snapshot(...)`，`read_snapshot` 抛 `AnnotationError("snapshot_missing", 404)`）。

**机制**：没有 per-row 容错，一个坏引用（快照被清理、项目被复制、`base_snapshot_id` 写坏）就让整个 `GET /chapters/{n}/annotations` 返回 404 `snapshot_missing`。

**影响**：单条批注的元数据损坏会让整章评审界面打不开（前端拿不到任何批注，也无法删除坏行自救）；`triage` 里同样的 `read_snapshot` 有 try/except，说明作者已知该风险但列表路径漏了。

**最小修复**：列表循环内 `try/except AnnotationError`，把该行标 `status='relocated_needed'`、`relocated={'status':'snapshot_missing'}` 并继续。

**复现 / 输出**
```
$ ... tmp-b-16-misc.py
1) missing snapshot breaks the whole annotation list
   GET annotations -> 404 {"code":"snapshot_missing","message":"snapshot_missing"}
```

### B-14 [P2] SSE 回放上限 200 且无续传标记；背压 resync 帧反而丢事件

**位置**：`api_v085.py:132-135`（`events_after(..., after_seq=after, project_id=identity)`，未传 limit → 默认 200）、`agent_room.py:390-391`（`LIMIT ?`，`max(1, min(limit,1000))`）、`api_v085.py:136-146`（回放完直接进入 live 队列）、`agent_room.py:620-629`（溢出时清空队列，塞入 `resync_required` 且 `seq` 取**最新**事件的 seq）。

**机制**：客户端带 `Last-Event-ID=0` 重连、库里有 230 条待回放时，只发最老的 200 条就切到 live 队列；201..230 既不在回放里也不在队列里（它们早于 subscribe），永久丢失且没有任何 `has_more` 标记。背压路径更糟：`resync_required` 帧的 `id` 是新事件的 seq，客户端重连时带这个 id，正好跳过被丢弃的整段。

**影响**：所谓"持久事件总线、可按 seq 重放"只在 ≤200 条时成立；长时间离线/慢客户端会静默丢任务状态与审批事件，且丢的正好是"最新"那段。

**最小修复**：`frames()` 循环回放直到 `len(replayed) < limit` 或返回 `has_more`/`retry_after`；`resync_required` 帧使用"最后成功投递的 seq"（或 `0`）并要求客户端重取 `snapshot()`，而不是最新 seq。

**复现 / 输出**
```
$ ... tmp-b-13-privacy-sse.py
pending 230; replay returns: 200 last seq: 200 -> events 201..230 silently skipped
max_seq: 230
```

### B-15 [P2] 校验型字段传标量 → HTTP 500

**位置**：`api_v085.py:59`（`[str(x) for x in data["annotation_ids"]]`）、`:83` → `annotations.py:575`（`hunk_ids`）、`:166` → `agent_room.py:371`（`list(mentions)`）、`:184` → `agent_room.py:193`（`list(constraints)`）；兜底：`api_v085.py:23-33` 的 `guard` 只捕获四个自定义异常，`app.py:1268-1273` 的全局处理器只覆盖 `ValueError/FileNotFoundError/RuntimeError/KeyError/FileExistsError`。

**机制**：`TypeError` 不在任何处理器名单里 → 落到 `app.py:1300-1310` 的 `unhandled_handler`，返回 500 `internal_error`。由于 app 的全局 400 处理器把 `RuntimeError` 映射为 400，作者显然要求"参数错误不许 500"，但 `TypeError` 这一类漏了。

**影响**：前端把 `hunk_ids` 误传成单值（或第三方脚本）就被当成服务端故障；日志里产生完整 traceback；错误码契约（`{"code","message"}` + 4xx）被破坏。

**最小修复**：`guard` 增加 `TypeError` → 400 `invalid_request`（或在每个入口用 `_as_list()` 做类型归一），并把 `api_v085` 的 body 解析改为 Pydantic 模型（`hunk_ids: list[str]`）以获得 422。

**复现 / 输出**
```
$ ... tmp-b-05-500.py
/api/.../revision/apply-hunks      -> HTTP 500 {"code":"internal_error","message":"服务内部错误：'int' object is not iterable"}
/api/.../annotations/run           -> HTTP 500 {"code":"internal_error", ...}
/api/.../chief/messages            -> HTTP 500 {"code":"internal_error", ...}
/api/.../chief/directives          -> HTTP 500 {"code":"internal_error", ...}
```
（被 `grep` 掉的大段 `未处理的异常` traceback 即 `logger.exception` 输出。）

### B-16 [P2] 批注预览可经 revision accept 二次提交，hunk 状态全不动

**位置**：`annotations.py:501-514`（批注预览同时登记进 `revision_previews/*.json` 与 `preview_index`）、`revision_plan.py:391-411`（`accept()` 只认 `revision_previews` 与 candidate，完全不碰 `annotation_hunks/preview_index/annotations`）、`api_v08.py:158-166`（`/chapters/{ch}/previews` 列出全部 revision 预览）、`app.py:2038`（`revision/accept`）。

**机制**：同一份候选有两条提交路径：`apply-hunks`（改草稿 + 维护 hunk/账本）与 `revision/accept`（直接 `commit_candidate` 改正文）。后者对批注预览完全"失明"：正文已写入，但 hunk 仍 `pending`、`preview_index` 仍 `pending`、批注仍 `proposed`。

**影响**：作者通过"预览/接受"按钮提交后，批注面板永久显示 1 个待处理预览 + 1 个待处理 hunk；再点"采纳"会被 `selection_changed` 拒绝（若已有草稿则会二次写入）。`summary()` 的计数从此与正文不一致。

**最小修复**：`accept()` 前判断 `record["mode"] == "annotation"` 并拒绝（`annotation_preview_requires_hunk_apply`），或在 accept 成功后同步把该 `preview_id` 的所有 hunk 置 `committed`、`preview_index` 置 `committed`、重算批注状态。

**复现 / 输出**
```
$ ... tmp-b-14-accept.py
preview: prev_81cfef32_a index status: ['pending']
revision accept -> accepted sha e0ac...
chapter file now: '甲改。\n乙句。\n'
hunk states: ['pending']
annotation status: proposed
preview index status: ['pending']
summary: {'proposed_count':1,'pending_previews':1,'pending_hunks':1,...}
```

### B-17 [P2] 指令护栏双记账：每次调用按 1 元计入指令预算

**位置**：`model_gateway.py:180-215`（`directive_guard` 时 `reserve_request(tokens=0, cost_cny=None, ...)`，成功/失败都 `_settle`）、`costs.py:208-210`（未知金额用 `unknown_reserve_cny` 占位，默认 `'1'`）、`costs.py:288-310`（`_directive_usage_db` 直接累加 `cost_cny`）、`costs.py:395-399`（`settle_request` 在 `unknown_cost=1` 时保留占位金额）。

**机制**：`AIService` 内部已经用 `costs.Attempt` 为每次网络尝试建账（`webnovel-writer/backend/services/ai_service.py:204`），网关再为同一次逻辑调用插一行 `request_budget` 并 link 到 directive。这行永远拿不到真实费用（网关读不到 Attempt 的 `cost_cny`），`unknown_cost=1` 使 `settle_request` 保留 1 元，于是**每条指令调用固定消耗 1 元**，与实际单价无关。

**影响**：`budget_cap_cny` 形同"调用次数÷1元"。实测 2 元上限只允许 2 次调用（真实费用约 0），第 3 次报"该指令费用已到上限"。`max_tokens` 护栏同样失真（预留 tokens=0，结算只写 completion tokens）。目前仓内**没有生产调用方**传 `directive_guard`（只有 `test_model_gateway.py:62` 用 `override_binding`），所以属于"第一个接入者必踩"的 latent 缺陷；`bind_directive()` 亦无调用方。

**最小修复**：网关在 `_settle` 时从 `costs.META` 取 `Attempt` 的 `cost_cny`（或让 `Attempt` 把 `request_budget.id` 回填到 META），用真实金额结算；`reserve_request` 对"仅做次数护栏"的场景允许 `unknown_cost=0` 且 `cost_cny=None`，不占费用额度。

**复现 / 输出**
```
$ ... tmp-b-09-guard.py
call 0: ok
call 1: ok
call 2: BudgetExceeded 该指令费用已到上限 {'limit':'budget_cap_cny','limit_value':'2','used':'2'}
directive_usage: {'calls': 2, 'tokens': 10, 'cost_cny': '2', ...}
request_budget: [{'state':'settled','tokens':5,'cost_cny':'1','unknown_cost':1,'operation':'op-0'}, {...'op-1'}]
```

### B-18 [P2] `override_binding` 只做隐私校验、不改变实际路由

**位置**：`model_gateway.py:171-175`（`binding = self.check_binding(role, override_binding)`；`domain = privacy_of(...)` 之后 `binding`/`domain` 都未再使用）、`:175`（`service = self._service_factory(role, self.config)` 用原 config）。

**机制**：`check_binding` 返回合并后的候选 binding，但真正建连用的是 `self.config` 里该角色的配置。也就是说换 provider/model 的"手动授权重试"完全不会发生，只有隐私校验会因为候选 binding 而可能抛错。`domain` 是纯死变量，诊断里也没有记录实际隐私域。

**影响**：调用方以为切到了指定模型/通道（例如用户手动授权把某次调用改走付费通道），实际仍走原 binding，且计费、隐私域、诊断三者互相不一致；排查时无从核对。

**最小修复**：`invoke` 用 `binding` 构造 `service`（把 binding 作为 `config` 的角色覆盖传给 `service_factory`），或明确删除该参数并在 docstring 写明"仅校验"。

**复现**：代码路径直接可见；`grep -rn "override_binding" backend` 仅测试使用（`test_model_gateway.py:62`）。

### B-19 [P2] 批注生成与调用方 `op_id` 脱钩，重跑重复计费

**位置**：`annotations.py:390-392`（`op_id` 只校验非空，不进 `context`）、`:440-445`（`context` 无 op_id）、`model_gateway.py:265-267`（`op_id=str(annotation.get("op_id") or f"ann-{annotation.get('id')}-{annotation.get('variant',0)}")`）。

**机制**：`annotations` 表没有 `op_id` 列，`context` 也不透传，所以网关只能按 `ann-<批注id>-<variant>` 自造 op_id。同一 `op_id` 的两次重跑：两次都真实调用模型、各生成一份预览、`candidate_ids` 追加两项；反过来，两次**有意**重跑同一批注会得到同一个自造 op_id（若将来接幂等，会被误判为重复）。`workbench_db.idempotency_keys` 及 `idempotency_begin/complete` 完全未接入 `run_annotations`/`apply_hunks`（对比 `chapter_editor._idempotent`）。

**影响**：丢应答/双击重试 → 双倍计费、双份候选；`op_id` 这个"强制幂等键"在批注路径上是装饰品。这与 `model_gateway` 头注释"mandatory op_id so every billed call is idempotent at the API layer"直接矛盾。

**最小修复**：把请求的 `op_id` 放进 `context` 并由 `annotation_generator` 透传；`run_annotations` 用 `wb.idempotency_begin(..., action="annotations.run", op_id=...)` 包住整段，`apply_hunks` 同样接入。

**复现 / 输出**
```
$ 内联脚本（tmp-b-19）
model calls: 2 [('ann_d91193f6', 0, None), ('ann_d91193f6', 0, None)]
previews after two identical op_ids: [('prev_4bfe59a9_a','pending'), ('prev_a010b321_a','pending')]
candidate_ids: ['prev_4bfe59a9_a', 'prev_a010b321_a']
```

### B-20 [P2] 指令端点无项目绑定

**位置**：`api_v085.py:192-212`（`amend_directive` / `cancel_directive` / `resume_directive` 直接拿 path 里的 `directive` 调 `agent_room`/`agent_hub`，不校验 `project_id == identity`）；对照 `:220-226` 的审批端点有 `approval_project_mismatch` 检查。

**机制**：`update_directive(db, directive_id=..., status=...)` 与 `start_amendment(db, directive_id=...)` 都只按 id 操作。任何书（或任何持有 directive_id 的客户端）都能取消/恢复/改令另一本书的指令，并且 `resume` 不校验当前状态（可以把 `cancelled` 直接拉回 `running`）。

**影响**：跨作品状态篡改（实测 B 书取消 A 书指令成功）；被取消的指令可被任意书恢复，绕过作者意图；与 B-05 的 room state 泄露组合后，`directive_id` 是可直接读到的。

**最小修复**：三个端点先 `get_directive()` 并校验 `project_id`，再校验状态迁移（`cancelled` 只能由作者显式 resume 且记录审计）。

**复现 / 输出**
```
$ ... tmp-b-16-misc.py
2) cross-project directive cancel/amend (no identity check)
   B cancels A's directive -> 200 cancelled
   directive now: cancelled
```

---

## 3. P3 清单

| 编号 | 位置 | 问题 | 影响 | 最小修复 |
|---|---|---|---|---|
| B-21 | `annotations.py:355-378` | `independent` 在加入 coupled 组后未从列表移除 | 客户端若按 `independent` 并发执行会与 `coupled_batch` 重复；当前 `run_annotations` 忽略分组，仅影响外层编排/前端 | 合并前先 `independent.remove(other["id"])`；或输出 `groups` 单一结构 |
| B-22 | `annotations.py:699-701` | 无论是否真的写入，信封恒为 `status:"applied"` | 冲突时 `applied: []`、草稿未变，UI 显示"已应用" | `status = "applied" if applied else ("conflict" if conflicts else "noop")` |
| B-23 | `annotations.py:27-31,796-817` | hunk 六态中 `rejected` 无任何写入点；`_recompute_annotation_status` 的 `proposed if any(applied_to_draft)` 分支不可达 | 无法逐 hunk 拒绝；只能整条批注拒绝且不生效（B-12） | 增加 `reject_hunks()` 并让 apply 过滤；删除死分支 |
| B-24 | `annotations.py:686-697` | 只重算本次 `pending_rows` 涉及的预览；被 A/B 覆盖的变体预览永远 `pending` | `pending_previews` 虚高；UI 继续提供已被覆盖的变体 | 对被 supersede 的 hunk 所属 `preview_id` 一并重算 |
| B-25 | `costs.py:125-138,828-840` | `.gaps/*.json` 只增不减，`ledger_gaps()` 统计全部历史 | 一次瞬时故障后 `complete` 永久为 false，"可能漏记"告警失去意义 | 按 24h/7d 窗口统计或把已处理 gap 归档；`report()` 同时给 `gaps_recent` |
| B-26 | `api_v08.py:158-166` + `annotations.py:556-564` | revision 预览记录没有 `base_snapshot_id`/`hunks`，`preview_merge_state` 必抛异常被吞 | `/chapters/{ch}/previews` 的 `merge_state` 恒 `{"clean":false,"unknown":true}`，误导前端 | 只对 `mode=="annotation"` 的预览计算，否则返回 `null` |
| B-27 | `agent_hub.py:64-68` + `model_gateway.py:255-263` | `untrusted()` 无调用方；批注提示词手拼 `<UNTRUSTED_MATERIAL>`、`<TARGET>`、`<BEFORE>` 且不转义闭合标签 | 正文里出现 `</UNTRUSTED_MATERIAL>`/`</TARGET>` 即可越狱注入；导入稿/学习样本属外部材料 | 用 `agent_hub.untrusted()` 包裹并转义全部内层闭合标签 |
| B-28 | `text_merge.py:199,439`；`model_gateway.py:33,130-145` | `merge_preview`、`locate_hunk` 无调用方；`ModelGateway._budget` 是死代码（若被用会泄漏预留，从不 settle）；`ROLE_PRIVACY_DEFAULT` 从未引用 | 死代码误导维护者；`_budget` 一旦启用即产生 B-02 同类泄漏 | 删除或在文档中标注实验性；`_budget` 立即移除 |
| B-29 | `annotations.py:771-793` | `mark_committed` 在外层 `connect`（autocommit）里逐条 UPDATE，并对每条 hunk 开新连接做 `_recompute_annotation_status` | 中途异常留下"部分 hunk 已 committed、账本已/未删"的半提交状态；N 次额外事务 | 整个函数包一个 `wb.write_tx`，状态重算改为一次批量查询 |

---

## 4. HEAD 已修项复测（407aaa0）

严格按照提交 diff 逐项复测，结论：**5 项真修好，3 项只修了一半，1 项是无效修复**。

| 修复 | 位置 | 复测结论 |
|---|---|---|
| 快照原子写（`mkstemp`+`fsync`+`replace_with_retry`） | `annotations.py:54-73` | ✅ 有效；并发写同一 digest 不再出现半截文件 |
| `triage()` 按当前草稿重定位 | `annotations.py:334-354` | ✅ 有效；不再用 base 坐标做重叠判断 |
| `_build_candidate` 用 anchor 坐标建 hunk | `annotations.py:485-488` | ⚠️ 一半：前缀插入场景已正确（`test_candidate_uses_base_snapshot_coordinates_after_prefix_insert` 通过），但 `overlap_conflict` 未跳过 → B-08 |
| 全失败时批注恢复 `open` | `annotations.py:464-468` | ✅ 有效；实测 `status:"failed"` + 批注回到 `open` |
| 新建草稿时校验 `expected_draft_epoch` | `annotations.py:638-643` | ✅ 有效；旧 epoch 返回 409 |
| `preview_index` 状态维护 | `annotations.py:686-697` | ⚠️ 一半：只覆盖本次应用涉及的预览 → B-24；冲突时信封仍 `applied` → B-22 |
| `revert_draft_hunks` 重算批注 | `annotations.py:750-763` | ✅ 有效 |
| `mark_committed` 读 `custom_text` | `annotations.py:777` | ❌ 无效修复：写入侧从未持久化 `custom_text` → B-07 |
| `apply_hunks` 新增 `applied_ranges` 重叠检测 | `text_merge.py:361-369` | ⚠️ 一半：漏掉"先删除、后替换"的零长区间，双写时丢失后续正文（已升级 P1，B-09） |

另有 `api_v085.py` 新增审批项目校验（`:225-226`）有效，但同函数内 `:230-234` 的默认值填补把三层绑定校验抵消（B-03）。

---

## 5. 覆盖矩阵

| 审计项 | 覆盖方式 | 结论 |
|---|---|---|
| 候选坐标 | 真跑：前缀插入/后缀/选区被改写 | 前缀插入正确；选区被改写时坐标混用（B-08） |
| hunk 六态 | 读码 + 状态迁移实测 | `rejected` 不可达（B-23）；拒绝不生效（B-12） |
| 补丁账本 | 真跑：apply→手改→再 apply | 无坐标空间，B′ 污染（B-01） |
| 重叠与撤销 | 真跑：删除+替换同区间（两种顺序、8 次重复）；删除后撤销 | 结果不确定：3/8 双写并丢正文（B-09）；撤销盲插（B-10） |
| XML 解析 | 真跑：多块/单块/非 nonce/JSON 回退 | 非 nonce/JSON 路径正常；`<patch>` 不可用（B-06）；提示词不转义（B-27） |
| 批注生命周期 | 真跑：create→run→reject→apply→commit→undo→delete | 拒绝不生效（B-12）；custom 记错（B-07）；快照缺失整表 404（B-13） |
| A/B | 真跑：两变体、应用 A | 覆盖逻辑生效；被覆盖预览仍 pending（B-24） |
| 审批五重校验与身份 | 真跑：API 无字段批准、跨项目、重放 | API 默认值抹平三道；重放 409 正确；跨项目 404 正确（B-03） |
| 主编室四通道/SSE | 真跑：broadcaster、230 事件回放 | NULL 项目跨书广播（B-05）；200 上限丢事件（B-14） |
| 任务与改令状态机 | 真跑：非法 fallback、update 类改令 | revision 误推进、改令不落库、任务永久 held（B-11） |
| 隐私分级回退 | 真跑：privacy_of / privacy_allowed | dsh_channel 误判（B-04）；override 不路由（B-18） |
| 预算五态/双记账 | 真跑：3 次失败请求；指令护栏 | 失败无法结算（B-02）；护栏 1 元/次（B-17） |
| 模型网关降级 | 读码 + 构造 config | 降级链正常；`override_binding` 空操作（B-18）；空候选时 `_call` 返回 None（未列为独立条，见 B-28 备注） |
| 错误码与 HTTP 500 | 真跑：7 类畸形 body | 4 条 500（B-15）；ValueError/KeyError 映射正常 |
| 跨作品泄露 | 真跑：room state / SSE / 指令端点 | 三处（B-05、B-20） |

补充说明（不单列条目）：`ProviderClient._call/chat_stream` 在 `_candidates()` 为空时（共享 pin 因配置变化失效）会**隐式返回 None** 而不抛错，调用方可能把 `None` 当成功；建议 `raise RuntimeError("no_candidate")`。`revision_plan.accept` 的 `invalidation.invalidate` 在提交之后执行，失败时正文已变而接口报错（P3 级别的一致性缺口）。

---

## 6. 复现脚本清单

| 脚本 | 覆盖 |
|---|---|
| `tmp-b-01-patches.py` | B-06 多块/单块 patch |
| `tmp-b-02-custom.py` | B-07 custom_text |
| `tmp-b-02b-custom-next.py` | B-07 后续 apply 一致性 |
| `tmp-b-03-costs.py` / `tmp-b-03b-costs.py` | B-02 |
| `tmp-b-04-api.py` | B-03、B-15（ValueError 侧） |
| `tmp-b-05-500.py` | B-15 |
| `tmp-b-06-sse.py` | B-05 SSE |
| `tmp-b-07-overlap.py` | B-09、B-10 |
| `tmp-b-09-guard.py` | B-17 |
| `tmp-b-10-overlap.py` | B-08 |
| `tmp-b-11-amend.py` | B-11 |
| `tmp-b-12-reject.py` | B-12 |
| `tmp-b-13-privacy-sse.py` | B-04、B-14 |
| `tmp-b-14-accept.py` | B-16 |
| `tmp-b-15-ledger.py` | B-01 |
| `tmp-b-16-misc.py` | B-13、B-20、B-21、审批重放 |
| `tmp-b-17-envelope.py` | B-22、B-24 |
| `tmp-b-18-room-leak.py` | B-05（API 级 room state 跨作品聚合） |
| `tmp-b-19-nondeterministic.py` | B-09（8 次重复：3 次双写丢正文 / 5 次冲突） |

P3 中 B-22 / B-24 的实际输出（`tmp-b-17-envelope.py`）：
```
envelope status: applied | applied: [] | clean: False
conflicts: [('selection_changed', '丙句。', '丙改。')]
draft unchanged: '甲句。\n乙句。\n丙句改了。\n'

previews: [('81b7_a', 'applied'), ('c4d8_b', 'pending')]
hunks: {'b7_a_hk_01': 'applied_to_draft', 'd8_b_hk_01': 'superseded'}
summary pending_previews: 1
```

所有脚本只读仓库、只写 `/tmp` 随机目录。本次审计未向仓库写入任何文件；`git status --porcelain` 唯一一条是外部工具放置的未跟踪符号链接 `node_modules -> /home/ubuntu/projects/dsh-chapter-whale/node_modules`（12:32 创建，非本次审计产生；`backend/manager/audit_inventory.py:10` 已把它排除在清单外）。

---

## 7. 优先级建议（若只修 5 处）

1. **B-09**（零长删除的重叠判定）——会静默删掉后续段落，且结果随随机 id 变化；改动只在 `_overlaps`。
2. **B-01**（账本坐标空间）——三方合并的可信度基础，用户每天都会遇到。
3. **B-02**（失败结算）——会让付费功能在抖动日直接不可用，且事后无法恢复。
4. **B-03**（审批绑定 + 身份）——安全边界，且改动集中在 API 一处。
5. **B-05**（跨作品隔离）——产品承诺的每书隔离，改动集中在 `snapshot()` 与 SSE 过滤器。

B-07 是一行 UPDATE 的修复，直接决定"采纳记账"是否可信，建议随后立刻带上。B-04 是隐私语义，B-08/B-10 是数据破坏，紧随其后。
