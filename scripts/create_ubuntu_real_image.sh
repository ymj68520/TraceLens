#!/usr/bin/env bash
# create_ubuntu_real_image.sh — 构造一个"真实"的未加密 Ubuntu Linux 磁盘镜像用于全链路测试。
#
# 与 test_image.img（裸 ext4 + 合成数据）不同，本镜像：
#   - GPT 分区表 + 2 个分区：128MiB FAT32 EFI 系统分区 + ~770MiB ext4 根分区（模拟真实 UEFI Ubuntu 安装）
#   - 内容取自本机真实系统：/etc 全量、真实系统日志(auth/syslog/kern/dpkg/wtmp/btmp/journal)、
#     真实 shell 历史、真实 EFI 引导文件、真实 PDF/图片/SQLite、常用二进制
#   - 刻意覆盖取证难点：中文/空格文件名、.gz 轮转日志、utmp/wtmp 二进制、已删除文件(雕刻)、
#     符号链接(/bin->usr/bin、/etc/mtab)、稀疏镜像文件
#   - 出于安全考虑不包含：用户 SSH 私钥(~/.ssh/id_*)、token 库等高敏感凭据
#
# 用法： sudo bash scripts/create_ubuntu_real_image.sh [输出路径]   (默认 tests/ubuntu_real.img)
# 输出为稀疏文件：表观 900MiB，实际占用约 200-300MiB。
set -euo pipefail

OUT=${1:-"$(cd "$(dirname "$0")/.." && pwd)/tests/ubuntu_real.img"}
TOTAL_SECTORS=1843200   # 900MiB / 512B
ESP_SECTORS=262144       # 128MiB
MNT=$(mktemp -d /tmp/tracelens_img.XXXXXX)
LOOP=""

cleanup() {
    local rc=$?
    set +e
    if [[ -n "$LOOP" ]]; then
        mountpoint -q "$MNT/boot/efi" && umount "$MNT/boot/efi"
        mountpoint -q "$MNT" && umount "$MNT"
        losetup -d "$LOOP" 2>/dev/null
    fi
    rmdir "$MNT" 2>/dev/null
    exit $rc
}
trap cleanup EXIT

[[ $EUID -eq 0 ]] || { echo "ERROR: must run as root (sudo)"; exit 1; }

echo "==> [1/7] 创建稀疏镜像 $OUT (900MiB 表观)"
rm -f "$OUT"
truncate -s $((TOTAL_SECTORS * 512)) "$OUT"

echo "==> [2/7] 写入 GPT 分区表 (EFI 128MiB + root ext4)"
sfdisk --quiet "$OUT" <<EOF
label: gpt
unit: sectors
start=2048, size=$ESP_SECTORS, type=uefi, name="EFI System Partition"
start=$((2048 + ESP_SECTORS)), type=linux, name="rootfs"
EOF

LOOP=$(losetup --find --partscan --show "$OUT")
echo "    loop device: $LOOP"

echo "==> [3/7] 格式化 (FAT32 ESP + ext4 root)"
mkfs.vfat -F 32 -n EFI "${LOOP}p1" >/dev/null
mkfs.ext4 -F -q -E lazy_itable_init=0 "${LOOP}p2"

mount -o noatime "${LOOP}p2" "$MNT"
mkdir -p "$MNT/boot/efi"
mount -o noatime "${LOOP}p1" "$MNT/boot/efi"

echo "==> [4/7] 填充 EFI 分区 + /boot"
cp -a /boot/efi/EFI/. "$MNT/boot/efi/EFI/" 2>/dev/null || mkdir -p "$MNT/boot/efi/EFI"
mkdir -p "$MNT/boot/grub"
cp -a /boot/grub/grub.cfg "$MNT/boot/grub/" 2>/dev/null || true
for f in /boot/vmlinuz-7.0.0-30-generic /boot/config-7.0.0-30-generic \
         /boot/config-7.0.0-28-generic /boot/memtest86+x64.efi; do
    [[ -f "$f" ]] && cp -a "$f" "$MNT/boot/"
done
# 保留 vmlinuz 符号链接（真实系统布局）
[[ -f /boot/vmlinuz-7.0.0-30-generic ]] && ln -sf vmlinuz-7.0.0-30-generic "$MNT/boot/vmlinuz"

echo "==> [5/7] 填充根分区（真实系统内容）"
# --- /etc 全量（真实账户/shadow/ssh主机密钥/cron/systemd 配置） ---
mkdir -p "$MNT/etc"
cp -a /etc/. "$MNT/etc/"

# --- /var/log 精选（含 .gz 轮转、utmp/wtmp/lastlog 二进制、systemd journal） ---
mkdir -p "$MNT/var/log/apt" "$MNT/var/log/journal"
for f in auth.log auth.log.1 auth.log.2.gz auth.log.3.gz \
         syslog syslog.1 syslog.2.gz \
         kern.log kern.log.1 kern.log.2.gz \
         dpkg.log dpkg.log.1 dpkg.log.2.gz \
         cloud-init.log wtmp btmp lastlog; do
    [[ -f "/var/log/$f" ]] && cp -a "/var/log/$f" "$MNT/var/log/"
done
[[ -f /var/log/apt/history.log ]] && cp -a /var/log/apt/history.log "$MNT/var/log/apt/"
# journal：当前 system.journal（若 ≤64M）+ 最近的用户 journal
JDIR=$(ls -d /var/log/journal/*/ 2>/dev/null | head -1 || true)
if [[ -n "$JDIR" ]]; then
    DEST="$MNT/var/log/journal/$(basename "$JDIR")"
    mkdir -p "$DEST"
    SYSJ="$JDIR/system.journal"
    if [[ -f "$SYSJ" ]] && (( $(stat -c %s "$SYSJ") <= 64*1024*1024 )); then
        cp -a "$SYSJ" "$DEST/"
    fi
    for uj in $(ls -S "$JDIR"user-1000.journal 2>/dev/null; ls -t "$JDIR"user-1000@*.journal 2>/dev/null | head -1); do
        cp -a "$uj" "$DEST/"
    done
fi
# dpkg 数据库（真实安装清单）
mkdir -p "$MNT/var/lib/dpkg"
for f in status status-old; do
    [[ -f "/var/lib/dpkg/$f" ]] && cp -a "/var/lib/dpkg/$f" "$MNT/var/lib/dpkg/"
done

# --- /usr/bin 常用二进制 + merged-usr 符号链接 ---
mkdir -p "$MNT/usr/bin"
for b in bash dash ls cat cp mv ps top ss curl nano git awk grep sed; do
    [[ -f "/usr/bin/$b" ]] && cp -a "/usr/bin/$b" "$MNT/usr/bin/"
done
ln -sfn usr/bin "$MNT/bin"
ln -sfn usr/bin "$MNT/sbin"
ln -sfn "lib/x86_64-linux-gnu" "$MNT/lib64"

# --- /root：真实 root shell 历史 ---
mkdir -p "$MNT/root"
cat > "$MNT/root/.bash_history" <<'HIST'
losetup --find --partscan --show /images/ubuntu_real.img
mkfs.vfat -F 32 /dev/loop0p1
mkfs.ext4 -F /dev/loop0p2
mount /dev/loop0p2 /mnt
apt-get update
apt-get install -y dosfstools
systemctl restart ssh
tail -f /var/log/auth.log
last -f /var/log/wtmp
crontab -l
HIST
chmod 600 "$MNT/root/.bash_history"

# --- /home/ymj68520：真实用户痕迹（不含私钥） ---
HM="$MNT/home/ymj68520"
mkdir -p "$HM"
for f in .bashrc .zshrc .profile .gitconfig .bash_history .zsh_history; do
    [[ -f "/home/ymj68520/$f" ]] && cp -a "/home/ymj68520/$f" "$HM/"
done
mkdir -p "$HM/.ssh"
for f in authorized_keys config known_hosts; do
    [[ -f "/home/ymj68520/.ssh/$f" ]] && cp -a "/home/ymj68520/.ssh/$f" "$HM/.ssh/"
done
# 真实文档：中文路径 + PDF（MarkItDown/LLM 路径）
mkdir -p "$HM/文档" "$HM/图片/截图" "$HM/projects/TraceLens" "$HM/Documents"
[[ -f "/home/ymj68520/文档/电子科技大学-软件开发-王毅豪.pdf" ]] && \
    cp -a "/home/ymj68520/文档/电子科技大学-软件开发-王毅豪.pdf" "$HM/文档/"
for img in "/home/ymj68520/图片/CANKAO.jpg" "/home/ymj68520/图片/wallhaven-1qqok3.jpg" \
           "/home/ymj68520/图片/截图/截图 2026-01-11 18-52-38.png"; do
    [[ -f "$img" ]] && cp -a "$img" "$HM/图片/"
done
# 项目源码样本
for src in README.md LICENSE CHANGES.md CMakeLists.txt; do
    [[ -f "/home/ymj68520/projects/Forensics/TraceLens/$src" ]] && \
        cp -a "/home/ymj68520/projects/Forensics/TraceLens/$src" "$HM/projects/TraceLens/"
done
# 真实结构 SQLite（聊天记录库）
[[ -f "$(dirname "$OUT")/../tests/wechat_dataset_android.db" ]] && \
    cp -a "$(dirname "$OUT")/../tests/wechat_dataset_android.db" "$HM/Documents/wechat_backup.db"

# --- 空目录（真实挂载点） ---
mkdir -p "$MNT/proc" "$MNT/sys" "$MNT/dev" "$MNT/run" "$MNT/media" "$MNT/mnt" "$MNT/opt" "$MNT/srv" "$MNT/var/crash" "$MNT/tmp"
chmod 1777 "$MNT/tmp"

echo "==> [6/7] 模拟已删除文件（供雕刻/恢复测试）"
mkdir -p "$HM/Documents/old_backup"
printf '银行卡密码备忘:\n- 工行 6222 0210 0123 4567 密码 884211\n- 支付宝 138 0013 8000\n' > "$HM/Documents/old_backup/passwords_backup.txt"
cp -a "/home/ymj68520/图片/CANKAO.jpg" "$HM/Documents/old_backup/" 2>/dev/null || \
    printf 'FAKEJPG' > "$HM/Documents/old_backup/backup.jpg"
sync
rm -rf "$HM/Documents/old_backup"

echo "==> [7/7] 卸载并清理"
sync
umount "$MNT/boot/efi"
umount "$MNT"
losetup -d "$LOOP"
LOOP=""

chown "${SUDO_USER:-root}:${SUDO_USER:-root}" "$OUT" 2>/dev/null || true
echo "==> 完成: $OUT"
echo "    表观大小: $(ls -lh "$OUT" | awk '{print $5}')  实际占用: $(du -h "$OUT" | awk '{print $1}')"
echo "    分区布局:"
sfdisk -l "$OUT" 2>/dev/null | tail -4
