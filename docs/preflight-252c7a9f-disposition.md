# 指定预检作业有限范围核查与待批准处置

作业：`252c7a9fcb07453fa3969a8f7d3ca340`。
核查时间：2026-09-28 09:38:16–09:43:40 Asia/Shanghai。
结论：`STALE_CONFIRMED_WITHIN_CHECKED_SCOPE`；未改变 job.json 或部分 manifest。

创建链是 `POST /api/evidence-intake/jobs` → `asyncio.to_thread(start_job)` →
Python 进程内 daemon thread / `_active`，没有 Preflight Redis/C/S 分发。
该作业为 directory/derived_html_report，不走镜像检查子进程。
存储状态 running；最后更新 2026-09-26 11:44:25；290 文件、69,068,342 字节。
无 owner PID、heartbeat、finished_at 或最终哈希。部分 manifest 存在但不代表完整校验。

两次只读 GET 均派生返回 interrupted，磁盘元信息未变化。8090 PID 1065136
启动于 2026-09-26 18:43:37，晚于作业创建；无已见子进程。两次限定 `/proc` FD
扫描共检查 2,254 / 2,185 个链接，精确来源/工作目录匹配均为 0，无权限拒绝。
核查实际 C++、Python、C/S 服务进程树、可读 system/root-user systemd/timer/cron/
supervisor/rc.local 配置、本地 Redis 精确 job key及已配置队列，未发现该作业执行入口。
Windows 已知 Python/forensic/队列进程、服务及计划任务的只读查询没有匹配执行者。

这不是无限期观察或仅以 mtime/PID 单点判断。范围不覆盖 Windows 句柄、其他 WSL
发行版、未知远端/容器、任意改名包装器、硬链接路径别名；原 creator PID 和退出原因未知。
需运维确认这些未核查范围是否存在实际配置的执行入口；如存在，补对应只读权限与核查。

待批准处置仅涉及此作业：

1. 在维护窗口关闭新预检创建入口；不改其他任务、镜像或队列数据。
2. 如另找具体执行单元，按 PID+启动身份/服务名精确阻止重启或重派发并停止它。
   目前未识别到需停止的相关单元，不用 pkill/fuser-k 或整机重启。
3. 保留原 job.json、日志/部分 manifest 的私有校验副本；确认实际文件写入者已停止，
   新进程不能接管同一旧输出目录。部分哈希仍为未验证。
4. 现有 `get_job` 仅派生 interrupted；`cancel_job` 需要 active 条目，不能取消这个遗留
   job；没有恢复续跑机制。本轮不伪造 API 取消成功，不手工改 completed。
5. 维护批准后可选择继续保留原状态并附独立审计记录，或另行批准精确 lifecycle
   reconciliation 到 interrupted（保留原件、说明依据/时间、不编造 finished_at）。
   不需要为了清空 running 计数而立即编辑磁盘元数据。
6. 若要重试必须另获检材处理授权并创建新 job，不复用此 ID/目录；本轮不重试。
7. 切换时重新核查实际已配置入口和新在途作业，保持真实检材准入关闭。未经批准不切换。
