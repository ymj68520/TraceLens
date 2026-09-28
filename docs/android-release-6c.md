# TraceLens 第六阶段 6C：受控发布准备与现场预演

## 后续只读依赖修复候选

03fcb281 的实际服务部署揭示：AI disabled/read-only 启动不创建二次分析执行器，
但 workbench 读侧仍依赖该执行器，历史 v7 overview 返回500。
新候选把摘要/详情/版本列表/单条分析 GET 改为 `InvestigationReadService` 的只读投影，
底层继续使用严格 `InvestigationGraphReader`。写侧仍保留原执行器、鉴权及状态边界。
不会开启AI、重放作业、恢复旧报告生成，或普通请求迁移v7。
新增真实 ServiceManager 初始化回归，不再用一个总是存在 executor 的 mock manager
掩盖 disabled + v7 组合；最终必须在实际新进程上再次验证。
旧候选、实际失败记录、351份状态备份和维护配置保留；原工作区未整理或重置。

## 2026-09-28：固定候选收口（非生产切换）

本轮候选位于受限持久目录 `/root/tracelens-releases/6c-freeze-20260928-bgDIFC`，
源码 worktree 为 `source/`，独立分支为 `release/6c-candidate-20260928-bgDIFC`。
原分支、原工作区和原暂存区不参与候选提交；不 push、不重启、不改网络、不迁移真实库。

具体发布范围见 [release-source-scope-6c.json](release-source-scope-6c.json)：
342 项已确认阶段源码/调用方/测试/文档改动纳入；18 项历史临时浏览器脚本、
未编译的 `OSSRoutes_new`、旧启动器/C/S 配置修复及历史测试笔记留在原目录。
数据、数据库、检材、日志、旧构建/venv/cache 一律排除。Graphiti 来源追踪、
翻译读取层、跨镜像报告读取和 toast 基础层是当前调用方的已有依赖，选择整体纳入，
不为缩小文件数而静默删功能。本轮没有新增格式、App、模型或认证框架；D 类无待决定项。

必要候选修复：

- CMake 由固定输入生成编译身份头，`--version` 与受保护接口返回编译时的 commit、
  源码 SHA-256 和 release ID；Python 导入包内生成身份，前端 manifest 对应同一 commit。
  原失败根因是 dirty 源码继续变化而构建缓存仍保留配置时的旧身份，并非同一份输入。
- 空 build 首次配置还暴露固定系统 Asio 头缺 `<utility>` 的兼容前提；旧缓存曾提供该
  编译选项。候选 CMake 显式声明，不升级依赖，不在系统头上打补丁，失败构建日志保留。
- `prepare_field_drill.py --freeze --wheelhouse ...` 是明确区别于旧演练 symlink 的冻结模式：
  新建 venv，从带哈希 wheelhouse 完全离线安装并 `pip check`，不得回退旧环境或公网。
- 现有 AOSP 工具曾把原开发目录的 `liblp.so` 绝对路径写入 DT_NEEDED；同一已验收源版本
  在候选重新构建，SONAME 为 `liblp.so`，运行时经 `$ORIGIN` 使用包内库，算法与格式未扩展。
- LP 发布包不携带 upstream Git 元数据；以固定 SHA-256 源码清单、逐文件校验和固定工具
  二进制哈希验证同一已验收输入。源码/二进制任一变化仍拒绝，不能任意换 manifest 放行。
  原阶段记录的 upstream commit 标识保留，不把父 worktree 的 HEAD 冒充 upstream 版本。
- 冻结目录包含正常启动需要的公开 `extractor_mapping.json` 和 `artifact_whitelist.json`，
  不因打包遗漏而静默变成零 extractor 路由。失败尝试和修复后验收记录分别保留。
- 空历史 v7 overview 明确标只读，页面不再自动 POST bootstrap；写操作仍要求受控 v8 迁移。
  不修改历史数据库，不拿浏览行为触发迁移。
- 纯 `--version` / `--help` 查询在配置与审计初始化之前退出，不创建审计库或读取生产配置。
  CLI 回归另行显式指定包外的合成 DATA_DIR；合成运行产物不得进入发布包。

离线 Python 目标仅为 Ubuntu 22.04 x86_64 / CPython 3.10.12 / glibc 2.35。
固定 148 个 wheel，包括原环境的运行/测试依赖和明确的构建工具；`pip` 使用 Ubuntu 的
22.0.2 启动包而非开发环境 26.2.1，其余已测运行包版本不变。
锁定文件和各安装包 SHA-256/依赖/许可证元信息见
`deploy/field/python-linux-cp310-x86_64.{lock,material.json}`。
wheelhouse 是离线安装材料，不是 `pip freeze` 截图；不宣称跨平台兼容。
C/S 不属于本机 disabled 发布模式，不启动 8091；不对 C/S 发布能力作新验收声明。

固定输入与回归执行入口：

1. 在候选提交完成且工作区干净后运行 `scripts/field_build_identity.py --output ...`。
2. 全新 `build/` 以 manifest 中的 release ID/commit/SHA 配置 CMake；禁止原目录产物。
3. Node 22 + 新 `npm ci --offline`，在私人 netns 执行 `field_frontend_build.py`。
4. 私人 netns 中 `prepare_field_drill.py --freeze` 新建 runtime；版本不匹配立即失败。
5. 使用该 runtime 二进制、新 venv 和候选前端重跑已有归档/文件系统/规范化、安全、
   6B mock HTTP、v7/v8、HTML/离线包和受限浏览器测试；机器证据存放此持久候选的
   `verification/`，失败尝试保留，不以旧 dirty 工作区测试替代。

`android_release_manifest.py` 兼容保留 `publishable=false` 的部署授权语义。
新增 `package_engineering_ready` 单独记录工程就绪；它不授权停服、切换或敏感检材准入。
生产是否静止、批准、切换和实际 unit 出站验证均是独立门槛。
真实模型和项目方真实样本仍分别为 `LOCAL_MODEL_VALIDATION_REQUIRED`、`REAL_SAMPLE_REQUIRED`。

指定预检作业的有限范围核查与待批准处置见
[preflight-252c7a9f-disposition.md](preflight-252c7a9f-disposition.md)。
本轮不修改其 `job.json`；`STALE_CONFIRMED_WITHIN_CHECKED_SCOPE` 不等于全局已知所有执行者。
正式切换仍须确认范围、保留部分输出、批准精确操作并核对当时所有新增作业。

以下 2026-09-27 记录保留为历史，不替代本轮固定候选验收。

记录日期：2026-09-27（北京时间）。分支 `feature/android-forensics-report-structure`，执行前 HEAD `c7f1fc3c0281527fb635773515521ed23960aecc`、工作区 322 处未提交状态。旧版真实服务没有停机、重启、网络变更、真实 Task 写入或数据库迁移。本文件只记录**准备与隔离演练**；不构成生产切换许可。

## 当前结论

| 验收域 | 实际状态 | 不能声称的内容 |
| --- | --- | --- |
| 6B 功能 | 合成 Task + 测试模型的单条短信→R2 引用已验收；四类工件复用测试通过。 | 不代表真实镜像、微信/QQ、原始数据库逐行定位或真实模型。 |
| 隔离测试 | `ISOLATED_TEST` 的 Chrome、模拟 HTTP 服务及子进程运行在仅 loopback 的独立网络命名空间；首个页面请求前安装 CDP `Fetch` 白名单与 Service Worker 绕过。受控禁止目标被阻止且收包 0，意外请求数 0。Python/Node 目标白名单也通过随机合成服务测试。 | 浏览器显示 PASS 不能取代后端认证或生产运行检查。 |
| 发布版本 | 另置目录的 field 前端候选构建通过，记录源码/资源哈希；Git 工作区未提交且 Python venv 尚未离线重建为不可变依赖。 | **RELEASE_NOT_FROZEN**，当前候选不是可发布生产版本。 |
| 生产服务 | 8666、8090、8091 仍由旧进程监听 `0.0.0.0`；无本轮批准的进程切换。 | 生产继续 `BLOCKED`，新安全代码未被确认加载。 |
| 本机配置 A | loopback、禁 AI、同源网关与两服务认证/出站模板已准备；隔离浏览器及已有 6A 后端测试有合成证据。 | 未安装正式本机网关或版本化单元；不能标为已部署通过。 |
| LAN 配置 B | HTTPS 反代与后端 loopback 模板已准备。 | 缺批准地址、真实证书/信任链、第二客户端和 Windows/WSL 转发验收，`LAN_DEPLOYMENT_PENDING`。 |
| 模型与真实样本 | 无获准本地模型进程/权重/许可的可核验清单；无项目方授权原始镜像。 | `LOCAL_MODEL_VALIDATION_REQUIRED`、`REAL_SAMPLE_REQUIRED` 不变。 |

隔离回归口径：本轮相关 Python/Investigation/报告/field 单元与集成合计 554 项通过，前端相关组件 26 项通过；最后的 6C 针对性复验为 14 项常规隔离检查通过、1 项要求独立网络命名空间的备份恢复通过、报告前端 16 项通过。未在网络命名空间内运行备份测试会按设计拒绝，不能将该安全门槛视为业务回归失败。合成备份恢复、两份报告同有 `c001` 的跨范围拒绝、TLS 材料校验和 field 构建无头路径均有独立断言。这些计数不是生产发布许可。

## 6B 误连事件：不覆盖旧失败记录

6B 首次旧前端构建沿默认 Python 地址，可能向既有 8090 发送合成 Task ID 的查询（包括以 POST 实现的搜索）；后续才改为同源 mock。独立保留的[误连风险记录](incidents/2026-09-27-browser-isolation-gap.md)明确原始逐请求日志缺失。对北京时间 9 月 27 日约 16:00–19:00 的已有日志做只读检查：`build/logs/python_service.log` 最后更新于 9 月 26 日，`cpp_server.log` 更早，journald 对相关 Python PID 在可疑窗口没有记录。现有日志不能确认实际目标、方法、状态码、请求 ID、认证头或业务副作用。历史 `tasks.json` 与 `reports.db` mtime 未变化，只是范围有限的佐证，不是全量无影响证明。结论 **`IMPACT_UNCONFIRMED`**。机器记录：`/tmp/tracelens-6c-incident-audit.json`；禁止用后来隔离 PASS 覆盖它。

## 实时作业与切换门槛

最终只读清单 `/tmp/tracelens-6c-job-audit-final.json` 在本轮记录：43 个 C++ Task 为 COMPLETED 24、FAILED 17、CANCELLED 2；派生调查库中查到 3 个 v7，当前无已记录的二次分析或事件刷新在途。R2 generation 为 completed 12/failed 6；Graphiti Redis 队列 0，历史 completed 32/failed 22；C/S command_queue、analysis_tasks 和 clients 均为空。第三方报告有 6 个 `PARTIAL` manifest，另有 1 个仅有 `records.db`、缺完成 manifest 的目录；没有持久请求级活跃标记。规范化与离线导出也没有统一活跃作业登记，不能仅靠 Task 计数推定全局静止。

预检 `252c7a9fcb07453fa3969a8f7d3ca340` 的 `job.json` 仍为 `running`，上次进度 290 文件、69,068,342 字节，最后持久更新在 9 月 26 日 11:44:25；无 owner PID、heartbeat、finished_at 或完整 manifest。当前 8090 进程于其后启动，API 将无 `_active` 映射的记录**派生展示**为 `interrupted`，并未持久修改旧文件。当前 PID 文件描述符未发现打开该来源/作业目录，但无法独立排除外部执行者。因此该作业保持 **`UNKNOWN`/切换阻塞**，不删除、不取消、不改终态。切换前需由运维确认旧实例/可能子进程归属、来源文件是否仍被读取，并给出精确处理批准。

新版本启动行为核对：现有 `evidence_preflight.get_job` 只在读取时派生 `interrupted`，不自动重放或写回旧状态；Investigation v7 的普通写入明确要求受控 v8 副本迁移，GET 可读。本轮没有运行真实库迁移。

本轮末再次只读检查（2026-09-27 22:40 北京时间）：Task 仍为 COMPLETED 24/FAILED 17/CANCELLED 2；同一预检 job 仍持久标记 `running`，无 owner PID/heartbeat、无完成 manifest，外部执行者仍未排除，`cutover_quiescence_confirmed=false`。没有据此清理或转换该 job。

## 隔离发布候选与部署形态

正式 field 前端将 Python API 固定为同源 `/python`，C/S 指向禁用路径，未配置时不再回退到旧 `8090/8091`。`scripts/field_frontend_build.py` 只向新目录构建，附源码与文件哈希，不包含 source map 或已知测试标记；它不会清空生产 `web/dist`。`scripts/browser_e2e.py` 只接受 `--mode ISOLATED_TEST`，要求独立网络命名空间、有效前端构建 manifest 和随机模拟实例身份；未经允许的连接在发出前拒绝。正式 field 的报告证据链接改为同标签页 SPA 导航，以保持仅内存中的 JWT，避免新标签页/整页刷新失去登录态。

候选前端在独立目录构建，最新 field 候选为 `/tmp/tracelens-6c-releases-UxFiGA/candidate5/web`（后续源变动将使其失效，测试器拒绝旧哈希），manifest `worktree_dirty=true`、`publishable=false`。该候选的隔离浏览器记录 `/tmp/tracelens-6c-browser-field-candidate5.json` 为 PASS，页面请求在发出前经过白名单、合成禁止端口收包 0、意外目标 0；合成登录、单条捕获与 `c001` 回跳在原会话完成。Node/Python 目标守卫测试为 `PASS_ISOLATED_TARGET_POLICY`。孤立模式下 Vite 开发代理缺显式随机目标和实例身份会在启动前失败；后续 field 构建仍须独立新目录并重验。C++ 独立构建目录 `/tmp/tracelens-6c-releases-UxFiGA/cpp-build`，与运行中的二进制分离；编译只构建 `forensic_analyzer`，显式关闭 CMake 的 web/npm 与 Python/pip 目标，且编译进程处于私人网络命名空间。独立验收器在合成运行中不仅检查受保护接口的双服务 release ID 与 C++ 进程实际二进制 SHA，还验证进程工作目录与前端 `index.html` 的候选哈希；候选 `publishable=false` 仍使总结果保持 BLOCKED。

`/tmp/tracelens-6c-releases-UxFiGA/candidate-drill4` 是最新**仅供演练**的运行目录，带独立 C++ 程序、当前 Python 服务源码、candidate5 field 前端及固定 qnxprobe/AOSP 文件；Python venv 链到现有**可变**环境，且该 C++ 程序的编译版本标识早于当前工作区，所以不发布。该目录的隔离合成全栈预演已通过：受保护的两服务实际加载相同演练 release ID；旧/新匿名业务请求 401、越权复核/导出 403、双向服务调用 200、身份服务失效时 C++ 503；disabled 下 SMS 2、Contacts 1、Apps 1、Wi-Fi 1 且结果包验真；合成旧报告库可 GET、在启动读侧无变化，报告生成入口在禁 AI profile 返回 503。预演只在私有 netns 中限制了出站，**不是**正式 unit 的 `IPAddressDeny` 实测，因此现场检查器如实保持 BLOCKED。独立目录的现有 EXT4/F2FS、RAW/E01 合成 CLI 回归也通过，每种来源均得到 2/1/1/1 与 6 条文件 provenance；locked 合成夹具只证明拒绝/覆盖状态。

`scripts/android_release_manifest.py` 生成源码、Git、二进制、前端、Python 依赖版本、qnxprobe/AOSP、许可证及配置模板哈希；脏工作区或缺独立二进制/版本化 Python 运行时时始终标 `publishable=false`。本轮最新候选清单 `/tmp/tracelens-6c-releases-UxFiGA/manifest-candidate-latest.json` 的源码 SHA-256 为 `3d9c4b5271eae4a77e6cf517a615e2ff66b0ebf20faf70e2bf0ff81a0e3884d9`，独立 C++ SHA-256 为 `05c9b4f8405633d844849c649e79479c9ce8d2ca080371e7511540d686b388ba`；清单明确列出 `DIRTY_WORKTREE_OWNERSHIP_UNRESOLVED`、`CPP_RELEASE_ID_MISMATCH`、`PYTHON_RUNTIME_NOT_VERSIONED_OR_OFFLINE_REBUILT`，不是发布物。执行前 322 处既有变更的归属尚未获准整体提交，后续新增的 6C 修改也仍未提交；旧 Python venv 还不是隔离、不可变的发布依赖。不能用仓库 HEAD 冒充运行实例。新受保护的 C++ `/api/security/status` 与 Python `/api/field-auth/status` 各返回**加载进进程**的 release ID；正式 profile 要求两者与 release manifest 一致，否则拒绝启动/验收。`android_field_check.py --release-manifest` 还能在认证后核对运行中 C++ 可执行文件 SHA-256；独立候选的身份匹配已演练，但候选 `publishable=false` 时检查器仍报 BLOCKED。当前生产 C++ 该 status 路由返回 HTML 200、Python 返回 404，匿名旧 Task/报告列表均为 200，不能据此宣称新版已加载。

首次正式 field profile 默认 `disabled` 且 `TRACELENS_REQUIRE_RELEASE_LAYOUT=1` 时：Python 启动使用只读 `ReportRepository` 读取已有报告，不运行旧报告/R2/分析的自动恢复或写入迁移；无模型报告生成入口返回 503。合成旧报告库在启动前后 SHA-256 不变，GET 可读。历史 v7 的快照 GET 继续可读，file/Android 快照捕获及报告证据写入会在**任何直写快照之前**返回 `409 MIGRATION_REQUIRED`，前端显示明确迁移提示；不创建空成功或“记录不存在”假象。隔离 v7 HTTP 测试已对比拒绝前后的源库 SHA-256 相同。升级工具仍只准备副本，不替换真实库。未来批准 `local_only` 模型前还须独立审计启动恢复对旧库的影响，不得仅改变 AI 开关。

两套未安装模板：本机禁 AI 见 [`field-release-local.env.example`](../deploy/field/field-release-local.env.example) 与仅 loopback 的 [`nginx-field-local.conf.example`](../deploy/field/nginx-field-local.conf.example)；LAN 见 [`field-release-lan.env.example`](../deploy/field/field-release-lan.env.example) 和已有 [`nginx-field.conf.example`](../deploy/field/nginx-field.conf.example)。版本化 systemd unit 分离于旧 `build/`/`web/dist`，保留 6A JWT、双向服务凭据、最小权限和 `IPAddressDeny=any`。本机没有 nginx 或 `/etc/tracelens/tls` 的正式材料，因此这两套模板尚未被实际部署。`scripts/check_field_tls.py` 仅能离线核验证书/私钥匹配、主机名、有效期与选定 CA；其合成证书测试通过，**不能**替代实际证书/客户端信任验收。

Windows/WSL 只读检查：Windows portproxy 仍对 `192.168.31.49` 与 `222.197.171.237` 的 8666/8090/8091 建立到当前 WSL `172.19.193.67` 的转发；`TraceLens WSL LAN` 入站规则启用，至少对 `192.168.31.49` 的这三个 TCP 端口放行到 `192.168.31.0/24`。未从第二设备测试可达性，也未修改拓扑。不能仅看 Linux 将来绑定 loopback 就断言 LAN 无旁路。

## 备份、切换与回滚预演

合成 `test_6c_backup_restore.py` 在私人网络命名空间中等待写入结束后，使用 SQLite Backup API 备份 Android 当前结果、v8 调查库、历史 v7 调查库、R2 数据库和第三方 `records.db`；连同冻结结果集、报告 manifest、coverage/离线包一起恢复到**另一隔离目录**。恢复后旧 v7 GET 不触发迁移，v8 引用仍绑定同一 result_set、R2 `citation` 可回跳、外部 HTML 仍是 `PARTIAL`；离线包验哈希通过，源库备份前后 SHA-256 相同。这只证明受控合成暂停窗口，不证明在线多个数据库的任意时点拷贝具有跨库原子性。真实维护窗口须先停相关写入，再统一登记数据和 manifest 的校验清单；不得直接复制活跃主 `.db` 而遗漏 WAL。

建议切换顺序（**此处不是授权执行命令**）：

1. 核定 release commit、所有既有 dirty 改动归属、独立二进制/前端/Python 依赖/工具哈希及许可证；准备唯一版本目录，禁止混用旧文件。
2. 获取精确停服、网络与数据操作批准；重跑作业清单。预检 UNKNOWN 或其他在途作业未解决时停止切换，不根据 C++ Task=0 推进。
3. 先关闭新真实检材准入；在已批准的维护窗口让旧版停止接新作业、等待/精确处理在途工作，完成一致性应用状态备份与恢复演练。原始镜像不默认重复复制。
4. 经批准后逐个切换指定服务及受控入口。本机方案先走 loopback/disabled；LAN 需证书、反代、端口转发和防火墙逐项批准并由第二客户端验证。8091 不需时也只能在批准后精确停用。
5. 发布后仍关闭真实检材准入，用批准的合成范围验证**当前进程** release ID、匿名旧/新 API 401、合法访问/内部凭据、角色 403、SSE/下载/来源回跳、实际 unit 出站、旧 v7 只读和新 v8 合成链。无批准不创建生产 Task。
6. 失败时保持认证、出站及入口限制，不恢复旧匿名 `0.0.0.0` 暴露；停用新版本但保留其数据。若新版产生 v8 复核/报告，不可让旧程序写 v8，也不可用旧备份直接覆盖新记录；维持只读并制定逐库受控恢复。

需要批准的具体生产动作：精确停止/重启 8666 与 8090 服务；决定 8091 的保留/停用；改变监听和 Windows portproxy/防火墙；安装并信任 LAN 证书、启用反代；替换任何真实 `investigation.db`；注册/删除任何生产合成 Task。**本轮均未执行。**

## 模型与项目方样本

`/tmp/tracelens-6c-model-audit.json` 明确为 `LOCAL_MODEL_VALIDATION_REQUIRED`：未识别获准模型进程、数值 loopback origin、权重哈希/来源、许可文本和模型服务自身的出站策略，也未审计本地代理/fallback。6B 的测试替身不升格；不调用公网模型、不下载模型或用真实检材试探。未来须在模型进程出站边界、许可和本地实现获准后，用**合成**短信走真实模型→人工复核→R2。另有独立合成回归 `test_6c_citation_scope.py` 已证明两份报告同用 `c001` 时必须按完整 Task/Report/Citation 上下文读取，跨 Task/Report 返回不命中；真实模型验收仍未进行。

现场样本模板 [`android-field-sample-manifest.example.json`](android-field-sample-manifest.example.json) 列出分段/附件、工具版本、容器/FS、加密/可读、SMS/Contacts/Apps/Wi-Fi 字段预期、账号/时间/删除/附件/过滤对照范围及授权记录；检查入口是 [`android_field_sample_manifest.py`](../scripts/android_field_sample_manifest.py)。微信、QQ 和其他 App 必须单独登记样本驱动验收，不能从四类合成工件外推。无获准真实镜像，`REAL_SAMPLE_REQUIRED`；LOCKED 正确处理也不等于消息取证目标已完成。

## 剩余阻塞与解除条件

- `RELEASE_NOT_FROZEN`：核对 322 处工作区改动归属、形成完整提交与可重复构建，版本化/离线重建 Python 依赖并完成独立 C++ 构建和源码/二进制哈希一致性检查。
- `IMPACT_UNCONFIRMED`：若能取得可疑窗口的可信访问日志/请求 ID 或独立审计数据，再逐请求判断；目前不能宣称无业务影响。
- `JOB_OWNERSHIP_UNKNOWN`：精确核查预检旧执行器和缺 manifest 的导入目录；未排除外部执行者前不进入停服窗口。
- `PRODUCTION_BLOCKED`：未批准切换，旧服务仍全网监听且 Windows 转发存在；没有新版实际进程身份与出站验收。
- `LOCAL_PROFILE_PENDING`：实际 loopback 网关、版本化 unit 与禁出站策略需在批准后的实例上验证。
- `CONTAINER_BRIDGE_RELEASE_TEST_PENDING`：独立目录已实测 EXT4/F2FS 与 RAW/E01 的旧路径；sparse/super 的 C++ 规范化桥在正式 release layout 下尚未单独重跑，现场若要准入该类来源须先补相应合成回归。
- `LAN_DEPLOYMENT_PENDING`：批准网络范围、真实 TLS 证书及信任链、宿主机转发与外部客户端验证均缺失。
- `LOCAL_MODEL_VALIDATION_REQUIRED`、`REAL_SAMPLE_REQUIRED`：按上节独立核验，不能用 mock 或 HTML 报告替代。

**总状态：本轮可授权的准备/隔离演练已完成；发布候选不可发布，生产仍 `BLOCKED`。**
