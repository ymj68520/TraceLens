# 调查与报告契约参考

> 这份参考专门把“取证数据已经解析出来”之后的调查域契约串起来：证据键、快照、二次分析、评审、事件版本、报告证据、生成、发布。它不替代路由 API 参考，而是解释这些接口为什么必须按这个顺序调用。

## 1. 总体状态链

```text
C++ files/events
      │
      ▼
Snapshot（不可变文件快照）
      │
      ├── Secondary Analysis（202，等待评审）
      │          │
      │          └── accept/reject
      │
      ├── Investigation Event（事件）
      │          │
      │          └── Event Refresh → 新版本
      │
      └── Report Evidence（只绑定已采纳分析）
                     │
                     ▼
             Report Generation（202 + generation_id）
                     │
                     ▼
             Manifest → Citation Traceback → Publish
```

| 对象 | 进入状态 | 终态/版本 | 关键不变量 |
|---|---|---|---|
| Snapshot | capture_if_absent | immutable | 同任务同输入不覆盖 |
| Analysis | queued/running | review_pending/accepted/rejected | 先持久化后启动 |
| Event | captured | version chain | 证据键可解析 |
| Refresh | admitted/running | produced/failed | 新版本不覆盖旧版本 |
| Report evidence | bound | removed（显式） | accepted analysis 才能绑定 |
| Generation | queued/running | completed/failed | input_hash 冻结 |
| Publication | draft | published | 发布后哈希可校验 |

## 2. 证据键语法

### 2.1 文件证据

```text
file:<normalized-path>
```

- `normalized-path` 必须经过任务目录/镜像路径解析；
- resolver 不能接受任意绝对路径；
- 文件缺失时返回明确的 evidence not found，而不是把空内容当证据；
- 同一文件在不同任务中不是同一证据，task_id 是隐含作用域。

### 2.2 事件簇证据

```text
cluster:v1:<minute>:<encoded-type>
```

- `minute` 是事件时间戳按分钟桶化的值；
- `encoded-type` 是固定编码，不是 UI 显示文字；
- `v1` 是冻结版本，不能随意改成新的分隔符；
- C++ 事件簇的 SQL bucket 与 Python investigation key 是相关但不同的两个层次。

### 2.3 解析失败分类

| 失败 | 含义 | 处理 |
|---|---|---|
| 格式非法 | 客户端传错 key | 400，不启动分析 |
| 任务不存在 | 作用域错误 | 404 |
| 文件不存在 | 证据已删/路径错 | 404，记录 claim 无证据 |
| 快照不一致 | source 在 capture 中变化 | 重新 capture，不覆盖已有 |
| 版本冲突 | 同时提交评审 | 409，重读当前版本 |

## 3. Snapshot 的不可变语义

`capture_if_absent` 的核心不是“读一次文件”，而是建立之后所有分析共享的输入边界：

1. 从 C++ 任务库解析文件/事件；
2. 规范化 source identity；
3. 复制或登记证据内容；
4. 计算 SHA-256；
5. 使用唯一约束 `ON CONFLICT DO NOTHING` 写入；
6. 后续读取永远使用快照，而不是重新读可变的原始库。

### 3.1 为什么不能每次重新读 files.db

- LLM 重分析可能已经更新 `llm_*` 列；
- 任务删除或清理可能让原路径消失；
- 同一输入重复分析需要可复现；
- 报告引用必须能证明生成时看到的内容。

### 3.2 Snapshot 检查表

| 检查 | 失败说明 |
|---|---|
| task_id 与 source task 对齐 | 越权/错任务 |
| path 在任务目录边界内 | 路径注入 |
| SHA-256 与 stored hash 相等 | 输入变化/损坏 |
| snapshot version 唯一 | 并发 capture |
| source metadata 可追踪 | 不能回溯 |

## 4. Secondary Analysis

### 4.1 202 不等于成功

`POST /api/investigation/analyses` 返回 202 只表示作业已准入。客户端必须：

```text
POST analyses
  └─ 202 {analysis_id}
       └─ GET analyses/{analysis_id}
            ├─ running → 继续轮询
            ├─ review_pending → 读取 claims
            ├─ accepted → 可以绑定报告证据
            └─ failed/rejected → 不得绑定
```

### 4.2 评审前后的权限

| 状态 | 可读 claims | 可建事件 | 可绑报告证据 |
|---|---:|---:|---:|
| running | 否/部分 | 否 | 否 |
| review_pending | 是 | 需评审 | 否 |
| accepted | 是 | 是 | 是 |
| rejected | 可审计 | 否 | 否 |

分析器输出的 FACT/INFERENCE/HYPOTHESIS 不是最终事实等级：没有证据引用的 FACT 会按 grounding 规则降级，调查员必须在评审阶段确认。

## 5. Event 与版本

事件不是一次性的 JSON 文档，而是一个版本容器：

| 字段语义 | 作用 |
|---|---|
| event_id | 稳定事件身份 |
| version_id | 某一叙事版本 |
| claims | 该版本提出的断言 |
| evidence links | 支撑链 |
| review state | 当前版本是否采纳 |
| refresh_id | 产生该版本的作业 |

刷新操作的正确顺序：读取当前事件与证据 → 生成新叙事 → 校验引用 → 插入新版本 → 由评审决定是否采纳。不要 UPDATE 旧版本文本，否则引用回溯失去历史。

## 6. Report Evidence 绑定

报告证据不是任意 `evidence_key` 的列表，而是一个冻结的绑定：

```json
{
  "task_id": "task-...",
  "evidence_key": "file:/etc/cron.d/job",
  "analysis_id": "analysis-...",
  "claim_id": "claim-...",
  "added_by": "analyst@example.com"
}
```

绑定前应验证：

1. task_id 与 evidence 所属任务一致；
2. analysis_id 状态 accepted；
3. claim_id 存在且属于 analysis；
4. evidence_key 可由 snapshot resolver 解析；
5. added_by 不为空；
6. 重复绑定有确定性行为（幂等或明确冲突）。

## 7. 报告生成准入

### 7.1 input_hash

生成器从报告证据、分析、claim 和元数据组装 envelope，再算 SHA-256 `input_hash`。这一步实现两个目标：

- 同样的输入重试不会制造不同版本；
- 生成结果可以证明“报告基于哪一组输入”。

### 7.2 生成状态轮询

```text
POST /api/reports/generate
  └─ 202 generation_id
       └─ GET /api/reports/generations/{id}
            ├─ queued
            ├─ running
            ├─ completed → manifest/categories/pages
            └─ failed → error + 重试建议
```

scope=case 在当前代码中有明确 501 边界；客户端不要把 501 当作暂时网络错误无限重试。

## 8. Citation Traceback

引用回溯沿四层走：

```text
Report page
  → category/page record
    → report evidence binding
      → analysis/claim
        → snapshot/evidence key
          → raw/files/events/platform table
```

每一层都必须能提供稳定 ID。若页面只有自然语言而没有 claim/evidence ID，它就是叙述文本而不是可核验引用。

### 8.1 常见断链

| 断点 | 页面表现 | 排查 |
|---|---|---|
| page→record | 页面空 | manifest/category page |
| record→evidence | citation 缺失 | report_evidence 表 |
| evidence→analysis | 绑定被拒 | accepted 状态 |
| analysis→claim | traceback 404 | claim_id 归属 |
| claim→snapshot | source not found | task_store/hash |

## 9. 发布

发布是最后一个写入门：

1. 检查 manifest 完整；
2. 检查每个 citation 可追溯；
3. 生成最终 HTML/Markdown/print 展示；
4. 计算 integrity hash；
5. 事务写 publication 状态；
6. 后续读取只读展示。

发布后修改内容会让 hash 不匹配。需要改事实时，创建新版本，不在发布文件上原地修补。

## 10. 客户端实现清单

- [ ] 202 响应保存 exact generation_id/analysis_id；
- [ ] 轮询按 identity 丢弃旧响应；
- [ ] 409 显示契约提示，不当作 500；
- [ ] 410 显示旧链路退役，不自动重试；
- [ ] 501 显示 scope/功能边界；
- [ ] completed 后再读 manifest；
- [ ] citation traceback 失败时显示 source id 与 evidence key；
- [ ] 发布成功后刷新 integrity hash；
- [ ] 切换 task/case 时取消旧轮询。

---

**最后更新**: 2026-08-24（新建：调查与报告契约参考）
