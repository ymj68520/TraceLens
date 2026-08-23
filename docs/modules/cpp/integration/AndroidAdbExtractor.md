# AndroidAdbExtractor（src/integration/AndroidAdbExtractor/）

> **一句话**：一个自研的 ADB 协议客户端（直连本机 adb 服务器 5037 端口，不依赖 adb 命令行），设计目标是直接从 Android 真机做逻辑提取（文件树拉取）和物理提取（root + dd 分区镜像）——**但它是死代码：未编入构建，且实现文件与头文件已失配到无法编译**。

> **现状声明（先读这个）**：本目录代码**不在 `CMakeLists.txt` 的 `LIB_SOURCES` 里**——`CMakeLists.txt:210` 只把该目录加成了头文件搜索路径，没有任何 `.cpp` 参与编译；全仓库也没有任何代码引用 `ADBClient`/`AndroidDirectoryExtractor`。更进一步，`g++ -fsyntax-only ADBClient_Init.cpp` 直接报错：实现文件使用的成员 `socket_fd_`、`current_device_` 在 `adbClient.h`（声明的是 `sock`、`current_serial`）里根本不存在——头文件与拆分的实现文件来自不同代际，即使想把它加回构建也必须先修。目录里的 `adbTest.cpp`、`test_console_encoding.cpp`、`test_encoding_fix.bat` 同样不在构建里，是 Windows 时代的独立试验程序。本文其余部分讲的是这套代码**本来的设计**，供未来复活或重写时参考。

## 1. 为什么有这个模块（设计意图）

Android 取证有两条经典路径：物理提取（分区/整机镜像，需要特殊模式或 root）和逻辑提取（应用数据、用户文件）。市面工具走 ADB 时通常 `popen()` 调 `adb pull` 命令行——进程开销大、输出解析脆弱、无法精细控制传输。

这个模块的思路是**直接实现 ADB 的 smart-socket 协议**：adb 守护进程常驻本机 5037 端口，客户端用 TCP 说一种很简单的文本协议就能枚举设备、执行 shell、传输文件。绕过命令行意味着：一个进程内连接、二进制安全的数据通道（sync 模式）、以及可以做"边 dd 边拉"的流式分区提取（不占用设备存储）。目录里 49KB 的 `README.md` 记录了完整的开发过程。

## 2. 在系统中的位置（如果它活着）

```
（设计中的位置）
AndroidDirectoryExtractor ──► ADBClient ──TCP:5037──► 本机 adb 服务器 ──USB──► Android 设备
        │ 产出
        ▼
./extracted_data/<设备路径镜像> 或 <分区>.img
        │ 作为输入
        ▼
AndroidAnalyzer（--android-source dir|zip 分析逻辑提取物；镜像则走 TSK）
```

**实际现状**：Android 取证数据获取完全绕开了它——实际流程是取证人员用外部工具（或手工 `adb pull` / 手机备份）产出目录或 zip，再用命令行 `--android-source dir|zip|miui-backup` 喂给 AndroidAnalyzer（`src/CommandLineParser.cpp:112, 195`）。它本该是"采集端"，现在只剩"分析端"。

## 3. 核心概念与设计

### 3.1 ADB smart-socket 协议

adb 服务器协议极简：每条命令是 `4 位十六进制长度 + 命令文本`（如 `001chost:transport:serial`），服务端回 `OKAY`/`FAIL` 四字节状态。`adbClient.h:75-86` 声明的 `sendADBCommand`/`receiveADBStatus` 就是这层封装。命令分两类前缀：`HOST:` 打给 adb 服务器管理设备（`HOST:devices` 列设备、`HOST:transport:<serial>` 选中设备），选中后发 `SHELL:<cmd>` 执行命令、`SYNC:` 进入文件传输模式。

```cpp
// ADBClient_Devices.cpp:4-38（节选）：枚举设备
if (!sendADBCommand("HOST:devices")) return devices;
if (!receiveADBStatus()) return devices;
std::string response = receiveData(4096);
// 响应按行解析："<serial>\t<status>"，只收集 status == "device" 的
```

连接目标写死为本机 adb 服务器：默认 `127.0.0.1:5037`（`adbClient.h:89`）——注意它**不直接连设备**，USB/网络设备的差异由 adb 守护进程屏蔽。

### 3.2 双通道：shell vs sync

- **shell 通道**（`ADBClient_Shell.cpp:5-22`）：`SHELL:` 后命令输出作为流返回，`executeShell` 读 8KB 后按 `\0` 截断——适合文本命令（`[ -d path ] && echo DIR`），不适合二进制（有独立的 `executeRaw`）。
- **sync 通道**（`adbClient.h:126-162`）：`SYNC:` 后进入二进制子协议，支持 `STAT`（取 mode/size/mtime）、`LIST`（列目录）、`RECV`（拉文件）。文件提取首选 sync，因为它二进制安全且带元数据。

设计上的关键决策是**逐级降级**：sync STAT 被权限拒绝时回退 `statFileShell`（shell `ls -l` 解析），LIST 为空时回退 `listDirectoryShell`，RECV 失败回退 `pullFileShell`（`adbClient.h:183-189`，使用处在 `adbExtractor.cpp:53-60, 72-77, 112-116`）——Android 各厂商 ROM 权限差异极大，这条路是踩坑踩出来的。

### 3.3 root 与分区提取

物理提取需要 root：`checkRootAccess()` 探测、`acquireRoot()` 执行 `adb root`（重启 adbd 为 root，连接需重建，`adbExtractor.cpp:154-168` 有重选设备的处理）。拿到 root 后分区提取有一条方法阶梯（`extractPartition`，`adbExtractor.cpp:255` 起，`531-540` 处的分派）：

1. `extractPartitionDirectly`/`extractPartitionStreaming`（`:486, :544`）：设备端 `dd if=/dev/block/...` 直接流式回传——不占设备存储，首选；
2. `extractPartitionUsingDD`（`:218-231`）：dd 到 `/data/local/tmp/<name>.img` 再 `pullFileShell` 拉回——设备要有足够空闲空间；
3. 传统路径 `extractPartitionTraditional`（`:596`）。

分区清单来自 `getPartitionList()`（`:406`）解析 `by-name` 符号链接；配套的 `PartitionInfo`（`AndroidAdbExtractorDataTypes.h:13-23`）记录 name/device_path/size/是否需要 root。试验程序 `adbTest.cpp:9-38` 还维护了 SAFE/DANGEROUS 分区白黑名单（efuse、frp、keymaster 等读取可能影响设备状态的分区被排除）——这是取证工具该有的保守性。

## 4. 工作流程走读（设计中的典型用法）

1. **初始化**（`adbExtractor.cpp:133-183`）：`adb.connect()` 连 5037 → `HOST:devices` 列设备（无设备即失败）→ 重连并 `selectDevice(devices[0])`（`HOST:transport:<serial>` + `DEV`，`ADBClient_Devices.cpp:40-63`）→ 默认 `auto_root=true` 尝试 `acquireRoot()` → `syncConnect()` 进入文件传输模式。
2. **逻辑提取**：`extractDirectory("/data/data/com.foo")`（`:185-197`）把设备路径映射到本地 `./extracted_data/data/data/com.foo`（构造函数在 `adbExtractor.h:63-66` 内联，建根目录），核心是递归：

```cpp
// adbExtractor.cpp:42-130（extractFileRecursive 逻辑摘要）
check = adb.executeShell("[ -d " + remote_path + " ] && echo DIR || echo FILE");
stat_success = adb.statFile(remote_path, mode, size, time);   // sync STAT
if (!stat_success && has_root) stat_success = adb.statFileShell(...);  // 降级
if ((mode & 0xF000) == 0x4000) {          // S_IFDIR：建目录 + LIST + 递归
    ...
} else {
    adb.receiveFile(remote_path, local_base, size);           // sync RECV
    if (!pull_success) adb.pullFileShell(remote_path, local_base); // 降级
}
```

3. **物理提取**：`extractPartition("userdata")` → 读分区表拿块设备路径 → 测可读性（`testPartitionReadAccess`，`:212`）→ 按第 3.3 节的阶梯取镜像。

## 5. 与其他模块的协作

| 相关方 | 关系 |
|---|---|
| AndroidAnalyzer（`src/analyzers/AndroidAnalyzer/`） | **本该衔接而未衔接**：AdbExtractor 产出目录/zip，AndroidAnalyzer 的 `--android-source dir\|zip` 模式消费这类产物。`IFileExtractor.h` 的头注释明说了设计意图——"an ADB logical/file-system pull packaged as an Image.zip"，即 LogicalDirExtractor/ZipArchiveExtractor 消费的就是 ADB 逻辑提取的产物 |
| AndroidAnalyzerCore.cpp:79-91 | sourceMode 分派：MiuiBackup/LogicalDir/Zip/TSK 四种后端；ADB 本该是第五种（或这三种的上游生产者） |
| adb 服务器 | 唯一外部依赖（本机 5037）；不依赖 adb 命令行可执行文件 |
| LLMIntegration 层 | 无直接关系；提取完成后产物可走 FileAnalyzer 等分析链路 |

## 6. 注意事项与已知问题

- **死代码三重确认**：不在 `LIB_SOURCES`（仅 `CMakeLists.txt:210` 的 include 路径）；无外部引用；`-fsyntax-only` 编译失败（成员名失配 + 缺 `<fcntl.h>` 等 include）。任何"复活"工作从修 `adbClient.h` 与三个 `ADBClient_*.cpp` 的一致性开始。
- **头文件里的连接管理是旧版**：`adbClient.h:34-41` 声明的 `sock/current_serial/in_sync_mode` 与实现文件的 `socket_fd_/current_device_` 对不上；读头文件理解协议接口即可，别当实现真相。
- **单设备假设**：`initialize()` 直接取 `devices[0]`（`adbExtractor.cpp:150`），多设备在线时无法选择目标——取证场景这是必须修的（设备选择直接影响证据链）。
- **流式读取的阻塞风险**：`receiveData` 用 select + 30 秒超时（`ADBClient_Init.cpp:38-56`），但大分区流式传输若中途停滞，超时后返回半截数据可能被当成功处理。
- **写操作无防护**：分区提取只做读，但 shell 通道本质可执行任意命令，若复活为服务暴露面需要严格白名单化（`adbTest.cpp` 的 SAFE/DANGEROUS 名单思路可扩展）。
- **Windows 痕迹**：`test_console_encoding.cpp`、`test_encoding_fix.bat`、`initializeConsoleEncoding()`（非 Windows 下为空实现）都指向它曾在 Windows 上开发，跨平台宏（`adbClient.h:13-24` 的 socket_t 抽象）是认真的，但 Linux 侧从未进入构建。

## 7. 如何验证与扩展

**验证现状**：
1. `grep -n adb CMakeLists.txt` 确认无源文件条目；`grep -rn ADBClient src/ --include=*.cpp -l` 确认无外部引用；`g++ -std=c++17 -fsyntax-only src/integration/AndroidAdbExtractor/ADBClient_Init.cpp` 复现编译失败。
2. 当前 Android 逻辑取证的正确入口是命令行：`--android-source dir|zip|miui-backup`（`CommandLineParser.cpp:112`），产出目录或 zip 后由 `LogicalDirExtractor`/`ZipArchiveExtractor`/`MiuiBackupExtractor` 接管（`AndroidAnalyzerCore.cpp:79-91`）。

**如果要在现代代码库里复活它**：
1. 统一 `adbClient.h` 与三个实现文件的成员命名（或干脆按头重写实现），补 `#include <fcntl.h>`；
2. 进程内保留一个 ADBClient 池（每设备一连接），把"提取到目录"实现为产出符合 `IFileExtractor` 约定的目录结构，与现有 `--android-source dir` 无缝对接——这是最小代价的整合方式；
3. 多设备枚举与用户选择、提取哈希校验（证据完整性）、进度回调对接 ThreadPool；
4. 分区流式提取改用 `executeRaw` + 定长循环读并校验字节数，替代超时即返回的 `receiveData`。

**最后更新**: 2026-08-23（解释式重写）
