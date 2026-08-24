# 发布前检查清单

> 面向准备把 TraceLens 交给另一位分析师、放入共享内网、或构建 release candidate 的维护者。清单刻意把“代码能编译”和“产品可用”分开：两者都通过才算完成。

## 1. 工作区与版本

- [ ] `git status` 干净，分支和远端一致；
- [ ] commit message 使用仓库已有的 `docs:/fix:/feat:/test:` 前缀；
- [ ] README、docs/README、modules/README 没有指向不存在的文件；
- [ ] 新增 env/端点/表已经在对应 reference/schema 文档登记；
- [ ] 代码修复后，模块文档中“已知缺陷”标注已经删除或改为已修复。

## 2. 构建层

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_WEB_FRONTEND=OFF
cmake --build build --target forensic_analyzer -j"$(nproc)"
```

- [ ] `build/forensic_analyzer` 存在且 `ldd` 无缺库；
- [ ] CMake 选项与 setup.sh 依赖一致（TSK/Crow/OSS SDK/GTest）；
- [ ] `tracelens_agent` 若发布分布式版本单独构建并检查 OpenSSL/SQLite；
- [ ] Python venv 可 import fastapi/pydantic/graphiti_core/markitdown；
- [ ] `cd web && npm run build` 成功，`build/web/dist/index.html` 已同步。

## 3. C++ 回归

```bash
cd build && ctest --output-on-failure
ctest -R '(Scene|Thread|TOON|FullText|Markitdown)'
```

- [ ] CTest 目标数量符合当前依赖（SQLCipher 未装时目标会少）；
- [ ] 关键 fixture：多分区、MIUI、WeChat SQLCipher、DLL、memory；
- [ ] 独立 main（llm_files_test/mysql daemon）若未运行，在发布说明中写清；
- [ ] 不把 tests 目录里的脚本 PASS 当作 ctest PASS。

## 4. Python 回归

```bash
make test-python-fast
make test-python-investigation
make test-python-full
```

- [ ] startup reliability：30s 总预算/12s 可选服务/回滚；
- [ ] D2b：任务路径 fail-closed、绝对路径/符号链接拒绝；
- [ ] D4b：删除后写保护、TOCTOU、Graphiti driver close；
- [ ] 报告：生成 202→轮询→manifest→citation；
- [ ] 若跑 integration，明确 Neo4j/PG 是否真实可用；
- [ ] `graphiti_integration/tests` 单独跑（不在默认 testpaths）。

## 5. 前端回归

```bash
cd web && npm test -- --run
npm run build
npm run lint
```

- [ ] routes/smoke harness；
- [ ] TaskSelector 切任务时旧轮询响应不会覆盖新任务；
- [ ] 报告 renderer 未注册时 GenericTable 回退；
- [ ] 发现 /analysis-center、/investigation-graph、/oss 的已知问题时，在发布说明保留限制；
- [ ] mock login 明确标注为本地占位，不当作认证通过。

## 6. 三服务验收

```bash
make acceptance-smoke
make acceptance-task
make acceptance-analyst
make acceptance-restart
```

- [ ] C++/Python/假 LLM 端口均为动态隔离端口；
- [ ] 验收工作区不读仓库 `.env`、不写仓库 data；
- [ ] task journey 验证 task-owned raw/events/files 三库完整性；
- [ ] analyst journey 验证 evidence→analysis→review→event→graph→report；
- [ ] restart journey 验证进程杀死后作业状态不假复活；
- [ ] `--with-distributed` 只有在 PostgreSQL URL 存在时开启。

## 7. 外部依赖与凭据

- [ ] `.env` 中 `NEO4J_PASSWORD`、`JWT_SECRET_KEY`、`DATABASE_URL` 已替换示例值且文件权限 600；
- [ ] LLM `/v1/models` 同时有聊天与 nomic embedding 模型；
- [ ] `GRAPHITI_BATCH_SIZE` 显式钉死，避免 Settings/GraphitiConfig/example 三默认漂移；
- [ ] Redis 不可用时，发布说明写“摄取作业重启不持久”；
- [ ] C/S 002/003 迁移已手工执行并验邮箱/index；
- [ ] 仅可信网段暴露 8080/8090/8091/7687/5432。

## 8. 数据与文档

- [ ] 用小 fixture 完成一次产出检查：raw/events/files/platform；
- [ ] `PRAGMA integrity_check` 对每个输出库为 ok；
- [ ] 报告引用回溯到 evidence/analysis/claim ID；
- [ ] schema 文档与实际 `PRAGMA table_info` 一致；
- [ ] `docs/reference/ServiceContracts.md` 与前端代理/服务端点一致；
- [ ] 所有新功能有“谁调用/写哪张表/失败怎么表现”的解释，而非只有接口表。

## 9. 发布结果模板

```text
版本/commit：
构建平台：
C++ ctest：通过数/跳过数/外部依赖：
Python fast/investigation/full：
前端 test/build/lint：
验收 profile：
外部服务：Neo4j / Redis / PG / LLM（可用/降级）
已知限制：
凭据轮换：
```

---

**最后更新**: 2026-08-24（新建：发布前检查清单）
