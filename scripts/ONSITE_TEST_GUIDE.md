# 现场测试手册（甲方现场 · AI 不可用场景）

> 本手册配合 `scripts/onsite_smoke_test.sh` 使用。脚本负责自动验证，手册负责**人工判断、记录截图、应对突发情况**。

## 一、现场测试的边界（必须先想清楚）

现场 AI/LLM **完全不可用**（无算力、物理隔离、合规禁止）。因此：

- ✅ **能测**：全部非 AI 功能（抽取、分类、时间线、统计、搜索、导出、平台专项）
- ✅ **能测 AI**：仅"降级行为"——AI 不可用时系统是否**优雅失败**（不崩溃、不卡死、前端有提示）
- ❌ **不能测**：AI 实际产出质量（文件描述、案件报告内容）——这部分用**带回的 DB 在本地回放**补测

## 二、去现场前（本地必做 checklist）

- [ ] **运行过一次冒烟脚本**（本机 `test_image.img`）：`bash scripts/onsite_smoke_test.sh test_image.img`，确认全 PASS
- [ ] **已部署重构 bug 修复**：`_helpers.py` 已存在（否则案件智能分析全 500）
- [ ] **重新编译**：`cd build && cmake --build . -j$(nproc)`，确保二进制最新
- [ ] **Web 前端已构建**：`cd web && npm run build`（否则 `build/web/dist` 缺失）
- [ ] **带上依赖**：确认目标机器能运行 `./build/forensic_analyzer`（`ldd` 检查）
- [ ] **内存取证符号**：如要测 RAM dump，提前问甲方内核版本，准备对应 ISF 符号文件

## 三、现场操作流程

### 步骤 1：启动服务

```bash
# 在干净终端启动（关键！见下方"坑1"）
cd /path/to/ForensicsProject
unset LLM_BASE_URL LLM_TEXT_BASE_URL LLM_VISION_BASE_URL   # 清掉旧环境变量
./start.sh
```

等待看到 `ALL SERVICES STARTED SUCCESSFULLY`。

### 步骤 2：跑冒烟脚本

```bash
# 磁盘镜像（E01/DD）
bash scripts/onsite_smoke_test.sh /path/to/disk.E01 --scenarios windows,linux

# 纯功能验证（不指定平台专项）
bash scripts/onsite_smoke_test.sh /path/to/disk.dd

# 交互式（不知道怎么填参数时）
bash scripts/onsite_smoke_test.sh
```

如果现场需要**限制文本导出总量**（例如甲方要求导出量有上限），可以直接用 `forensic_analyzer` 跑受限导出，而不必走冒烟脚本：

```bash
# 限制 --dump-text 的现场导出总量（原文件 + Markdown，二进制单位）
./build/forensic_analyzer /path/to/disk.E01 \
  --db-dir ./onsite-output \
  --linux-analyze \
  --no-ai \
  --dump-text-max-size 500M
```

操作要点：

- `--dump-text-max-size` 会自动启用 `--dump-text`，不要求 `--no-ai`。
- 仅统计 `<base>_extracted_files/` 与 `<base>_extracted_text/` 中的普通文件；三个核心数据库和 `--report` 不受限制。
- `K/M/G/T` 按 1024 进位，只接受正整数，例如 `500M`、`2G`。
- 上限是文件级软限制：已开始的原文件及其 Markdown 会完整保留，所以最终大小可能超过设置值；达到后不会开始下一个文件。
- 重跑时已有产物会计入额度并尽量复用；提高额度后可继续导出。
- 达到上限只会警告，主分析仍成功，核心取证数据库仍有效。

脚本会自动：建任务 → 等完成 → 查 DB → 验证功能 → 测降级 → 列出带回清单。

### 步骤 3：人工验证（脚本覆盖不到的）

脚本跑完后，**打开浏览器** `http://localhost:8080` 逐页确认：

| 页面 | 人工要看什么 | 截图存证 |
|---|---|---|
| 仪表盘 | 任务数、文件统计显示正常 | ☐ |
| 任务列表 | 刚建的任务存在、状态正确 | ☐ |
| 时间线 | 事件分布图、聚类正常渲染 | ☐ |
| 文件管理 | 13 类文件分类有数据、能点开 | ☐ |
| 统计 | 图表渲染正常（无空白/报错） | ☐ |
| 搜索 | 建过索引后能搜到结果 | ☐ |
| **AI 描述** | **空列表或"模型不可用"提示，不白屏不转圈** | ☐ |
| **案件智能** | **能进入页面，触发分析时提示失败而非卡死** | ☐ |
| **知识图谱** | **显示"未连接/disabled"，不报错弹窗** | ☐ |
| Windows/Linux/Android 取证 | 有数据则正常显示（取决于镜像内容） | ☐ |

> **加粗**的页是 AI 降级重点——它们正是"AI 不可用"时最容易出问题的地方。

### 步骤 4：采集带回产物

脚本最后会列出要打包的 DB 路径并给出 `tar` 命令。**务必带回**：

- `*_raw.db` / `*_events.db` / `*_files.db`（基础三库）
- `windows.db` / `linux.db` / `android.db`（平台专项，如有）
- 任务的 `tasks.json`、案情描述

回到本地后，启动 LLM，用这些真实 DB 回放：
```bash
curl -X POST http://localhost:8090/api/llm/case-analysis \
  -H "Content-Type: application/json" \
  -d '{"task_id":"<现场任务id>","files_db_path":"<带回的files.db路径>"}'
```

## 四、已知坑与应对

### 坑 1：改了 .env 但配置没生效 ⚠️ 最常见

**现象**：`.env` 里写了 `LLM_TEXT_BASE_URL=http://...`，但 `/api/llm/status` 显示的还是旧值（如 `localhost:1234`）。

**根因**：`start.sh` 里有一行 `set -a; source .env; set +a`，把 `.env` 内容**导出成了进程环境变量**。而 pydantic-settings 的优先级是 **环境变量 > .env 文件**。如果你在**已经 source 过旧 .env 的终端**里改文件再重启，环境变量仍是旧值，覆盖文件。

**解决**：
```bash
# 方法 A：新开一个终端再 start
exec bash   # 或直接开新 terminal
./start.sh

# 方法 B：unset 旧变量再 start
unset LLM_BASE_URL LLM_TEXT_BASE_URL LLM_VISION_BASE_URL LLM_TEXT_MODEL
./start.sh

# 方法 C：直接用环境变量覆盖（最可靠）
LLM_TEXT_BASE_URL=http://新地址 ./start.sh
```

### 坑 2：任务卡在 running 0% 很久

**可能正常**：大镜像分析耗时。脚本里 progress 字段是**嵌套结构** `progress.overall_percentage`（不是扁平的 `percentage`）——脚本已正确处理，但若你自己写查询要注意。

**判断**：看 `build/logs/cpp_server.log`，若日志在持续输出文件名，说明在工作，耐心等。

### 坑 3：案件分析显示"已完成"但报告是空的

**这是正常的降级行为**，不是 bug。LLM 不可用时，report_generator 对每个章节 try/except，失败跳过，job 仍标 completed 但 `files_analyzed: 0`。现场看到这个现象 = AI 没跑（预期内）。

### 坑 4：RAM 内存取证失败

Volatility3 需要**匹配内核版本的 symbol 文件**（`~/.cache/volatility3/symbols/*.json`，vol3 2.x 用 cache 目录而非 config）。现场大概率没有 → 内存模块会报符号缺失。setup.sh 现在会从仓库内置的 `resources/volatility3-symbols/` 自动安装 6.8.0-110 的符号；其它内核用 `scripts/build-vol3-isf.sh <版本>` 生成。

## 五、降级行为预期表（脚本自动断言这些）

| 场景 | AI 可用时 | AI 不可用时（现场） |
|---|---|---|
| `/health/ready` | ready=true | **ready=true**（LLM 标 optional） |
| `/api/llm/status` | available=true | **available=false**（前端可判断） |
| `/api/llm/analyze` | 返回描述 | **HTTP 500, <1s 返回**（不卡死） |
| 案件分析 job | completed, 有报告 | **completed, 报告空**（降级） |
| 知识图谱 | connected | **disconnected**（不崩溃） |
| 全部非 AI 功能 | 正常 | **正常**（不受影响） |

## 六、如果脚本 FAIL 了

1. 看脚本输出的 FAIL 项详情
2. 查日志：`build/logs/cpp_server.log` 和 `build/logs/python_service.log`
3. 常见原因：
   - **镜像格式不支持**：确认 `file <镜像>` 类型，E01 需 libewf
   - **依赖缺失**：`ldd build/forensic_analyzer | grep "not found"`
   - **重构 bug 未修**：若案件分析报 `NameError`，检查 `_helpers.py` 是否部署
4. 把 FAIL 详情、日志、截图带回，回来再修
