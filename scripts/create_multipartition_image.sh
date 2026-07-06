#!/usr/bin/env bash
# =============================================================================
# 创建多分区测试镜像 — 用于验证多分区文件系统解析
#
# 生成一个含 2 个分区（ext4 + NTFS）的 MBR 磁盘镜像，每个分区里放几个
# 带区分度的文件，用来验证 ImageAnalyzer 遍历所有分区、FileExtractor 按分区
# 路由抽取的正确性。
#
# 需要 sudo（用于 losetup 挂载分区写入文件）。
#
# 用法： sudo bash scripts/create_multipartition_image.sh [输出路径]
# 默认输出： tests/test_multi_partition.img
# =============================================================================
set -euo pipefail

OUTPUT="${1:-$(dirname "$0")/../tests/test_multi_partition.img}"
OUTPUT="$(readlink -f "$OUTPUT")"
IMG_DIR="$(dirname "$OUTPUT")"
mkdir -p "$IMG_DIR"

echo "=== 创建多分区测试镜像 ==="
echo "输出: $OUTPUT"
echo ""

# 1. 创建 200MB 空镜像
echo "[1/6] 创建 200MB 空镜像..."
dd if=/dev/zero of="$OUTPUT" bs=1M count=200 status=none

# 2. 用 sgdisk 创建 GPT 分区表 + 2 个分区（各 ~90MB）
#    分区1: ext4 (Linux)，分区2: NTFS (Windows)
echo "[2/6] 创建分区表（2 个分区: ext4 + NTFS）..."
sgdisk --clear \
  --new=1:2048:184320   --typecode=1:8300 --change-name=1:"LinuxRoot" \
  --new=2:186368:407551 --typecode=2:0700 --change-name=2:"WindowsData" \
  "$OUTPUT" >/dev/null

# 3. 关联 loop 设备（-P 让内核解析分区）
echo "[3/6] 关联 loop 设备..."
LOOPDEV=$(losetup -fP --show "$OUTPUT")
if [ -z "$LOOPDEV" ]; then
  echo "错误：无法关联 loop 设备（需要 sudo 或 loop 模块）" >&2
  exit 1
fi
echo "  loop 设备: $LOOPDEV"
trap 'losetup -d "$LOOPDEV" 2>/dev/null || true' EXIT

# 等待分区设备节点出现
sleep 1
for i in $(seq 1 10); do
  [ -b "${LOOPDEV}p1" ] && [ -b "${LOOPDEV}p2" ] && break
  sleep 0.5
done
if [ ! -b "${LOOPDEV}p1" ] || [ ! -b "${LOOPDEV}p2" ]; then
  echo "错误：分区设备未出现 (${LOOPDEV}p1/p2)" >&2
  exit 1
fi

# 4. 格式化分区
echo "[4/6] 格式化分区..."
mkfs.ext4 -F -L "LinuxRoot" "${LOOPDEV}p1" >/dev/null 2>&1
mkfs.ntfs  -F -L "WinData"  "${LOOPDEV}p2" >/dev/null 2>&1 || \
  mkfs.vfat -F 32           "${LOOPDEV}p2" >/dev/null 2>&1   # fallback to vfat if ntfs missing

# 5. 挂载并写入测试文件（每个分区的文件内容带区分标记）
echo "[5/6] 写入测试文件..."
MNT1=$(mktemp -d); MNT2=$(mktemp -d)
trap 'umount "$MNT1" 2>/dev/null || true; umount "$MNT2" 2>/dev/null || true; rmdir "$MNT1" "$MNT2" 2>/dev/null || true; losetup -d "$LOOPDEV" 2>/dev/null || true' EXIT

mount "${LOOPDEV}p1" "$MNT1"
mount "${LOOPDEV}p2" "$MNT2"

# ext4 分区（模拟 Linux 根）：放 log、passwd、bash_history
mkdir -p "$MNT1/var/log" "$MNT1/etc" "$MNT1/home/user" "$MNT1/root" "$MNT1/usr/bin"
echo "ext4-partition-marker: LinuxRoot (partition 1)" > "$MNT1/etc/os-release"
echo "root:x:0:0:root:/root:/bin/bash"                 > "$MNT1/etc/passwd"
echo "ssh root@evil.example.com"                       > "$MNT1/home/user/.bash_history"
echo "Jan 01 12:00:00 host sshd[123]: Accepted password for root" > "$MNT1/var/log/auth.log"
echo "test ext4 file content from partition 1"         > "$MNT1/var/log/syslog"
echo "secret-token-12345"                              > "$MNT1/root/secret.txt"
for i in $(seq 1 5); do mkdir -p "$MNT1/usr/bin"; echo "bin file $i" > "$MNT1/usr/bin/tool$i"; done

# NTFS/VFAT 分区（模拟 Windows 数据）：放文档、图片占位
mkdir -p "$MNT2/Users/Admin/Documents" "$MNT2/Windows/System32/config"
echo "ntfs-partition-marker: WindowsData (partition 2)" > "$MNT2/marker.txt"
echo "Sensitive Windows document content here"          > "$MNT2/Users/Admin/Documents/report.txt"
echo "fake registry hive"                               > "$MNT2/Windows/System32/config/SOFTWARE"
for i in $(seq 1 5); do echo "win file $i" > "$MNT2/Users/Admin/Documents/doc$i.txt"; done

sync
umount "$MNT1"; umount "$MNT2"
rmdir "$MNT1" "$MNT2"

# 6. 解除 loop（trap 会处理）
echo "[6/6] 完成。"
losetup -d "$LOOPDEV" 2>/dev/null || true
trap - EXIT

echo ""
echo "=== 验证：分区表 ==="
sgdisk -p "$OUTPUT" 2>/dev/null || fdisk -l "$OUTPUT"
echo ""
echo "镜像创建成功: $OUTPUT ($(du -h "$OUTPUT" | cut -f1))"
echo ""
echo "现在用它测试多分区解析："
echo "  ./build/forensic_analyzer $OUTPUT --db-dir /tmp/mptest"
echo "  sqlite3 /tmp/mptest/*.raw.db 'SELECT partition_num, COUNT(*) FROM files GROUP BY partition_num;'"
