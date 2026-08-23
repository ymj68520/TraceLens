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

### 3.1 类结构：两层封装

底层 `ADBClient`（`adbClient.h:32-191`）封装协议与 socket；上层 `AndroidDirectoryExtractor`（`adbExtractor.h:26-86`）封装取证流程。ADBClient 的公开面（节选自 `adbClient.h:88-191`）：

```cpp
// adbClient.h:88-191（节选）
public:
    ADBClient(const std::string &h = "127.0.0.1", int p = 5037);   // 默认本机 adb 服务器
    bool connect();                                    // 连 5037 并握手
    bool disconnect();                                 // 发 QUIT 后关 socket
    std::vector<std::string> getDevices();             // HOST:devices → 在线序列号
    bool selectDevice(const std::string &serial);      // HOST:transport:<serial> + DEV
    std::string executeShell(const std::string &cmd);  // SHELL:<cmd>，文本输出
    bool syncConnect();                                // 进入 SYNC 文件传输子协议

    struct SyncEntry {                                 // adbClient.h:140-145
        std::string name;
        uint32_t mode;      // 高 4 位是文件类型（0x4000 = 目录）
        uint32_t size;
        uint32_t time;      // mtime
    };
    std::vector<SyncEntry> listDirectory(const std::string& path);              // SYNC LIST
    bool statFile(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time);
    bool receiveFile(const std::string& remote_path, const std::string& local_path,
                     uint32_t total_file_size = 0);                             // SYNC RECV
    bool checkRootAccess();                            // 探测 root
    bool acquireRoot();                                // adb root（重启 adbd）
    bool executeRaw(const std::string &command, std::vector<char>& output);     // 无 PTY 二进制通道
    // Shell 降级三件套（adbClient.h:187-189）：statFileShell / listDirectoryShell / pullFileShell
```

连接目标写死为本机 adb 服务器：默认 `127.0.0.1:5037`（`adbClient.h:89`）——注意它**不直接连设备**，USB/网络设备的差异由 adb 守护进程屏蔽。上层的 `AndroidDirectoryExtractor` 状态极简（`adbExtractor.h:26-33`）：一个 `ADBClient adb` 成员、`output_dir`（构造时建目录，默认 `./extracted_data`，`adbExtractor.h:63-66`）、`has_root`/`use_root_for_extraction` 两个布尔。
### 3.2 ADB smart-socket 协议

adb 服务器协议极简：每条命令是 `4 位十六进制长度 + 命令文本`（如 `001chost:transport:serial`），服务端回 `OKAY`/`FAIL` 四字节状态。命令分两类前缀：`HOST:` 打给 adb 服务器管理设备（`HOST:devices` 列设备、`HOST:transport:<serial>` 选中设备），选中后发 `SHELL:<cmd>` 执行命令、`SYNC:` 进入文件传输模式。

但**实现与规范有一处要命的出入**。看 `sendADBCommand` 的真实代码（`ADBClient_Init.cpp:72-80`）：

```cpp
// ADBClient_Init.cpp:72-80
bool ADBClient::sendADBCommand(const std::string &cmd) {
    std::string message = cmd;
    message += "\0";                                  // 意图是补 NUL，但 strlen("\0")==0，实为空操作

    uint32_t length = htonl(message.length());
    if (!sendData(std::string(reinterpret_cast<char*>(&length), 4))) return false;

    return sendData(message);
}
```

真实 ADB smart-socket 协议要求长度前缀是 **4 位十六进制 ASCII**（如 `001c`），而这里发的是 `htonl(len)` 的 **4 字节二进制大端值**（如 `\x00\x00\x00\x1c`）——按此实现连真实 adb 服务器大概率无法完成握手。这与"头实现失配、从未进入构建"的处境互相印证：这套代码从未对着真实 adb 服务器跑通过当前形态。复活时这层必须重写。状态读取倒是简单（`ADBClient_Init.cpp:82-86`）：

```cpp
bool ADBClient::receiveADBStatus() {
    char status[4];
    if (!receiveExact(status, 4)) return false;   // receiveExact 循环 recv 凑满 4 字节（:62-70）
    return std::string(status, 4) == "OKAY";
}
```

设备枚举与选择（`ADBClient_Devices.cpp:6-61`）：

```cpp
// ADBClient_Devices.cpp:6-37（节选）：枚举设备
std::vector<std::string> ADBClient::getDevices() {
    std::vector<std::string> devices;
    if (socket_fd_ < 0 && !connect()) return devices;
    if (!sendADBCommand("HOST:devices"))  return devices;
    if (!receiveADBStatus())              return devices;

    std::string response = receiveData(4096);
    std::istringstream iss(response);
    std::string line;
    while (std::getline(iss, line)) {
        size_t tab_pos = line.find('\t');
        if (tab_pos != std::string::npos) {
            std::string serial = line.substr(0, tab_pos);
            std::string status = line.substr(tab_pos + 1);
            if (status == "device") {          // 只收 "device" 状态；unauthorized/offline 排除
                devices.push_back(serial);
            }
        }
    }
    return devices;
}
```

选择设备（`:39-61`）是两条命令的序列：`HOST:transport:<serial>`（把连接绑定到该设备，同时记 `current_device_`）→ `DEV`，各等一次 `OKAY`。`current_device_` 为空时 `executeShell`/`receiveFile` 直接拒绝（`ADBClient_Shell.cpp:5-7`）——防止命令打到未选目标的连接上。

### 3.3 双通道：shell vs sync

- **shell 通道**（`ADBClient_Shell.cpp:5-22`）：`SHELL:` 后命令输出作为流返回，`executeShell` 读 8KB 后按 `\0` 截断——适合文本命令（`[ -d path ] && echo DIR`），不适合二进制（有独立的 `executeRaw`）：

```cpp
// ADBClient_Shell.cpp:5-22（节选）
std::string ADBClient::executeShell(const std::string &command) {
    if (current_device_.empty()) return "";
    if (!sendADBCommand("SHELL:" + command)) return "";
    // For shell commands, we might not always get OKAY
    // Try to read response anyway
    std::string response = receiveData(8192);
    // Trim trailing null characters
    size_t end = response.find('\0');
    if (end != std::string::npos) response = response.substr(0, end);
    return response;
}
```

- **sync 通道**（`adbClient.h:126-162`）：`SYNC:` 后进入二进制子协议，支持 `STAT`（取 mode/size/mtime）、`LIST`（列目录）、`RECV`（拉文件）。文件提取首选 sync，因为它二进制安全且带元数据。

设计上的关键决策是**逐级降级**：sync STAT 被权限拒绝时回退 `statFileShell`（shell `ls -l` 解析），LIST 为空时回退 `listDirectoryShell`，RECV 失败回退 `pullFileShell`（`adbClient.h:183-189`，使用处在 `adbExtractor.cpp:53-60, 72-77, 112-116`）——Android 各厂商 ROM 权限差异极大，这条路是踩坑踩出来的。

### 3.4 root 与分区提取

物理提取需要 root。`initialize()`（`adbExtractor.cpp:133-183`）是完整的取 root 流程：

```cpp
// adbExtractor.cpp:133-167（节选）
bool AndroidDirectoryExtractor::initialize(bool auto_root) {
    if (!adb.connect()) return false;
    auto devices = adb.getDevices();
    adb.disconnect();                                  // 枚举与传输分两次连接
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    if (devices.empty()) { std::cerr << "No device found" << std::endl; return false; }
    std::cout << "Found " << devices.size() << " device(s)" << std::endl;
    std::cout << "  Using device: " << devices[0] << std::endl;   // ← 单设备假设：永远取 [0]

    if (!adb.connect()) return false;
    if (!adb.selectDevice(devices[0])) return false;

    if (auto_root) {
        has_root = adb.checkRootAccess();
        if (!has_root) {
            has_root = adb.acquireRoot();              // adb root 会重启 adbd
            if (has_root) adb.selectDevice(devices[0]); // ← 连接已失效，必须重选设备
        }
    }
    // ...
    if (!adb.syncConnect()) return false;              // 最后进入 SYNC 模式
    return true;
}
```

注释点：枚举设备后**断开重连**（adb 服务器的 devices 查询会占用连接）；`acquireRoot()` 执行 `adb root` 会重启 adbd 进程导致旧连接失效，所以拿到 root 后立即 `selectDevice` 重选；`devices[0]` 的单设备假设是第 6 节列出的问题。

拿到 root 后分区提取有一条方法阶梯（`extractPartition`，`adbExtractor.cpp:255` 起，`531-540` 处的分派）：

1. `extractPartitionDirectly`/`extractPartitionStreaming`（`:486, :544`）：设备端 `dd if=/dev/block/...` 直接流式回传——不占设备存储，首选；
2. `extractPartitionUsingDD`（`:218-231`）：dd 到 `/data/local/tmp/<name>.img` 再 `pullFileShell` 拉回——设备要有足够空闲空间：dd 命令为 `"dd if=" + block_device + " of=/data/local/tmp/" + partition_name + ".img bs=4096"`（root shell 执行），产物以 `pullFileShell` 拉回，输出含 "No such file" 即判失败；

3. 传统路径 `extractPartitionTraditional`（`:596`）。

分区清单来自 `getPartitionList()`（`:406`）解析 `by-name` 符号链接；配套的 `PartitionInfo`（`AndroidAdbExtractorDataTypes.h:13-23`）记录 name/device_path/size/是否需要 root：

```cpp
// AndroidAdbExtractorDataTypes.h:13-23
struct PartitionInfo {
    std::string name;           // 分区名称 (如 "vbmeta", "boot")
    std::string device_path;    // 设备路径 (如 "/dev/block/by-name/vbmeta")
    std::string block_device;   // 实际块设备路径 (如 "/dev/block/sde12")
    uint64_t size;              // 分区大小 (字节)
    std::string type;           // 分区类型 (如 "emmc", "ufs")
    bool is_readable;           // 是否可读
    bool requires_root;         // 是否需要root权限
    PartitionInfo() : size(0), is_readable(false), requires_root(true) {}
};
```

默认 `requires_root = true` 体现了保守取向：未知分区一律按"需要 root"对待。试验程序 `adbTest.cpp:9-54` 还维护了 SAFE/DANGEROUS 分区白黑名单：

```cpp
// adbTest.cpp:9-36（节选）
std::vector<std::string> SAFE_PARTITIONS = {
    "vbmeta", "boot", "recovery", "system", "vendor", "product",
    "cache", "userdata", "misc", "persist"
};
std::vector<std::string> DANGEROUS_PARTITIONS = {
    "efuse",     // 熔丝设置
    "param", "frp", "config", "sec",
    "keymaster", // 密钥管理
    "tee",       // 可信执行环境
    "proinfo"    // 生产信息
};

bool isSafePartition(const std::string& partition_name) {
    for (const auto& dangerous : DANGEROUS_PARTITIONS)
        if (partition_name.find(dangerous) != std::string::npos) return false;
    for (const auto& safe : SAFE_PARTITIONS)
        if (partition_name.find(safe) != std::string::npos) return true;
    // 默认情况下，不认识的分区被认为是中等风险的
    return false;   // 默认拒绝
}
```

判定顺序是"危险黑名单优先、安全白名单其次、未知默认拒绝"（子串匹配，`keymaster2` 也会被拒）——读取可能影响设备状态的分区被排除，这是取证工具该有的保守性。

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

   `(mode & 0xF000) == 0x4000` 是 POSIX 的 `S_IFMT`/`S_IFDIR` 位判断——sync STAT 返回的 mode 是设备侧 Linux 原生 st_mode，符号链接等其他类型走"跳过"分支（`:126-130`）。
3. **物理提取**：`extractPartition("userdata")` → 读分区表拿块设备路径 → 测可读性（`testPartitionReadAccess`，`:212`，即 root shell 跑 `test -r ... && echo readable`）→ 按第 3.4 节的阶梯取镜像。

## 5. 与其他模块的协作

| 相关方 | 关系 |
|---|---|
| AndroidAnalyzer（`src/analyzers/AndroidAnalyzer/`） | **本该衔接而未衔接**：AdbExtractor 产出目录/zip，AndroidAnalyzer 的 `--android-source dir\|zip` 模式消费这类产物。`IFileExtractor.h` 的头注释明说了设计意图——"an ADB logical/file-system pull packaged as an Image.zip"，即 LogicalDirExtractor/ZipArchiveExtractor 消费的就是 ADB 逻辑提取的产物 |
| AndroidAnalyzerCore.cpp:79-91 | sourceMode 分派：MiuiBackup/LogicalDir/Zip/TSK 四种后端；ADB 本该是第五种（或这三种的上游生产者） |
| adb 服务器 | 唯一外部依赖（本机 5037）；不依赖 adb 命令行可执行文件 |
| LLMIntegration 层 | 无直接关系；提取完成后产物可走 FileAnalyzer 等分析链路 |

## 6. 注意事项与已知问题

- **死代码三重确认**：不在 `LIB_SOURCES`（仅 `CMakeLists.txt:210` 的 include 路径）；无外部引用；`-fsyntax-only` 编译失败（成员名失配 + 缺 `<fcntl.h>` 等 include）。任何"复活"工作从修 `adbClient.h` 与三个 `ADBClient_*.cpp` 的一致性开始。
- **协议实现与 adb 规范不符**：`sendADBCommand` 发的是 `htonl` 二进制长度而非 4 位十六进制 ASCII（见 3.2 的代码走读）——即使修好编译错误，对真实 adb 服务器的握手也会失败；附带一提 `message += "\0"` 因 `strlen` 语义实际是空操作。
- **头文件里的连接管理是旧版**：`adbClient.h:34-41` 声明的 `sock/current_serial/in_sync_mode` 与实现文件的 `socket_fd_/current_device_` 对不上；读头文件理解协议接口即可，别当实现真相。
- **单设备假设**：`initialize()` 直接取 `devices[0]`（`adbExtractor.cpp:150`），多设备在线时无法选择目标——取证场景这是必须修的（设备选择直接影响证据链）。
- **流式读取的阻塞风险**：`receiveData` 用 select + 30 秒超时、单次 `recv`（`ADBClient_Init.cpp:37-60`），但大分区流式传输若中途停滞，超时后返回半截数据可能被当成功处理；且单次 recv 不保证读满请求长度（`receiveExact` 才循环凑字节）。
- **写操作无防护**：分区提取只做读，但 shell 通道本质可执行任意命令，若复活为服务暴露面需要严格白名单化（`adbTest.cpp` 的 SAFE/DANGEROUS 名单思路可扩展）。
- **Windows 痕迹**：`test_console_encoding.cpp`、`test_encoding_fix.bat`、`initializeConsoleEncoding()`（非 Windows 下为空实现）都指向它曾在 Windows 上开发，跨平台宏（`adbClient.h:13-24` 的 socket_t 抽象）是认真的，但 Linux 侧从未进入构建。

## 7. 如何验证与扩展

**验证现状**：
1. `grep -n adb CMakeLists.txt` 确认无源文件条目；`grep -rn ADBClient src/ --include=*.cpp -l` 确认无外部引用；`g++ -std=c++17 -fsyntax-only src/integration/AndroidAdbExtractor/ADBClient_Init.cpp` 复现编译失败。
2. 当前 Android 逻辑取证的正确入口是命令行：`--android-source dir|zip|miui-backup`（`CommandLineParser.cpp:112`），产出目录或 zip 后由 `LogicalDirExtractor`/`ZipArchiveExtractor`/`MiuiBackupExtractor` 接管（`AndroidAnalyzerCore.cpp:79-91`）。

**如果要在现代代码库里复活它**：
1. 统一 `adbClient.h` 与三个实现文件的成员命名（或干脆按头重写实现），补 `#include <fcntl.h>`；
2. **重写长度前缀编码**：把 `htonl` 二进制长度改为 4 位十六进制 ASCII（见第 6 节协议问题），用本机 adb 服务器做握手冒烟；
3. 进程内保留一个 ADBClient 池（每设备一连接），把"提取到目录"实现为产出符合 `IFileExtractor` 约定的目录结构，与现有 `--android-source dir` 无缝对接——这是最小代价的整合方式；
4. 多设备枚举与用户选择、提取哈希校验（证据完整性）、进度回调对接 ThreadPool；
5. 分区流式提取改用 `executeRaw` + 定长循环读并校验字节数，替代超时即返回的 `receiveData`。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
