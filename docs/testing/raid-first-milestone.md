# RAID第一里程碑：实际验收记录（2026-09-29）

## 执行边界

- 分支：`feature/android-forensics-report-structure`。
- 基线提交：`c7f1fc3c0281527fb635773515521ed23960aecc`，执行前已有 347 项 dirty
  变更；未清理工作区、未切换分支、未提交或推送这些历史变更。
- 原展示服务 PID：C++ `1715913`、Python `1943646`、nginx `1943681`，结束时
  同一 PID 仍在运行。未重启服务、修改监听或迁移历史调查数据。
- 没有调用生产 API、创建/重跑/删除真实 Task；本轮所有输入均为合成检材。
- C++ 最小路径修复只增量编译到独立 `/tmp/tracelens-raid-cpp-regression-hepoxsle/`
  目录；没有覆盖原 `build/forensic_analyzer` 或已冻结运行包。

## 验证矩阵

| 实际输入 | 独立预期与实际结果 | 状态 |
| --- | --- | --- |
| MD v1.2 RAID0，3个RAW成员，全部6种输入排列 | 786432字节已知逻辑内容逐字节一致，含跨条带及末尾读取 | 合成 PASS |
| MD v1.2 RAID1，3个RAW成员，全部6种输入排列 | 已知逻辑内容一致；副本冲突必须拒绝 | 合成 PASS |
| MD v1.2 RAID5，3个RAW成员，全部6种输入排列 | 六种已支持布局的完整内容匹配；错误 parity 必须拒绝 | 合成 PASS |
| RAID5 E01成员：未压缩、多段 | 每个成员真实产生多个EWF分段；成员输入反序，4MiB逻辑内容匹配；缺段拒绝 | 合成 PASS |
| RAID5 E01成员：deflate压缩 | 压缩解码后的完整逻辑内容匹配 | 合成 PASS |
| 故意损坏的未压缩EWF chunk | 明确 checksum 错误，不接受填零或补齐 | 拒绝 PASS |
| RAID5重组 -> 16MiB EXT4 -> `fls/icat` | `source.txt`中文正文与独立原文相同 | 合成 PASS |
| 同一三成员RAID5 -> 16MiB Android EXT4 -> 实际C++ CLI | 短信2、联系人1、应用1、Wi-Fi1；正文、号码、方向、时间、联系人字段、包名/版本、Wi-Fi字段多重集合匹配 | 合成 PASS |
| 独立编译的 mdadm `--examine --config=/dev/null` | 合成成员被识别为正确 checksum、clean RAID5，无内核装配 | 合成 PASS |
| 完整第三方源码包恢复到隔离目录 | 9份快照、2806个文件全部哈希匹配，包含原本被Git忽略的Windows源码和fuzz seeds | 离线 PASS |

RAW/E01支持不等于其内部任意文件系统和应用已支持。RAID0/1 的 E01路径
本轮未单独差分验收，不能用RAID5的测试代替它们。

## Android链路断点及最小修复

首次接现有C++ CLI，文件列表已有四个目标文件，但工件数量为 **0/0/0/0**。
原因不是重组字节错误，而是文件表保存 `/data/...`、解析器请求 `data/...`，
提取层只做精确单路径查询。修复为参数化双拼写匹配，仍拒绝多条匹配，
不创建虚假文件或修改 Android 字段语义。隔离修复后二次验收达到 **2/1/1/1**。

CLI的工件按其原语义写入 `logical_files.db`；没有冒充生产HTTP Task的
`android.db`链路已通过。Task选择、Investigation成员级来源、报告回跳均待接入。

## 最终回归与可复核产物

最终运行 **50 passed、0 skipped、0 failed**，pytest计时50.98秒，整进程
wall时间58.79秒，最大RSS83336KiB（约81.4MiB）。完整运行包含源哈希和重哈希，
不是只计条带读取时间。测试报告：`build/raid-validation/tests.xml`。

环境：WSL2 Linux `6.18.33.2-microsoft-standard-WSL2`、32个可见CPU、约15.3GiB
内存。合成数据位于Linux `/tmp`，源码位于Windows挂载的`/mnt/d`；不能把该
小样本结果外推为TB级吞吐或内存保证。

本轮最后一次合成Android回归的证据路径（临时目录可被后续pytest清理）：

```text
/tmp/pytest-of-root/pytest-169/test_actual_tracelens_android_0/inbox/
/tmp/pytest-of-root/pytest-169/test_actual_tracelens_android_0/outputs/70f0e4ff9cb34ad59af8ab9aedae02f2/raid_manifest.json
/tmp/pytest-of-root/pytest-169/test_actual_tracelens_android_0/isolated-runtime/databases/logical_files.db
/tmp/pytest-of-root/pytest-169/test_actual_tracelens_android_0/isolated-runtime/raid-integration-result.json
```

- 逻辑镜像：16777216字节；SHA-256
  `c6586be64e1b955a5ca54d16e7790d495dcc745bc4fadc9cdd5ca5297cbf640b`。
- 隔离增量验证程序SHA-256：
  `9d713419743767deafdf93f0684fb3fb1efdc2b0610116b6dd9ada77c198f434`。
- 该样本的源哈希0.015918秒、逻辑读取/校验/导出0.064844秒、源重哈希
  0.013045秒。这些时间不包括生成文件系统、编译或Android解析。
- 重组输出包为 `COMPLETE`；当前整体RAID功能仍是**首批核心完成、整链PARTIAL**。

完整源码分发：`third_party/raid/sources.bundle.tar.gz`，7529228字节；SHA-256
`be66365f7ed1a6acf523720c22881ca5fafc4c66d2538f0b58e091ad45d74bc5`。
保存源码不表示已启用其全部能力；`raid_recovery`、nbdkit/libnbd尚未接入运行链。

## 独立保留的缺口

- `PRODUCTION_TASK_UI_NOT_CONNECTED`：网页多成员选择、生产Task准入未接入。
- `INVESTIGATION_MEMBER_TRACE_NOT_CONNECTED`：研判/报告尚不能直接回跳成员来源。
- `REAL_SAMPLE_REQUIRED`：没有本轮获准真实RAID样本。
- `TB_SCALE_NOT_VALIDATED`：没有TB级测试，当前显式导出默认限额1GiB。
- 无元数据RAID5、DDF/IMSM、其他MD版本、RAID6/10、缺盘恢复、重建中的阵列
  和非零MD feature均不能宣称本轮兼容；原始成员分区自动发现也未实现。

## 复现命令

```sh
python3 scripts/raid_vendor_sources.py verify
bash scripts/build_raid_md_examine.sh
python3 scripts/build_raid_cpp_regression.py --build build
# 将上两条命令打印的独立程序路径代入，不使用生产服务或HTTP端口：
TRACELENS_RAID_MDADM=/tmp/DIAGNOSTIC_BUILD/mdadm/mdadm \
TRACELENS_RAID_TEST_ANALYZER=/tmp/REGRESSION_BUILD/forensic_analyzer \
PYTHONDONTWRITEBYTECODE=1 python_service/.venv/bin/python -m pytest \
  tests/raid_validation -q --import-mode=importlib -p no:cacheprovider \
  --junitxml=build/raid-validation/tests.xml
```

不设置这两个显式工具路径时，相关生产CLI/独立oracle测试标为SKIP，不能
将这种运行误报为完整端到端验收。新RAID模块和CLI采用AGPL-3.0-or-later，
保留第三方原许可证；没有推送或公开Git仓库，也没有接入闭源工具。
