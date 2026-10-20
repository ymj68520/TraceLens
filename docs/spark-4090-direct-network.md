# Spark 部署状态与 4090 直连指南

- 更新日期：2026-10-19
- 关联文档：[local-llm-deployment.md](local-llm-deployment.md)（总体模型部署方案）
- 本文记录 Spark（DGX Spark，主机名 `spark-13d3`）已完成的服务端配置，以及 4090 主机与 Spark 网线直连的步骤。

## 1. Spark 当前状态（2026-10-19 已配置完成）

| 项目 | 状态 |
|---|---|
| 系统 | DGX OS 7.5（Ubuntu 24.04.4，aarch64，20 核，121G 统一内存，盘 3.6T） |
| CUDA | 13.0（`/usr/local/cuda`） |
| llama.cpp | 已编译完成 ✓，CUDA sm_121a（GB10 自动识别），位于 `~/llama.cpp/build/bin/llama-server` |
| 模型 | `~/models/qwen3-embedding-06b/Qwen3-Embedding-0.6B-f16.gguf`（1.2GB，v3 定稿；8B 版 15.1GB 仍留在 `~/models/qwen3-embedding/` 备查） |
| systemd 服务 | `llama-embedding.service`（0.6B + `-np 4` 并发，别名 `qwen3-embedding-0.6b`）**已启动并设为开机自启**，实测 active，监听 `0.0.0.0:8001` ✓ |
| 防火墙 | ufw 处于**未启用**状态（无过滤），已预置放行 8001/tcp 规则 |
| SSH | 本机（开发 WSL `root@localhost`）公钥已装入 `lwc` 账户，可免密登录 |
| 编译/下载日志 | `~/build-logs/`（llama-cmake.log / llama-build.log / aria2.log） |

服务运维命令（Spark 上执行）：

```bash
sudo systemctl status llama-embedding      # 状态
sudo systemctl restart llama-embedding     # 重启
journalctl -u llama-embedding -f           # 实时日志
```

Embedding 接口自测（Spark 本机）：

```bash
curl -s http://127.0.0.1:8001/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-embedding-0.6b","input":"测试"}' | head -c 200
```

## 2. 当前网络拓扑（配置期）

```
Spark(wlP9s9 WiFi) ──── Windows 热点网卡 192.168.43.4/24
      192.168.43.5            │
                           开发 WSL / Windows 终端
```

- 现阶段 Spark 通过 **WiFi（接口 `wlP9s9`）** 挂在 Windows 热点网段：`ssh lwc@192.168.43.5`
- 板载网口是 **`enP7s7`**（当前 DOWN），另有 USB 网卡 `enx68da73a0f9fc`（未用，勿混淆）

## 3. 网线直连方案（4090 主机 ↔ Spark）

目标拓扑：一根网线直连两台设备，独立于办公室/家庭网络，低延迟且断外网不影响：

```
4090 主机(10.55.0.2) ════ 网线 ════ Spark enP7s7(10.55.0.1)
        │
     TraceLens(WSL2)
```

### 3.1 Spark 侧：给 enP7s7 配静态 IP（一次性）

在 Spark 上执行（DGX OS 用 netplan；新文件编号大于现有文件即可，不动 WiFi 配置）：

```bash
sudo tee /etc/netplan/70-enP7s7-direct.yaml > /dev/null <<'EOF'
network:
  version: 2
  ethernets:
    enP7s7:
      dhcp4: false
      optional: true
      addresses: [10.55.0.1/24]
EOF
sudo chmod 600 /etc/netplan/70-enP7s7-direct.yaml
sudo netplan try          # 120s 内回车确认；网口没插线也不会断现有 WiFi
```

### 3.2 4090 主机侧：Windows 网卡配静态 IP

网线插好后，在 4090 主机的 Windows 上（管理员 PowerShell，网卡名以 `Get-NetAdapter` 实际输出为准）：

```powershell
Get-NetAdapter                                    # 找到插了线的以太网口，记录 Name
netsh interface ip set address name="以太网" static 10.55.0.2 255.255.255.0
```

> TraceLens 跑在 4090 主机的 WSL2 里：WSL2 出站流量经 Windows 路由，Windows 网卡在 10.55.0.x 网段后，WSL2 内可直接访问 `10.55.0.1`，无需额外配置。

### 3.3 验证（4090 主机 WSL2 内执行）

```bash
ping -c 3 10.55.0.1
curl -s http://10.55.0.1:8001/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-embedding-0.6b","input":"连通性测试"}' | head -c 120
```

返回 JSON 且含 embedding 数组 → 直连打通。

## 4. TraceLens `.env` 目标值（embedding 段）

```ini
EMBEDDING_BASE_URL=http://10.55.0.1:8001/v1     # 直连打通后用这个
EMBEDDING_MODEL=qwen3-embedding-0.6b
EMBEDDING_DIM=1024                              # v3 定稿
```

**EMBEDDING_DIM 实测结论（2026-10-19 v3 已定稿：0.6B / 1024 维）**：llama.cpp **忽略 `dimensions` 参数**（8B 上要 2048 给 4096；0.6B 上要 768 给 1024），维度只能取模型原生值。生产服务已切 **Qwen3-Embedding-0.6B**（F16，`-np 4` 并发），`.env` 必须写 **`EMBEDDING_DIM=1024`**——**首次图谱入库后不可再改**（改维度需重建图谱数据）。

实测数据（2026-10-19 Spark）：0.6B 单发 10–66ms（8B 为 76–494ms）、批量 8 条 70ms、4 路并发聚合 ~67 条/秒即饱和（8/16 路无增益）；实体区分度对拍 0.6B 0.158 vs 8B 0.122，质量代价可接受。切换前的 8B 模型仍留在 `~/models/qwen3-embedding/`，需要切回时改 systemd 模型路径 + `EMBEDDING_DIM=4096`（需重建图谱）。

## 5. 注意事项

1. **WiFi 与直连相互独立**：拔掉 WiFi、只插网线时，Spark 服务照常运行，仅管理通道变为 `ssh lwc@10.55.0.1`。
2. **两个网口别混淆**：板载口是 `enP7s7`；`enx68da73a0f9fc` 是 USB 网卡（未配置）。
3. **SSH 密码**：Spark 的 `lwc` 账户当前密码较弱，建议部署收尾后修改（`passwd`）；4090 主机如需免密管理 Spark，把它的公钥追加到 Spark 的 `~/.ssh/authorized_keys`。
4. **防火墙**：Spark 的 ufw 未启用（无过滤），8001 端口天然可达；若日后启用 ufw，记得放行 22 和 8001。
5. **服务开机自启**：`llama-embedding.service` 是 systemd 常驻服务，Spark 重启后自动拉起，无需手动干预。
