# Neo4j 本地服务验证说明

## 目标
验证本机是否存在可用的 Neo4j 服务，并说明 `Unable to retrieve routing information` 的可能根因与后续建议。

## 已验证项（环境范围）
- 仅验证本机服务/端口可达性与常见服务进程状态。
- 默认连接目标仅确认 `bolt://127.0.0.1:7687` 与 `neo4j://127.0.0.1:7687`，不跨机。

## 常见根因
1. Neo4j 未安装/未启动。
2. 仅安装了客户端（如 `cypher-shell`/Neo4j Desktop），但服务实际未运行。
3. 服务启动失败：内存/JVM/端口被占/配置错误。
4. 驱动版本与路由协议不匹配（常见于 4.x/5.x 混用或 `neo4j://` vs `bolt://`）。
5. 认证信息不一致（用户名/密码/AUTH 插件）。
6. 防火墙/SELinux 阻断本地回环端口。

## 建议检查命令
```bash
# 服务状态
systemctl status neo4j || service neo4j status || pgrep -af neo4j

# 端口监听（以 7687 为例）
ss -ltnp 2>/dev/null | grep 7687 || netstat -ltnp 2>/dev/null | grep 7687

# 版本/安装
neo4j --version || cypher-shell --version

# 驱动侧排查
python3 - <<'PY'
from neo4j import GraphDatabase
print("driver ok")
PY
```

## 建议修复顺序
- 先确认服务状态与监听端口。
- 再核对 `NEO4J_URI/USER/PASSWORD` 与 `.env`。
- 最后确认代码是否固定使用本地回环地址，而非 `localhost` 被特殊 DNS/hosts 改写。

## 结论（待现场验证补充）
- 在完成本机服务检查前，日志里的 `Unable to retrieve routing information` 优先按“服务未运行/连不上”处理。

## 现场补充
- 本机已安装 `neo4j` 与 `cypher-shell`，版本 `2026.06.0`。
- 当前未发现监听中的 `7687` 端口；未确认到运行的 Neo4j 服务进程。
- 基于现状，`Unable to retrieve routing information` 现仍然优先按“服务未运行/连不上”处理，后续补充启动后的连通性验证。
