# B 域独立审计报告（第四轮）

- 工作树：`/home/ubuntu/.hermes/cache/scratch/audit-v4/head-b`，detached HEAD `ce50d08`（`docs: correct third audit P1 closure count`）。
- 审计方式：只读；实际运行 FastAPI TestClient HTTP/SSE、SQLite、故障注入与并发窗口注入；未修改仓库、未 commit、未联网。
- Python：`/home/ubuntu/venvs/dsh/bin/python`。
- 基线（本轮实跑）：
  - `PYTHONPATH=backend python -B -X utf8 -m unittest discover -s backend/integration -t backend` → **Ran 1270 tests, OK (skipped=9)**，112.6s。
  - `... -s backend/manager -t backend` → **Ran 235 tests, OK**，104.9s。
  - `git status --porcelain` 仅 `?? node_modules`（工作树既有未跟踪符号链接，非本次审计产生）。
- 所有探针与日志只写 `/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-b/`；临时 SQLite 库也在该目录下。仓库内无新增/修改文件。

## 0. 结论摘要

本轮共 **25 条**：P0 × 0，P1 × 1，P2 × 14，P3 × 10。

### 0.1 父任务点名项结论

| 点名项 | 本轮结论 | 关键证据 |
|---|---|---|
| **B3-01 未闭环是否可被实际利用** | **当前不可经 HTTP 实际利用；保留 P2 设计缺陷**。GET 回放字段已堵死，新卡必须一次性 capability，GET 不泄漏 capability/hash；仓库没有创建审批卡的 HTTP 路由，HTTP `/evaluate` 也触发不了唯一的内部制卡路径（fallback）。但制卡者仍拿到 capability 可自批，`resolved_by` 仍是声明；作者没有独立 capability 交付通道。接入执行器/卡片生产后即回到 P1。 | `p01_approval.py`、`p13_r04.py`；路由清单只有 approvals GET + resolve POST |
| **B3-03 无 project probe** | **核心修复成立；P2 残余成立**。带 project 的 dsh/ofm/free_pool 在 `stage='probe'` 下仍强制 `allowed_projects`；但 project=None 的 probe 仍可携带正文：dsh 15,000 字通过（上限 20,000），free_pool 60,000 字直接发出且无任何长度上限。 | `p07_probe.py` |
| **B3-06..20 的 P2** | 06/07/08/09/10/11/15/17/18/20 仍开放（07 由“稀疏丢历史”变为“>200 条仍丢最旧”）；12 残余 P3；13/14/16/19 已关闭。 | 见 §5 |
| **R-02 是否引入新状态机问题** | **是，且是 P1**：`start_amendment` 现在把 `awaiting_approval` 任务也置 held 并 supersede 其审批卡；随后 `/evaluate` 会把 held 全部改回 pending（无审批放行），不回评估则任务永久卡在 awaiting 且无卡；amend 后再 resume 也会 pending + 卡死亡。仅“单独 resume”被 R-02 修好。 | `p02_amend_approval.py` |
| **R-03 是否引入新状态机问题** | 核心成立（按 project + 24h + unrecorded per-project fail-closed）；但 `costs.py:504/914` 仍写 project-less gap，任何一本书的 finalization/settlement 失败会 24h 阻断所有书的付费回退；`resolve_gaps` 没有 HTTP/maintenance 调用者，只能等窗口过期。 | `p06_gaps.py` |
| **R-04 是否引入新状态机问题** | 绑定校验本身成立：legacy 卡必须回传指纹/作用域/revision，任意 capability 不能绕过。但升级迁移只加列不回填：旧卡字段又不再由 GET 返回，升级后已有 pending 旧卡在 HTTP 上无法批准（永久 pending/不可操作）。 | `p13_r04.py`、`p01_approval.py` |
| **SSE/回放/预算/改令 TOCTOU** | 稀疏回放已修（144/144）；`after_seq`、`/api/chief/room/stream`、跨进程 wake 仍缺；>200 条 fresh 只给最新 200（无 from-0 语义，overflow 0 重连也走 fresh）；预算 count-only cap、双记账、reserved 崩溃占用未修；amend/resume 的 cancel TOCTOU 已修，evaluate/release 仍会把 cancelled amendment 改成 evaluated/released。 | `p03`/`p04`/`p05`/`p16` |

### 0.2 编号总表

| 编号 | 级别 | 标题 | 主位置 |
|---|---|---|---|
| B4-01 | P1 | 改令把 `awaiting_approval` 置 held 后评估/恢复直接变 pending：审批绕过 + 无卡死锁（R-02/B3-14 回归） | `agent_hub.py:333,386,405-413,471-475,586-595` |
| B4-02 | P2 | B3-01 残余：制卡者自批、作者无 capability 交付通道 | `agent_room.py:514-639` / `api_v085.py:392-442` |
| B4-03 | P2 | B3-03 残余：无 project probe 可带正文；free_pool 完全不限长 | `provider_client.py:57-80` / `free_pool.py:160-176` |
| B4-04 | P2 | R-03 残余：project-less gap 跨书阻断 24h；`resolve_gaps` 无入口 | `costs.py:504,914,227` |
| B4-05 | P2 | R-04 残余：legacy 卡升级后无法从 GET 取得绑定字段，永久不可批 | `agent_room.py:544-551,600-609` |
| B4-06 | P3 | B3-12 残余：cancel 已提交后 evaluate/release 仍把 amendment 改成 evaluated/released | `agent_hub.py:434-437,489-511,517-538` |
| B4-07 | P3 | B3-25 残余：有 directive_id 但无成本 DB 时 guard 静默不生效 | `model_gateway.py:209-214` / `costs.py:312-319` |
| B4-08 | P3 | `max_calls=1.9` 被 `int()` 静默截断为 1 | `api_v085.py:70-85` |
| B3-06 | P2 | SSE 事件模型与设计相反：生命周期不写事件，瞬态永久落库 | `agent_room.py:29,412-448` |
| B3-07 | P2 | 稀疏 fresh 回放已修；>200 条无 from-0 语义，overflow full_reload 不能确定性补齐 | `api_v085.py:257-266` / `agent_room.py:485-511,846-860` |
| B3-08 | P2 | `after_seq`、`/api/chief/room/stream` 仍不存在；跨进程 wake 仍孤儿 | `api_v085.py:220` / `app.py:1258-1273` |
| B3-09 | P2 | count-only 护栏仍把 `budget_cap_cny` 每笔记 0，正数上限永不可达 | `costs.py:325-327,378-382` |
| B3-10 | P2 | 指令护栏与 AIService 仍双记 `request_budget` | `model_gateway.py:206-214` / `ai_service.py:204` |
| B3-11 | P2 | `Attempt` 仍不 `mark_dispatched`；reserved 崩溃占用无回收 | `costs.py:804-855` / `maintenance.py`（无恢复） |
| B3-13 | — | 已关闭：cancel 覆盖 awaiting_approval/paused_budget；resume 释放 paused_budget | `agent_hub.py:553-556,589-592` |
| B3-14 | — | 已关闭（但触发 B4-01）：连续改令保留原状态；pending 也被 hold | `agent_hub.py:398-413,534` |
| B3-15 | P2 | `/evaluate` 仍不传 evaluator；`amendment_fallback` 卡批准后仍无消费者 | `api_v085.py:363-366` / `agent_hub.py:471-487` |
| B3-16 | — | 已关闭：0/负/超大/dict/list/非法字符串均 400，不再 500 | `api_v085.py:70-99,337-338` |
| B3-17 | P2 | 默认 sender_role 已改 system；显式 `"author"` 仍可冒充 | `api_v085.py:58-68,316` |
| B3-18 | P2 | `local_route` 否定/长句误判未修 | `agent_hub.py:192-204` |
| B3-19 | — | 已关闭：`approved` 必须严格 bool | `api_v085.py:409-414` |
| B3-20 | P2 | 工具表 `risk` 仍从不被读取，高风险 DAG 无审批 | `agent_hub.py:31-56,126-180,260-294` |
| B3-21 | P3 | `bind_session_to_project` 仍绕过 `broadcaster.publish` | `agent_room.py:307-326` |
| B3-22 | P3 | session-only 读取器仍跨书；仅 `recent_events` 加了 `project_id IS NULL` | `agent_room.py:381-399,451-482,642-663` |
| B3-23 | P3 | 默认 session=`author` 的预建书行仍可被任一本书认领；400 仍先 bind | `api_v085.py:306-320` / `agent_room.py:307-326` |
| B3-24 | — | 已关闭：cursor clamp 到 2^63-1；回放帧也 ack | `api_v085.py:228-230,249-253` |
| B3-25 | — | 核心已关闭：guard 无 directive_id 直接报错；见 B4-07 no-db 残余 | `costs.py:316-319` / `model_gateway.py:191-196` |
| B3-26 | P3 | `op_id` 仍只是标签：同 op_id 两次真实调用两次、两行 | `model_gateway.py:1-8,189,209-214` |
| B3-27 | — | 已关闭：`costs.scope` 现在带 db，invoke_sync 线程内 Attempt 能写 usage_events | `model_gateway.py:220-222` |
| B3-28 | P3 | tokens 字符串上限已修；`max_chapters` 仍把 chapter 0 当一章 | `costs.py:366-371,692-696` |
| B3-29 | P3 | 写函数仍不 `initialize`（新库 OperationalError）；ghost project 仍可写 | `agent_room.py:207-235,514` / `api_v085.py` room 端点 |
| B3-30 | P3 | 过期卡已从 pending 列表隐藏，但 DB status 仍是 pending | `agent_room.py:656-663` |
| B3-31 | — | 已关闭：无候选抛 `no_model_candidate` | `provider_client.py:234,256` |

---

## 1. B4-01 [P1] 改令把 awaiting_approval 置 held 后评估/恢复直接变 pending：审批绕过 + 无卡死锁（R-02/B3-14 回归）

**位置**
- `backend/integration/agent_hub.py:333`：`HOLDABLE_STATUSES = {"running","waiting","pending","awaiting_approval","paused_budget"}`（本轮新加入 `awaiting_approval`）。
- `backend/integration/agent_hub.py:386`：`start_amendment` 在任何 task 处理之前 `_supersede_pending_approvals(db, directive_id, stamp)`，无条件作废该指令全部 pending 卡。
- `backend/integration/agent_hub.py:398-413`：读任务状态；`awaiting_approval` 落入 `HOLDABLE_STATUSES`，被 `UPDATE ... status='held', wait_reason='awaiting_approval|...'`。
- `backend/integration/agent_hub.py:471-475`：HTTP `/evaluate` 不传 evaluator，确定性结果把所有 held 任务放进 `wait_and_redo`。
- `backend/integration/agent_hub.py:501-504`：`wait_and_redo` 执行 `UPDATE ... SET status='pending' ... WHERE status='held'`。
- `backend/integration/agent_hub.py:586-595`：`resume_directive` 的 `awaiting` 集合只扫描当前 `status='awaiting_approval'` 的任务；已被改令置 held 的等待审批任务不在集合内，于是 `held` 被 `UPDATE ... status='pending'`，且其卡不在 `keep_task_ids`，被 supersede。
- `backend/manager/api_v085.py:340-352`、`:354-366`：这两个状态转换都是公开 HTTP 端点，写操作只需要静态头 `X-Novel-Helper: 1`。

**机制**

新代码把 `awaiting_approval` 也当作可 hold 状态，但没有同步处理“审批”语义：

1. **审批绕过（A 场景）**：任务 T 正在 `awaiting_approval`，有 pending 卡 C。`POST /amend` 带 `task_ids=[T]` 后，C 被 superseded，T 变 `held`；随后 `POST /evaluate`（HTTP 不传 evaluator，永远确定性）把 T 从 `held` 改回 `pending`。T 现在可被任何 worker claim，而 C 已死、审批从未发生。
2. **死锁（F 场景，最常见）**：`POST /amend` 只传文字、不传 `task_ids`（或 `fallback="continue"`）时，T 不被 hold，但 C 仍被 supersede；T 永久停在 `awaiting_approval`，而当前仓库没有任何 HTTP 路由能再创建一张卡，`pending_approvals` 也看不到 superseded 卡，`resolve` 409。任务永久不可操作。
3. **R-02 漏洞（C 场景）**：先 `POST /amend` 带 `task_ids=[T]`，再 `POST /resume`。`resume` 的 `awaiting` 集合为空（T 是 held），于是 T 变 `pending`、C 仍 superseded。R-02 的测试只覆盖“单独 resume”，没有覆盖“amend 后 resume”。

`GET /api/projects/{identity}/chief` 的 `snapshot.tasks` 会公开返回 `awaiting_approval` 任务的 id/status（实测 `[('tsk_49cfbd11','awaiting_approval')]`），所以调用者不需要读库就能拿到 `task_ids`。

**影响**

- 只要该指令下已存在 `awaiting_approval` 任务（执行器接入后即常态），任何能调用本机 HTTP 的 agent/进程都可以把它改成 `pending`，绕过审批门禁；也可以仅凭一条文字改令让作者的待批卡全部作废，导致审批永久卡死。这与 R-02 注释“requeueing it while superseding the card would be an approval bypass”直接矛盾。
- 在接入执行器后，`pending` 任务会被真实 claim/执行；对 `request_publish_authorization` 等高危工具就是无审批发布。
- `fallback="continue"` 和无 `task_ids` 的正常改令都会触发死锁，属于常规作者操作即可踩中的功能回归，不只是恶意路径。

**最小修复**

- 不要 hold `awaiting_approval` 任务（从 `HOLDABLE_STATUSES` 中移除），并且在 `start_amendment` supersede 卡时，对仍处于 `awaiting_approval` 的任务保留其卡或**立即创建新 revision 的替代卡**；只 bump revision 而不补卡，必然留下死卡。
- `fallback="continue"`/空 `task_ids` 不应 supersede 未受影响任务的卡；至少只 supersede 被本次 amendment 实际 hold/重排的任务卡。
- `resume_directive` 的 `awaiting` 集合应同时包含 `status='awaiting_approval'` 与 `status='held' AND wait_reason LIKE 'awaiting_approval|%'` 的任务，并在释放时恢复 `awaiting_approval`、保留其卡；或明确在此路径重新制卡。
- 补测试：amend(wait)+evaluate、amend(continue)、amend(no task_ids)、amend+resume 四个矩阵，断言“awaiting 任务仍然 awaiting 且卡仍 pending/可解析”，或“有新的可解析卡”。

**探针 / 输出**

`p02_amend_approval.py`（真实 TestClient HTTP）：
```text
A amend: 200
A after amend: {'task': 'held', 'card': 'superseded', 'directive': 'amended'}
A evaluate: 200 evaluated
A after evaluate: {'task': 'pending', 'card': 'superseded', 'directive': 'amended'}
A pending cards: []
B amend(continue): 200
B state: {'task': 'awaiting_approval', 'card': 'superseded', 'directive': 'amended'}
B pending cards: []
B resolve superseded card: (409, 'approval_not_pending')
F amend no task_ids: 200 awaiting_approval superseded []
C resume: 200 1
C state: {'task': 'pending', 'card': 'superseded', 'directive': 'running'}
D resume only: 200 0
D state: {'task': 'awaiting_approval', 'card': 'pending', 'directive': 'running'}
```
（A=审批绕过；B/F=死锁；C=amend 后 resume 绕过；D=R-02 单独 resume 的对照，只有该路径正常。）

---

## 2. B4-02 [P2] B3-01 残余：制卡者自批、作者无 capability 交付通道

**位置**
- `backend/integration/agent_room.py:514-535`：`create_approval` 生成 `secrets.token_urlsafe(32)`，只存 `_capability_hash`，并把明文 `capability` 放进返回 dict。
- `backend/integration/agent_room.py:538-551`：`get_approval` 从返回中移除 `capability_hash`、`artifact_fingerprint`、`approved_scope_hash`、`directive_revision`。
- `backend/integration/agent_room.py:592-609`：新卡要求 capability，legacy 卡要求回传指纹/作用域/revision。
- `backend/manager/api_v085.py:392-442`：只有 GET 列表和 POST resolve；**没有创建审批卡的路由**。
- `backend/integration/agent_hub.py:477-487`：唯一的卡生产者是 `evaluate_amendment` 的异常 fallback；它把包含 capability 的 `approval` 返回给调用者，但 HTTP `/evaluate` 从不传 evaluator，所以这条路径经 HTTP 不可达。

**机制 / 实际可利用性**

- 旧 P1 攻击链（GET 卡 → 回读 `artifact_fingerprint`/`approved_scope_hash`/`directive_revision` → POST 原样回传 → 自批）**已关闭**：GET 不再返回这三个字段；新卡不带 capability 直接 403。
- 但 capability 只交给**制卡者**。如果未来执行器/worker 在 agent 进程内调用 `create_approval`，它同时拿到 capability，可以自行 `POST /resolve`（`resolved_by` 由服务端强制写 `author`，不证明身份）——即制卡者自批。当前仓库没有生产制卡者（只有 HTTP 不可达的 fallback），所以**不是当前 HTTP 可利用漏洞**；一旦接入执行器/审批 UI 就会恢复为 P1。
- 作者没有独立的 capability 交付通道：`create_approval` 的明文只在返回 dict 里，manager 没有任何接口把它送到作者 UI；因此即使有卡，作者也无法从 HTTP 获得 capability（除非制卡者转发）。这是 B3-01 未闭环的核心，不是“已修”。
- legacy 卡（`capability_hash IS NULL`）仍然只靠回传绑定字段；而 GET 已不返回这些字段，升级后旧 pending 卡在 HTTP 上永久不可批（见 B4-05）。

**影响**

- 当前没有完整的“制卡 → 作者审批”HTTP 闭环；审批功能处于 library-only 状态。
- 一旦制卡方是 agent/worker，审批边界仍然可被制卡者自己跨过；`resolved_by` 仍是声明。
- 旧库升级会留下无法处理的 pending 卡。

**最小修复**

- 把“创建卡”和“持有 capability”分离：制卡 API 不应把 capability 返回给 agent 进程；由服务端通过作者会话/IPC/OS 用户把 capability 交付给作者 UI（一次性、短期、绑定 approval_id）。
- 对 `create_approval` 的调用方做身份区分：worker 只能请求卡，不能获得 capability；capability 只能通过作者通道领取。
- 迁移旧卡：启动时把 `capability_hash IS NULL` 的 pending 卡生成 capability 并标记迁移，或明确置 `expired` 并提供“重建卡”路径；不要留下不可操作的行。
- 如果短期不做身份通道，至少把“制卡者 capability”限制为只可由 author UI 进程领取，并在 API 层拒绝 agent 进程的 resolve。

**探针 / 输出**

`p01_approval.py`：
```text
approval routes: [('/api/projects/{identity}/approvals', ['GET']), ('/api/projects/{identity}/approvals/{approval}/resolve', ['POST'])]
GET /api/projects (no header): (200, [{'id': '78470364917d869c', 'path': '.../book-a', ...}, {'id': '10864cf66ce35df7', 'path': '.../book-b', ...}])
GET /approvals (no header) status: 200
listed fields: ['created_at','decision','detail','directive_id','expires_at','id','kind','project_id','resolved_at','resolved_by','session_id','status','task_id','title']
leaked binding fields: {'artifact_fingerprint': None, 'approved_scope_hash': None, 'directive_revision': None, 'capability': None, 'capability_hash': None}
resolve with echoed fields, no capability: (403, 'approval_capability_required')
resolve as agent with capability: (403, 'agents_cannot_approve')
resolve with creator capability: (200, 'approved', 'author')
amend HTTP: (200, 2)
evaluate HTTP: (200, [...], 'evaluated', False)   # 无 approval 键，HTTP 无法触发 fallback 制卡
pending cards after HTTP evaluate: []
```
`p13_r04.py`：
```text
wrong capability: 403 approval_capability_invalid
capability + wrong fingerprint: 409 approval_artifact_changed
missing approved: 400 invalid_request
approved='false': 400 invalid_request
R-04 legacy + arbitrary capability: 400 approval_binding_required
R-04 legacy + arbitrary capability + binding: 200 approved
new card first resolve: 200 approved
new card replay: 409 approval_not_pending
```

**结论**：第三轮把 B3-01 记为 P1（身份缺陷）在“设计/未来接入”意义上仍成立；但按“ce50d08 当前 HTTP 实际可利用性”应降为 **P2 latent**——没有卡片创建入口、没有 capability 泄漏、HTTP evaluate 触发不了 fallback。不能以“GET 已隐藏字段”当作闭环。

---

## 3. B4-03 [P2] B3-03 残余：无 project probe 可带正文；free_pool 完全不限长

**位置**
- `backend/integration/provider_client.py:57-60`：`PROBE_MAX_PAYLOAD_CHARS = 20000`。
- `backend/integration/provider_client.py:63-80`：`_authorize_project`：有 project 时强制 `allowed_projects`；无 project 时只要求 `stage='probe'` 且 payload ≤ 20,000 **字符**。20,000 字符足够一整章中文正文。
- `backend/integration/provider_client.py:141`、`:151`：dsh/ofm 两个协议都走该检查。
- `backend/integration/free_pool.py:160-176`：`is_probe = stage == 'probe'`；`if project:` 才校验 `allowed_projects`；project=None 时直接返回 `(RUNTIME_ROOT, rows)`，**没有任何 payload 长度检查**（`_choices` 不接收 messages）。
- `backend/integration/model_gateway.py:185`、`:220`：`stage` 是调用方参数，原样进入 `costs.scope`，无 allowlist。

**机制**

带 project 的旁路已被修：即使 `stage='probe'`，`/unauthorized/book` 也会被 `allowed_projects` 拒绝。但“probe”仍被当作“可以不带 project”的授权依据：

- dsh/ofm：project=None + `stage='probe'` + 15,000 字正文 → 通过检查，消息进入共享渠道；只有超过 20,000 字符才拒绝。
- free_pool：project=None + `stage='probe'` + 60,000 字 → 无任何检查；`_run` 直接把 messages 交给免费池客户端。
- 调用者只要把 `stage` 设为 `probe` 并省略 project，就能把任意书（未在 `allowed_projects`）的正文送到共享渠道；`ModelGateway.invoke` 是公共出口，`stage` 没有 allowlist。

**影响**

- 隐私硬边界仍可被绕过：`allowed_projects` 只对“带 project 的调用”有效，匿名 probe 变成任意正文通道。
- free_pool 无长度上限，问题比 dsh 更大；20,000 字符的 dsh 上限也不是“探测 payload”的量级（一个连接测试只需几十字节）。
- 当前 HTTP 入口的 probe 都发固定小 payload（`provider_api.py:129`、`role_checks.py:112`、`worker.py:68`），所以是 **latent/library-level P2**；接入 agent 调用后即成为真实泄漏路径。

**最小修复**

- 不再用 `stage` 作授权：probe 走独立 `probe_connection()`，只允许固定 payload（例如 `<64` 字符），不接受调用方 messages/正文。
- 无 project 的 probe 一律禁止携带 messages（或只允许固定 “Reply only OK.”）；有 project 的调用无论 stage 都必须校验 `allowed_projects`。
- free_pool 在 `_run`/`chat_stream` 入口加与 dsh 相同的 payload 上限，但上限应降到探测级别（≤1,024 字符），不是 20,000。
- `ModelGateway.invoke` 对 `stage` 做 allowlist，并拒绝在 scope 外部设置 `probe`。

**探针 / 输出**

`p07_probe.py`：
```text
dsh, no project, stage=probe, 15000 chars: AUTHORIZED (messages reach the channel)
dsh, no project, stage=probe, 25000 chars: blocked: 连接测试仅允许无作品的小型探测请求，已停止发送
dsh, unauthorised project, stage=probe: blocked: 此作品尚未授权免费渠道处理正文与记忆
dsh, no project, stage=draft: blocked: 此作品尚未授权免费渠道处理正文与记忆
free_pool, no project, 60000 chars: sent=ok bytes=60033 prefix=密密密密密密密密密密密密
free_pool, unauthorised project, stage=probe: blocked: 此作品未授权免费渠道处理正文与必要记忆
gateway stage=probe: accepted, scope stage='probe', project=None
```

---

## 4. R-02/R-03/R-04 复核

### 4.1 R-02：单独 resume 正确，amend 交互错误（B4-01）

- `p02` D 场景：仅 `POST /resume`，任务保持 `awaiting_approval`、卡保持 `pending`，R-02 的目标成立。
- `p02` A/B/C/F 场景：只要经过 `start_amendment`，R-02 就失效（详见 B4-01）。
- 测试 `test_agent_hub.py:261-272` 只覆盖“单独 resume”，没有 amend 组合，因此全绿不能证明 R-02 覆盖完整。

### 4.2 R-03：核心修好，残余 project-less gap

**位置**
- `backend/integration/costs.py:136-160`：`record_gap(db_path, kind, project=None)` 现在写 `project`/`resolved_at`。
- `backend/integration/costs.py:164-206`：`ledger_gaps` 支持 24h + project；project-less 旧 gap 仍对所有 project 生效。
- `backend/integration/costs.py:194-207`：`unrecorded_gap_count(project)` 按 project + `"*"` 汇总。
- `backend/integration/costs.py:504`：`settle_request` 找不到行时 `record_gap(db_path,'budget_settlement_missing')`，**没有 project**。
- `backend/integration/costs.py:914`：`Attempt.finish` 异常时 `record_gap(self.db_path,'finalization_failed')`，**没有 project**。
- `backend/integration/costs.py:227`：`resolve_gaps` 没有 API/maintenance 调用者（grep 只有定义与测试）。
- `backend/integration/run_report.py:240`：run report 仍调用 `ledger_gaps(ledger)` 不带 project，会把别的书的 gap 算进本次运行。

**机制 / 影响**

- 单本书的 finalization/settlement 失败会写 project-less gap，`fallback_budget.reserve` 对所有 project 都会 24h 拒绝付费回退（`p06`：A、B 同时 blocked）。不是永久，但跨书污染。
- `resolve_gaps` 无法从 HTTP/维护入口调用；用户只能等 24h 或手工改 `.gaps/*.json`，所以“可 resolve”在运行产品里不可达。
- 其余 R-03 目标成立：按 project 的 recent gap 只阻断该书（`p06`：A allowed / B blocked）、48h 旧 gap 不阻断、gap 写失败时 per-project fail-closed（A blocked / B allowed）。

**最小修复**

- `costs.py:504` 与 `:914` 传入当前 event 的 project（`row['project']` / `self.event['project']`）；实在拿不到时不要写全局 gap，改为进程内 `UNRECORDED_GAPS['*']` 并明确告警。
- 增加 maintenance/API `POST /api/maintenance/costs/resolve-gaps`（author-only）调用 `resolve_gaps`，或在 `/api/costs` 提供按钮。
- `run_report` 传 project，避免别的书的 gap 影响本次 job 的 `complete`。

**探针 / 输出**

`p06_gaps.py`：
```text
A with only B's recent gap: allowed
B with its own recent gap: blocked
B after resolve_gaps: allowed
A with only a 48h-old gap: allowed
A with a project-less recent gap: blocked
A after resolving the global gap: allowed
unrecorded counts A/B: (1, 0)
A with unrecorded gap: blocked
B while A has unrecorded gap: allowed
A after project-less finalization_failed: blocked
B after project-less finalization_failed: blocked
settle no-usage outcome / gap files before-after: cancelled 4 4
A after a failed fallback settled as cancelled: allowed
settle unknown outcome / gap files before-after: unknown 4 4
```

### 4.3 R-04：绑定校验成立，legacy 迁移不可操作（B4-05）

**位置**
- `backend/integration/agent_room.py:600-609`：legacy 卡（`capability_hash` 为空）必须回传 `artifact_fingerprint`、`approved_scope_hash`、`directive_revision`，否则 400。
- `backend/integration/agent_room.py:544-551`：`get_approval` 已不再返回这些字段。
- `backend/integration/agent_room.py:667-672`：`pending_approvals` 同样移除这些字段。
- `backend/integration/agent_room.py:187-191`：迁移只 `ALTER TABLE ... ADD COLUMN capability_hash`，不回填。

**机制 / 影响**

- 安全语义正确：随便给一个 capability 不能绕过 legacy 卡的绑定回传（`p13`：400）。
- 但升级后的旧 pending 卡需要三个绑定字段，HTTP 已经拿不到；旧 UI 也没有缓存。结果是旧卡永久不可批、且一直出现在 pending 列表（`p01` legacy 卡仍在列表），作者只能删库或手工改状态。
- 这是一个升级路径的功能回归，不是新的授权绕过；级别 P2。

**最小修复**

- 迁移时为每个 legacy pending 卡生成新 capability（存 hash），通过作者通道交付；或统一把 legacy pending 卡置 `expired` 并在 UI 提供“重建审批卡”。
- 不要同时要求“绑定字段”又隐藏字段；若保留 legacy 回传，则 GET 至少对本地作者返回一次性绑定值，但这会把旧攻击面重新打开，不如迁移。

**探针 / 输出**

`p13_r04.py`：
```text
R-04 legacy + arbitrary capability: 400 approval_binding_required
R-04 legacy + arbitrary capability + binding: 200 approved
```
`p01_approval.py`：legacy 卡 GET 字段与普通卡相同（无指纹/作用域/revision），但仍在 pending 列表。

---

## 5. B3-06..20 逐项状态

### B3-06 [P2] SSE 事件模型仍与设计相反

**位置**：`agent_room.py:29`（`TRANSIENT_KINDS` 只用于 `:846` 溢出分支）、`:412-448`（`append_event` 无条件 INSERT）、`api_v085.py:212,313`（只有 chat 消息写事件）；`agent_hub.py` 无任何 `append_event` 调用。

**机制/影响**：directive/task/approval/amendment 全生命周期仍 0 条 `agent_events`；`progress_signal`/`draft_updated` 仍永久落库并进入 `chat_context`/`snapshot`，会挤占 100/200 条窗口。`p08`：生命周期后 `events=[]`，随后两条 transient 均落库，`max_seq=2`。

**最小修复**：增加 `publish_transient`（只广播不落库）；在 create/resolve/amend/cancel/task 状态变化处写持久事件（最好与业务事务同事务 outbox）；`append_event` 拒绝 transient kind。

**探针**：`p08_events.py`：
```text
events after full directive/task/approval lifecycle: []
events after transient signals: [('progress_signal', '正在写第3章 40%'), ('draft_updated', '草稿有变化')]
TRANSIENT_KINDS: ['draft_updated', 'live_preview_delta', 'progress_signal']
chat_context sees transients: [('progress_signal', ...), ('draft_updated', ...)]
```

### B3-07 [P2] 稀疏回放已修；>200 条仍丢最旧，overflow full_reload 仍补不齐

**位置**：`api_v085.py:257-266`（fresh 用 `recent_events` 取本项目最新 200）、`agent_room.py:485-511`（`recent_events`）、`:735-737`（snapshot 上限 100）、`:846-860`（overflow marker）。

**机制/影响**：
- 稀疏场景已修：`p16` 100 A + 156 B + 44 A，fresh 回放 144/144，seq 1..300 全部到达。
- >200 条仍丢：`p04` A 300 条，fresh 只回放 200（257..456），最旧 100 条（1..100）不出现；snapshot 只给 100（357..456）。
- overflow `resync_required` 的 `seq` 仍是最后 ack（未 ack 时为 0）；客户端带 0 重连会走 fresh 分支（最新 200），不能确定性地补回最旧 100 条。`after=0` 被“fresh”占用，没有 `after_seq=0`/`before_seq` 的“从 0 分页”语义；客户端若硬猜 `Last-Event-ID: 1` 可拿到 2..（`p04` 299 条），但项目自己拥有 seq 1 时仍丢第 1 条，且 fresh/overflow 文档路径不会给出这个值。

**最小修复**：提供 `after_seq=0` 真正的“从头分页”语义（用独立 `fresh=1` 区分），或让 overflow marker 携带 `oldest_available_seq` 并允许分页；snapshot 至少覆盖与 SSE 相同的 200 条。

**探针**：`p16_sparse.py`（稀疏 144/144）、`p04_sse.py`：
```text
A total / seq range: 300 (1, 456)
HTTP fresh replay count / range: 200 (257, 456)
HTTP fresh lost oldest A events: 100
HTTP ?after_seq=1 count / range: 200 (257, 456)
HTTP Last-Event-ID:1 count / range: 299 (2, 456)
snapshot seq: 456 events: 100 range: (357, 456)
HTTP fresh + snapshot covers oldest seq 1: False
```

### B3-08 [P2] `after_seq`、会话流、跨进程 wake 仍缺

**位置**：`api_v085.py:220`（`room_stream(identity, request, last_event_id="")`，无 `after_seq`）、`:268`（只订阅 `agent_room.broadcaster`）、`app.py:1258-1273`（`/internal/events/notify` 只 publish 到 `event_fanout`）、`:277`（15s queue wait，无 500ms DB 短读）。

**机制/影响**：
- `?after_seq=1` 被 FastAPI 忽略，等价 fresh：`p04` 返回 200（257..456），显式 `Last-Event-ID:1` 才返回 299（2..456）。
- `/api/chief/room/stream` 仍 404（`p04`），预建书阶段无实时流。
- `event_fanout` 启动时 0 订阅者；`/internal/events/notify` 返回 200 但丢弃，`agent_room.broadcaster` 也 0 订阅者（`p14`）；子进程事件不会唤醒 manager SSE。

**最小修复**：加 `after_seq`（header 优先/query 次之）；加 `/api/chief/room/stream?session_id=...`（并加 `project_id IS NULL`）；让 `room_stream` 订阅 fanout 或在 notify 时 publish 到 broadcaster，并加 500ms 短读兜底。

**探针**：`p04_sse.py` / `p14_wake.py`：
```text
HTTP ?after_seq=1 count / range: 200 (257, 456)
GET /api/chief/room/stream: 404
fanout subscriber count at startup: 0
notify HTTP: (200, {'ok': True, 'subscribers_dropped': 0})
fanout subscriber count after notify: 0
room broadcaster subscribers: 0
```

### B3-09 [P2] count-only 护栏仍把 `budget_cap_cny` 每笔记 0

**位置**：`costs.py:325-327`（`count_only and amount is None` → `reserve_amount=0`）、`:378-382`（cap 检查用 `usage['cost_cny'] + reserve_amount`）、`model_gateway.py:209-214`（`count_only=True, cost_cny=None`）。

**机制/影响**：每行 `cost_cny='0'`，`budget_cap_cny=1` 时 `0+0>1` 永远 False；`p05` 10 次全过、directive cost 0。真实金额路径的 cap 仍有效（对照：0.06+0.06>0.1 被拦），说明只有 count-only 模式失效。

**最小修复**：count-only 时拒绝 `budget_cap_cny`，或给每次调用传保守单价/`reserve_cost`，用真实金额做 cap；更好是单行会计（见 B3-10）。

**探针**：`p05_budget.py`：
```text
B3-09 count-only cap=1: calls: 10
B3-09 directive cost_cny: 0
B3-09 control real-cost second call: blocked (cap works with real cost)
```

### B3-10 [P2] 指令护栏与 AIService 仍双记 `request_budget`

**位置**：`model_gateway.py:206-214`（guard 分支先 reserve 一行 count-only）、`webnovel-writer/backend/services/ai_service.py:204`（每次网络尝试再 `costs.Attempt`）、`costs.py:339-344`（`today_rows` 统计所有非 released 行，`requests_per_day=len(today_rows)`）。

**机制/影响**：一条逻辑调用占 2 行（网关 + Attempt），`requests_per_day=3` 时第一条逻辑调用占 2 行，第二条的网关预留占第 3 行后 Attempt 被拒；`p05`：outcomes `['ok','BudgetExceeded']`，3 行 request_budget（`settled`/`settled`/`unknown_charge`），directive usage 只看到 2 次。限额实际减半。

**最小修复**：单行会计：网关不再为 directive guard 单独 reserve；把 `directive_id`/guard 传给 `Attempt`，让同一行承担全局+指令护栏；或网关成为唯一预留者、AIService 在带 guard 的 scope 下跳过预算预留。

**探针**：`p05_budget.py`：
```text
B3-10 requests_per_day=3 logical outcomes: ['ok', 'BudgetExceeded']
B3-10 directive usage: {'calls': 2, 'attempts': 2, ... 'cost_cny': '0', 'states': {'settled': 1, 'unknown_charge': 1, ...}}
B3-10 request_budget rows: [('settled', 20, '1', 1, ''), ('unknown_charge', 0, '0', 0, 'op-1'), ('settled', 0, '0', 0, 'op-0')]
```

### B3-11 [P2] `Attempt` 仍不 `mark_dispatched`；reserved 崩溃占用无回收

**位置**：`costs.py:804-855`（`Attempt.__init__` reserve + persist，无 dispatch）、`:462-474`（`mark_dispatched` 只有网关调用）、`:548-584`（`budget_status` 只统计）、`maintenance.py`（无 stale 恢复）；`grep mark_dispatched` 仅 `model_gateway.py:218`。

**机制/影响**：真实 AIService 路径只有 reserved/settled/failed/released，`dispatched` 永远 0。进程在 `finish` 前崩溃，reserved 行永久占用 requests_per_day/tokens/cost；`p05`：一次 reserve 后 `pending=1`，第二次 blocked，`recovery helpers in costs: []`，reserved 行保持 `('reserved',10,'0.1')`。

**最小修复**：`Attempt` 发 HTTP 前 `mark_dispatched`；增加 `recover_stale_reservations(db, older_than)`（reserved→released，dispatched→unknown_charge）并在启动/定时任务调用；加 `updated_at`/heartbeat。

**探针**：`p05_budget.py`（上方 B3-11 行）。

### B4-06 [P3]（原 B3-12 残余）amend/resume TOCTOU 已修；evaluate/release 仍有 cancel 竞争

**位置**：`agent_hub.py:373-383`（amend 条件 UPDATE）、`:571-579`（resume 条件 UPDATE）已修；`:434-437` 只在事务外检查 cancelled，`:489-511` 的写事务和 `room.update_amendment` 未再检查；`:517-538` 同样只在事务外检查，最后无条件 `UPDATE agent_amendments SET status='released'`。

**机制/影响**：注入“cancel 在读检查后、BEGIN IMMEDIATE 前提交”：
- `start_amendment`/`resume` 正确 409（`p03`）。
- `evaluate_amendment` 仍返回 evaluated，并把已 cancelled 的 amendment 改成 `evaluated`；`release_holds_for_current` 返回 released 0，但把 amendment 改成 `released`。任务仍是 cancelled，不会复活执行；影响是取消语义/审计状态不一致。

**最小修复**：在 evaluate/release 的写事务内重读 directive 或条件 UPDATE amendment `WHERE status!='cancelled'`，rowcount 0 则 409；release 不要无条件覆盖状态。

**探针**：`p03_toctou.py`：
```text
amend after concurrent cancel: HubError directive_cancelled
resume after concurrent cancel: HubError directive_cancelled
evaluate after concurrent cancel: evaluated
  directive: cancelled task: cancelled amendment: evaluated
release after concurrent cancel: released 0
  directive: cancelled task: cancelled amendment: released
```

### B3-13 [已关闭] cancel 覆盖所有活跃状态；resume 释放 paused_budget

`agent_hub.py:553-556` 的 IN 列表已含 `awaiting_approval`/`paused_budget`；`:589-592` 的 resume 释放 `held`/`paused_budget`。`p12`：cancel 后两任务均 cancelled，resume 409；`p02` E：paused_budget resume 后 pending。无回归。

### B3-14 [已关闭，但触发 B4-01] 连续改令保留原状态；pending 也被 hold

`agent_hub.py:398-413` 从 `wait_reason` 取原状态，第二次改令保留 `running`；`:534` 的 release 用 `HOLDABLE_STATUSES` 恢复。`p12`：A1/A2 后 wait_reason 仍是 `running|...`，release 回 `running`；pending 任务也被 hold。该修复同时把 `awaiting_approval` 纳入 hold，直接造成 B4-01。

### B3-15 [P2] `/evaluate` 仍不传 evaluator；fallback 卡仍无消费者

**位置**：`api_v085.py:363-366`（不传 evaluator）、`agent_hub.py:471-475`（确定性 wait_and_redo）、`:477-487`（只有 evaluator 抛异常才建 fallback 卡）、`agent_room.py:633-636`（resolve 只改卡，不读 decision）。

**机制/影响**：HTTP evaluate 永远把所有 held 变 pending，没有 Role E 分析、不会建 fallback 卡（`p12`：evaluate 200 evaluated、wait_and_redo、无卡）。直接 hub 调用传抛错 evaluator 才建 `amendment_fallback` 卡；批准后 task 仍 held、amendment 仍 fallback（`p12`：`('held','fallback')`）。

**最小修复**：API 注入 Role E evaluator（经 ModelGateway + guard），失败建卡；增加卡决策消费者（放行/重评/取消）；在消费者存在前不要把卡暴露为可操作。

**探针**：`p12_amend_matrix.py`：
```text
B3-15 HTTP evaluate: (200, 'evaluated', ['tsk_...'], 'pending')
B3-15 cards after evaluate: []
B3-15 fallback resolve: (200, 'approved')
B3-15 after card approval: ('held', 'fallback')
```

### B3-16 [已关闭] 指令创建输入不再 500

`api_v085.py:70-99` 校验 `max_calls`/`budget_cap_cny`；`agent_room.py:213-223` 再做库级校验。`p09`：0/-1/10^30/1e30/True/"abc"/dict/list/"not-a-number"/1e30 全部 400 invalid_request，无 500。遗留极小问题：`max_calls=1.9` 被 `int()` 截成 1（B4-08，P3）。

### B3-17 [P2] 默认 sender_role 已改 system；显式 "author" 仍可冒充

`api_v085.py:58-68` 默认 `system`，`SENDER_ROLES` allowlist；`p09` 默认 system。但 `sender_role="author"` 仍直接接受（`p09` 返回 author），`chat_context` 仍把它当作者（`agent_room.py:696`）。任何本地调用者仍可显式冒充作者。

**最小修复**：不信任 body 的 role；从服务端会话/调用方身份取 `actor_kind`，author 只允许作者通道；事件记录 `actor_id`。

### B3-18 [P2] `local_route` 否定/长句误判未修

`agent_hub.py:192-204` 正则原样。`p09`：
```text
'继续写所有章节' -> system_ai_pause {'paused': False}
'恢复所有角色的默认设置' -> system_ai_pause {'paused': False}
'不要全局暂停' -> system_ai_pause {'paused': True}
'不要执行本章批注' -> run_annotations {}
```
**最小修复**：锚定句首/命令词、先检测否定前缀、对副作用 action 返回 `requires_confirmation`；补否定/长句测试。

### B3-19 [已关闭] `approved` 严格 bool

`api_v085.py:409-414` 缺字段/字符串/0/null 全部 400；`p13` 四类均 400，卡保持 pending。直接调用 `resolve_approval(approved="false")` 仍会按真值批准，但 HTTP 边界的 B3-19 已关闭（库级可另记 P3，未单列）。

### B3-20 [P2] 工具表 `risk` 仍从不被读取

`agent_hub.py:31-56` 标 high/medium；`:126-180` `validate_dag` 不读 risk；`:260-294` `route` 不附加 `requires_approval`。`p09`：`request_publish_authorization` + `create_book` DAG 通过 validate，route level 2 节点 `requires_approval=None`，返回键无 risk。**最小修复**：validate 对 high/medium 返回 requires_approval 或拒绝 Level 2 使用 high 工具；route 输出 risk；执行器派活前建卡。

---

## 6. P3 / 其他残余

### B3-21 [P3] bind 仍不 publish

`agent_room.py:307-326` 用 `_append_event_db`，不调用 `broadcaster.publish`。`p11`：
```text
B3-21 live queue empty after bind: True
B3-21 durable events after bind: ['project_bound']
B3-21 live queue after append_event: 1
```
在线 SSE 收不到绑定事件；重连回放可见。修复：事务提交后 publish。

### B3-22 [P3] session-only 读取器仍跨书

`events_after`/`max_seq`/`list_tasks`/`pending_approvals` 未统一加 `project_id IS NULL`；`recent_events` 已加（`agent_room.py:500-502`）。`p11`：
```text
events_after(session only): [('A','A-event'), ('B','B-event'), (None,'unbound')]
max_seq(session only): 5
list_tasks(session only): [('A','A-task'), ('B','B-task')]
pending_approvals(session only): [('A','A-card'), ('B','B-card')]
snapshot(session only): [(None,'unbound')]
recent_events(session only): [(None,'unbound')]
```
一旦接入 `/api/chief/room/stream?session_id=` 就会跨书；修复：统一 `project_id IS NULL`，或 `unbound_only=True` 默认。

### B3-23 [P3] 预建书认领 / 400 先 bind 未修

`api_v085.py:306-320` 先 `bind_session_to_project` 再 `append_event`；`agent_room.py:307-326` 按 session 把全部未绑定行迁走。`p11`：
```text
B3-23 B first message: 200 <book-b-id>
B3-23 B room sees pre-book text: ['开书前私密对话：结局是双胞胎']
B3-23 A room sees pre-book text: []
B3-23 invalid channel: 400 <book-b-id>
```
400 请求仍改写归属。修复：预建书 session 用 `prebook_<uuid>`；先校验/成功 append 再 bind；bind 由作者会话发起。

### B3-24 [已关闭] cursor clamp + 回放 ack

`api_v085.py:228-230` clamp `2**63-1`；`:249-253` 回放帧 ack；`:285-290` resync 帧绕过 seq 过滤。`p04`：40 位 cursor `huge cursor stream events: 0`，无 OverflowError。

### B3-25 [已关闭，残余 B4-07]

`costs.py:316-319` 在 guard 非空但 directive_id 空时 `ValueError('directive_id_required')`；`model_gateway.py:191-196` 抛 `GatewayError`。`p05`：两处均报错。残余：db_path=None 时 `costs.py:312-313` 先返回 None，guard 静默失效（B4-07）。

### B3-26 [P3] `op_id` 仍不幂等

`model_gateway.py:1-8` 头注释称幂等，`:189` 只校验非空，`:209-214` 只写入 `operation` 字段；无唯一键/缓存。`p10`：同 op_id 两次 → `service calls 2`、`request_budget rows 2`、`usage_events 2`。修复：接 `idempotency_keys` 或表唯一键 `(project,op_id,stage)`；或把注释改成 tracing id。

### B3-28 [P3] max_chapters 仍把 chapter 0 当一章

`costs.py:366-371` 用 `len(usage['chapters'])`，`:424` 把 chapter 0 加入集合；tokens 字符串上限已在 `:692-696` 修好（`p05`：`tokens('9999999999999') -> None`）。`p05`：chapter 0 调用后 chapter 1 被拦 `{'limit':'max_chapters','limit_value':'1','used':'1'}`。修复：max_chapters 统计排除 0。

### B3-29 [P3] 新库写函数不 initialize；ghost project 可写

`agent_room.py:207-235`/`:514` 直接 `write_tx`，只有读函数 initialize。`p10`：fresh DB `create_directive`/`create_approval` 均 `OperationalError no such table`。`p11`：ghost identity 的 message/directive/snapshot 全 200。修复：写函数开头 initialize；room 端点先 `project(identity)` 校验。

### B3-30 [P3] 过期卡列表已隐藏，DB 状态仍 pending

`agent_room.py:656-663` pending 查询过滤 `expires_at > now`；`p10`：过期卡不在列表，但 DB `status='pending'`。功能上已被隐藏，状态卫生/审计仍不一致；修复：定期扫过期置 expired，或在列表读取时顺手更新。

### B4-07 [P3] guard + 无成本 DB 静默不生效

`model_gateway.py:209-214` 只在 `db_path is not None` 时 reserve；`costs.py:312-313` 在 guard 检查之前 `if not db_path: return None`。`p15`：
```text
gateway db_path=None + guard: ok service calls: 1
reserve_request(db_path=None, guard=..., directive_id=...): None
```
调用方以为 `max_calls`/`budget_cap_cny` 生效，实际 0 行、无限制。修复：guard 非空但无 db 时拒绝；把 guard 校验移到 `if not db_path` 之前。

### B4-08 [P3] `max_calls` 浮点静默截断

`api_v085.py:70-85` 用 `int(value)`；`p09`：`max_calls=1.9` → 200，返回 1；`"5"` → 5。调用方写 1.9 期望 2 或报错，实际 1。修复：要求整数（`float.is_integer()` 或 Pydantic int），拒绝非整数。

### 会话/隔离 P3 汇总

B3-21/22/23 + B3-29 ghost 都属于“预建书/会话边界尚未闭环”。当前生产没有会话流和大量预建书写入者，所以是 latent；接入 `/api/chief/room/stream` 或开书引导后必须同时修复，否则跨书串数据。

---

## 7. 已关闭 / 无回归对照

| 项 | 本轮验证 |
|---|---|
| B3-02 审批随改令/取消失效 | **关闭**：amend/cancel 同事务 supersede；resolve 事务内读 live revision。`p13`：revision bump 后 409 `approval_directive_revision_stale`；`p01`/`p12`：superseded 卡不能 resolve。 |
| B3-05 失败回退永久 gap | **关闭（核心）**：按 project + 24h + unrecorded per-project。`p06`：B 的 gap 不阻断 A；48h 旧 gap 不阻断；失败回退无 usage → cancelled 不写 gap；未知 → unknown 不写 gap。残余 B4-04。 |
| B3-13 cancel 漏状态 | **关闭**：`p12` 两状态均 cancelled，resume 409。 |
| B3-14 running→held→release 丢状态 | **关闭**：`p12` 两次改令后 release 回 `running`；pending 也被 hold。但引入 B4-01。 |
| B3-16 输入 500 | **关闭**：`p09` 全部 400。 |
| B3-19 approved 弱转 | **关闭**：`p13` 四类 400。 |
| B3-24 超大 cursor / 回放 ack | **关闭**：`p04` 40 位 cursor 无异常；回放 ack 读码确认。 |
| B3-25 guard 无 directive | **关闭**：`p05` 两处报错；残余 B4-07。 |
| B3-27 invoke_sync 丢 META | **关闭**：`p10` `invoke_sync` 后 `usage_events=1`、request row `settled`。 |
| B3-31 无候选返回 None | **关闭**：`p10` `RuntimeError no_model_candidate`。 |
| B-04 隐私域/回退 | 未发现本轮回归；`provider_client._options` 仍按隐私域过滤（读码+既有测试）。 |

---

## 8. 测试覆盖与盲区

- 集成 1270 / manager 235 全绿，但以下关键路径没有测试：
  - `test_agent_hub.py:261-272` 只测“单独 resume 保留 awaiting 任务/卡”，**没有** amend(wait)+evaluate、amend(continue)、amend(no task_ids)、amend+resume；因此 B4-01 在全绿测试下成立。
  - `test_v085_api.py` SSE 测试覆盖稀疏 144 条和 huge cursor，但**没有** >200 条的 fresh/overflow 恢复测试；`snapshot` 100 上限与 fresh 200 的组合未被断言。
  - `test_costs_five_state.py:170-180` 只断言 count-only 行 `cost_cny='0'`，**没有**断言 `budget_cap_cny` 会被拦截；等于把 B3-09 的缺陷固化成“预期行为”。
  - 没有 `resolve_gaps` 的 HTTP/maintenance 测试；没有 legacy 卡迁移测试；没有 B3-21/22/23 的端到端会话流测试。
  - 没有“evaluate/release 与 cancel 并发”的测试（B3-12 残余）。

---

## 9. 覆盖矩阵

| 审计范围 | 本轮探针/方式 | 结论 |
|---|---|---|
| `costs` 预算预留/结算/五态 | `p05`、`p10`、grep `mark_dispatched` | B3-09/10/11 开放；B3-25 核心关闭；B4-07 残余 |
| `fallback_budget` gap/reserve/settle | `p06` | B3-05 核心关闭；B4-04 残余 |
| `model_gateway` 隐私/预算/op_id/invoke_sync | `p05`、`p10`、`p15` | B3-26 开放；B3-27 关闭；B4-07 残余 |
| `provider_client`/`free_pool` 授权 | `p07` | B3-03 带 project 关闭；无 project P2 残余 |
| `agent_room` 审批/事件/SSE/会话 | `p01`、`p04`、`p08`、`p11`、`p13` | B3-01 当前不可远程、B3-06/07/08/21/22/23/29/30 状态见上 |
| `agent_hub` 改令/评估/cancel/resume | `p02`、`p03`、`p12` | B4-01 新 P1；B3-13/14 关闭；B3-12 残余、B3-15 开放、B3-20 开放 |
| `api_v085` 输入/身份/流 | `p01`、`p09`、`p04` | B3-16/19 关闭；B3-17/18 开放；B3-08 开放 |
| SSE/回放/预算/改令 TOCTOU | `p03`、`p04`、`p16` | 稀疏已修；>200/after_seq/session/wake 未修；amend/resume TOCTOU 修、evaluate/release 残余 |
| 测试基线 | integration 1270 / manager 235 | 全绿；B4-01、B3-09/10、>200 SSE、legacy 迁移无覆盖 |

## 10. 探针清单

| 脚本 | 覆盖 |
|---|---|
| `p01_approval.py` | B3-01/B3-02：GET 枚举/字段、无 capability 403、capability 自批、legacy 卡、HTTP evaluate 无 fallback、跨项目 |
| `p02_amend_approval.py` | B4-01：amend+eval、amend(continue)、amend(no task_ids)、amend+resume、单独 resume 对照、paused_budget |
| `p03_toctou.py` | B3-12：cancel 注入 vs amend/resume/evaluate/release |
| `p04_sse.py` | B3-07/08/24：>200 fresh、after_seq、Last-Event-ID、snapshot、会话流、huge cursor |
| `p05_budget.py` | B3-09/10/11/25/28：count-only cap、双记账、reserved 无回收、guard 无 directive、chapter 0、tokens |
| `p06_gaps.py` | B3-05/R-03：project/24h/global/unrecorded gap、settle cancelled/unknown、project-less 跨书 |
| `p07_probe.py` | B3-03：dsh 15k/25k、unauthorized project、free_pool 60k、gateway stage |
| `p08_events.py` | B3-06：生命周期 0 事件、transient 落库、chat_context |
| `p09_inputs.py` | B3-16/17/18/20：输入 400、sender_role、local_route、高风险 DAG |
| `p10_misc.py` | B3-26/27/29/30/31：op_id、invoke_sync、fresh DB、过期卡、无候选 |
| `p11_room_isolation.py` | B3-21/22/23/29：bind 不 publish、session 跨书、预建书认领、400 bind、ghost |
| `p12_amend_matrix.py` | B3-13/14/15：cancel 全状态、连续 hold、HTTP evaluate、fallback 卡无消费者 |
| `p13_r04.py` | R-04/B3-02/B3-19：legacy 绑定、revision stale、strict bool、capability 一次性 |
| `p14_wake.py` | B3-08：fanout 0 订阅者、notify 丢弃、broadcaster 0 订阅者 |
| `p15_guard_nodb.py` | B4-07：db_path=None + guard 静默放行 |
| `p16_sparse.py` | B3-07：稀疏 100+156+44 fresh 144/144 |

所有脚本及 `*.log` 在 `/home/ubuntu/.hermes/cache/scratch/audit-v4/tmp-b/`。

---

## 11. 未覆盖 / 限制

- 未修改仓库、未联网；HTTP 探针使用 FastAPI TestClient/ASGI，未启动真实 8765 端口；SSE 通过 TestClient 流读取，未做真实浏览器端解析。
- `agent_tasks` 目前仍没有生产 executor/creator；B4-01、B3-15、B3-20 等涉及任务执行的项是“状态机/HTTP 已成立，端到端执行需接入 executor”。B4-01 的初始 `awaiting_approval` 任务在本轮由库调用创建；其 `task_ids` 可经 `GET /chief` 公开获得，HTTP 侧的 amend/evaluate 全链路已实测。
- B3-01/B3-03 的残余是 latent/library-level：当前没有 HTTP 制卡入口，probe 的 HTTP 调用方都发固定小 payload；一旦接入 agent 制卡或让调用方控制 probe messages，即变为实际可利用。
- B3-12 的并发窗口用故障注入（在事务入口前提交 cancel），未做 OS 级 kill/锁压测；与真实并发提交同一代码路径。
- 未复核 annotations/text_merge 的其余修复（B3-04 属其他域）；未做 Windows 路径/真实局域网配对/前端 SSE 解析器端到端。

## 12. 优先级建议

1. **B4-01**：先修 `start_amendment`/`evaluate`/`resume` 对 `awaiting_approval` 的语义；否则审批门禁在第一次改令后即失效/死锁。
2. **B4-02/B4-05**：建立作者 capability 交付与 legacy 迁移；在此之前不要把审批功能宣称为可用。
3. **B3-09/B3-10/B3-11**：单行预算会计 + dispatched + 崩溃清扫；否则指令护栏和日限额不可信。
4. **B3-07/B3-08**：>200 回放、`after_seq`、会话流、跨进程 wake；实时事件总线的核心承诺。
5. **B4-03**：把 probe 改为固定小 payload，free_pool 加同等级上限。
6. **B3-06/B3-15/B3-17/B3-18/B3-20**：事件生产者、Role E 消费者、身份、路由、高风险门禁；接入 executor 前必须完成。
7. **B4-04/B3-12 残余/B3-21..23/B3-26/B3-28/B3-29/B3-30**：按迭代处理。
