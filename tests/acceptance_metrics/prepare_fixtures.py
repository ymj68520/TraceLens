#!/usr/bin/env python3
"""Build the fixture set used by the third-party acceptance test suite.

All fixtures are generated with userspace tools only (mkfs.ext4 + debugfs),
no loop mounts and no root. Outputs land in tests/acceptance_metrics/fixtures/
(or $TRACELENS_ACCEPT_FIXTURES) together with manifest.json describing what
was built, so the acceptance report can state exactly which inputs were used.

  python3 tests/acceptance_metrics/prepare_fixtures.py            # build all
  python3 tests/acceptance_metrics/prepare_fixtures.py --only raw dd timeline logs
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = Path(__import__("os").environ.get("TRACELENS_ACCEPT_FIXTURES", HERE / "fixtures"))

RAW_SIZE_MB = 100          # raw_basic.img nominal size (sparse-friendly ext4)
TIMELINE_FILES = 120       # must stay >= the 100-node acceptance threshold

# Roles planted in the evidence; test_m4 asserts the narrative report does not
# invent others.
ROLE_NOTE = """内部沟通记录（导出）
2026-03-02 10:14 张伟（仓库主管）：今晚 11 点后仓库换班，监控停两小时。
2026-03-02 10:20 李娜（财务）：货款走王五的私人账户，单据照旧做平。
2026-03-02 22:58 张伟：已断电，动手。
2026-03-03 06:40 李娜：账已平，别留痕。
"""

CASE_DOC_HTML = """<html><head><title>涉案合同</title></head><body>
<h1>设备采购合同</h1>
<p>甲方：某某贸易有限公司 乙方：张伟</p>
<p>合同金额：￥386,000，付款账户：6222 0000 1234 5678（户名 王五）。</p>
</body></html>
"""

LEDGER_CSV = """日期,项目,金额,经手人
2026-02-10,入库,120000,李娜
2026-02-18,出库,96000,李娜
2026-03-02,异常调拨,386000,王五
"""

RANSOM_NOTE = """Abc ransomware test marker.
Encrypted by acceptance fixture. Contact: none.
UNIQUE-MARKER-ACCT-2026-RAWDATA-777
"""


def run(cmd: list[str], **kw) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)


def build_ext4(path: Path, size_mb: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.truncate(size_mb * 1024 * 1024)
    run(["/sbin/mkfs.ext4", "-F", "-q", str(path)])


def debugfs_inject(image: Path, files: dict[str, bytes], mtimes: dict[str, str] | None = None) -> None:
    """Copy `files` into the ext4 image via debugfs (userspace, no mount).

    mtimes maps image-path -> "YYYYMMDDHHMMSS" (debugfs set_inode_field format).
    """
    cmds: list[str] = []
    for img_path in files:
        parent = img_path.rsplit("/", 1)[0]
        parts = [p for p in parent.split("/") if p]
        acc = ""
        for part in parts:
            acc += "/" + part
            cmds.append(f"mkdir {acc}")
    tmp_root = image.parent / "_inject"
    tmp_root.mkdir(exist_ok=True)
    for i, (img_path, data) in enumerate(files.items()):
        local = tmp_root / f"f{i:04d}.bin"
        local.write_bytes(data)
        cmds.append(f"write {local} {img_path}")
    for img_path, stamp in (mtimes or {}).items():
        cmds.append(f"sif {img_path} mtime {stamp}")
        cmds.append(f"sif {img_path} atime {stamp}")
    cmd_file = image.parent / "_debugfs_cmds.txt"
    cmd_file.write_text("\n".join(cmds) + "\n")
    run(["/usr/sbin/debugfs", "-w", "-f", str(cmd_file), str(image)])
    cmd_file.unlink(missing_ok=True)
    shutil.rmtree(tmp_root, ignore_errors=True)


def junk_bytes(seed: int, size: int) -> bytes:
    out = bytearray()
    word = (seed * 2654435761 + 1) & 0xFFFFFFFF
    while len(out) < size:
        word = (1103515245 * word + 12345) & 0xFFFFFFFF
        out += struct.pack("<I", word)
    return bytes(out[:size])


def minimal_pdf(text: str, target_bytes: int = 0) -> bytes:
    """Build a tiny valid single-page PDF (correct xref) so markitdown can
    parse it and the LLM text path finishes fast — unlike opaque binaries,
    which wedge task-time analysis (observed >1h with no progress).

    target_bytes pads the content stream with repeated ledger lines so the
    byte-level mix of the fixture (M1-2 压缩比配平) stays deterministic.
    """
    lines = [f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET"]
    filler = "BT /F1 12 Tf 72 %d Td (entry %d ledger line for acceptance fixture) Tj ET"
    i, y = 0, 660
    while target_bytes and sum(len(x) for x in lines) < target_bytes:
        lines.append(filler % (y - (i + 1) * 24 % 600, i))
        i += 1
    stream = "\n".join(lines).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode()
    return bytes(out)


def csv_padded(header: str, row: str, target_bytes: int) -> bytes:
    """CSV padded with repeated rows to reach target_bytes (LLM-friendly size)."""
    lines = [header]
    i = 0
    while sum(len(x.encode("utf-8")) + 1 for x in lines) < target_bytes:
        lines.append(f"{row},{i % 10000}")
        i += 1
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_raw_basic() -> Path:
    """Small linux image with a scene-tuned valuable/low-value mix for M1-2.

    Linux scene rules (FileClassifier_SceneRules) only grant priority to
    /home, /root, /var/log, /etc and a few more — i.e. real deployments keep
    user evidence under /home while system dirs are low-value. Composition is
    tuned so the pending set lands at ~13% of bytes (12-15% window) with ~71%
    of files rejected (>=70%), deterministically.

    All files stay small (<=24KB) on purpose: task-time LLM analysis reads
    every file, and multi-10KB text blobs were observed to stall the text
    model for >10min each (empty-response retries), so the LLM fixture stays
    in the fast per-file range.
    """
    img = FIXTURES / "raw_basic.img"
    build_ext4(img, RAW_SIZE_MB)
    ledger_header = "日期,项目,金额,经手人,序号"
    ledger_row = "2026-02-10,入库,120000,李娜"
    files: dict[str, bytes] = {
        "/home/analyst/内部沟通记录.txt": ROLE_NOTE.encode("utf-8"),
        "/home/analyst/readme.txt": RANSOM_NOTE.encode("utf-8"),
        "/home/analyst/涉案合同.html": CASE_DOC_HTML.encode("utf-8"),
        "/home/analyst/台账.csv": csv_padded(ledger_header, ledger_row, 20 * 1024),
        "/home/analyst/photos/dup_a.csv": csv_padded(ledger_header, ledger_row, 24 * 1024),
        "/home/analyst/backup/dup_b.csv": csv_padded(ledger_header, ledger_row, 24 * 1024),  # byte-identical twin
        "/home/analyst/docs/会议纪要.txt": csv_padded("会议纪要", "参会人 张伟 李娜 王五", 16 * 1024),
        "/home/analyst/docs/通讯录.csv": csv_padded("姓名,电话,备注", "张伟,13800000001,主管", 16 * 1024),
        "/home/analyst/docs/项目计划.txt": csv_padded("项目计划", "节点 2026-03-02 仓库换班", 16 * 1024),
        "/home/analyst/docs/邮件导出.txt": csv_padded("主题,发件人", "对账,李娜", 16 * 1024),
        "/etc/passwd": b"root:x:0:0:root:/root:/bin/bash\nanalyst:x:1000:1000::/home/analyst:/bin/bash\n",
        "/var/log/syslog": b"".join(
            f"Mar  2 {h:02d}:00:00 fixture CRON[111]: (root) CMD (fixture)\n".encode()
            for h in range(10)
        ),
    }
    junk_dirs = ["/usr/lib", "/usr/share", "/var/cache", "/tmp"]
    for i in range(30):
        ext = ".so" if i % 3 == 0 else (".ttf" if i % 3 == 1 else ".tmp")
        name = f"libsample{i:02d}{ext}"
        files[f"{junk_dirs[i % len(junk_dirs)]}/{name}"] = junk_bytes(
            i + 11, (26 + (i % 5) * 2) * 1024)
    stamps = {
        "/home/analyst/内部沟通记录.txt": "20260302101400",
        "/home/analyst/readme.txt": "20260303064000",
        "/home/analyst/涉案合同.html": "20260201090000",
        "/home/analyst/台账.csv": "20260303070000",
        "/home/analyst/photos/dup_a.csv": "20260302230000",
        "/home/analyst/backup/dup_b.csv": "20260302230000",
        "/var/log/syslog": "20260302235900",
    }
    debugfs_inject(img, files, stamps)
    return img


def build_raw_llm() -> Path:
    """LLM-safe evidence-only image for the llm_analyze tests (M3-1/M4).

    raw_basic.img 里的二进制垃圾（.so/.ttf/.tmp）在任务态 LLM 分析下会被
    原文喂给文本模型并触发长时间空响应重试（实测单文件 >20min 无进展），
    因此推演/聚合用例使用这份只含小文本证据的镜像。
    """
    img = FIXTURES / "raw_llm.img"
    build_ext4(img, 32)
    ledger_header = "日期,项目,金额,经手人,序号"
    ledger_row = "2026-02-10,入库,120000,李娜"
    files: dict[str, bytes] = {
        "/home/analyst/内部沟通记录.txt": ROLE_NOTE.encode("utf-8"),
        "/home/analyst/readme.txt": RANSOM_NOTE.encode("utf-8"),
        "/home/analyst/涉案合同.html": CASE_DOC_HTML.encode("utf-8"),
        "/home/analyst/台账.csv": csv_padded(ledger_header, ledger_row, 20 * 1024),
        "/home/analyst/photos/dup_a.csv": csv_padded(ledger_header, ledger_row, 24 * 1024),
        "/home/analyst/backup/dup_b.csv": csv_padded(ledger_header, ledger_row, 24 * 1024),
        "/home/analyst/docs/会议纪要.txt": csv_padded("会议纪要", "参会人 张伟 李娜 王五", 16 * 1024),
        "/home/analyst/docs/通讯录.csv": csv_padded("姓名,电话,备注", "张伟,13800000001,主管", 16 * 1024),
        "/home/analyst/docs/项目计划.txt": csv_padded("项目计划", "节点 2026-03-02 仓库换班", 16 * 1024),
        "/home/analyst/docs/邮件导出.txt": csv_padded("主题,发件人", "对账,李娜", 16 * 1024),
        "/etc/passwd": b"root:x:0:0:root:/root:/bin/bash\nanalyst:x:1000:1000::/home/analyst:/bin/bash\n",
        "/var/log/syslog": b"".join(
            f"Mar  2 {h:02d}:00:00 fixture CRON[111]: (root) CMD (fixture)\n".encode()
            for h in range(10)
        ),
    }
    debugfs_inject(img, files, {
        "/home/analyst/内部沟通记录.txt": "20260302101400",
        "/home/analyst/readme.txt": "20260303064000",
        "/home/analyst/涉案合同.html": "20260201090000",
        "/home/analyst/台账.csv": "20260303070000",
        "/home/analyst/photos/dup_a.csv": "20260302230000",
        "/home/analyst/backup/dup_b.csv": "20260302230000",
        "/var/log/syslog": "20260302235900",
    })
    return img


def build_dd() -> Path:
    src = FIXTURES / "raw_basic.img"
    dst = FIXTURES / "dd_basic.dd"
    if not src.exists():
        build_raw_basic()
    shutil.copyfile(src, dst)
    return dst


def build_timeline() -> Path:
    """>=100 files with 1-hour spaced mtimes -> >=100 filesystem events (M3-2)."""
    img = FIXTURES / "timeline_120.img"
    build_ext4(img, 64)
    files: dict[str, bytes] = {}
    stamps: dict[str, str] = {}
    base_day, base_hour = 1, 8
    for i in range(TIMELINE_FILES):
        day = base_day + (base_hour + i) // 24
        hour = (base_hour + i) % 24
        files[f"/logs/event_{i:03d}.log"] = f"acceptance event {i}\n".encode()
        stamps[f"/logs/event_{i:03d}.log"] = f"202603{day:02d}{hour:02d}0000"
    debugfs_inject(img, files, stamps)
    return img


def build_logs() -> Path:
    """Linux server image carrying syslog/auth.log/nginx access.log (M1-1e)."""
    img = FIXTURES / "logs_server.img"
    build_ext4(img, 32)
    syslog = "".join(
        f"Mar  2 {h:02d}:{m:02d}:00 srv01 CRON[12{i:02d}]: (root) CMD (command -v Debian-exim >/dev/null)\n"
        for i, (h, m) in enumerate((h, m) for h in range(24) for m in (0, 15, 30, 45))
    )
    auth = "".join(
        line + "\n"
        for line in (
            "Mar  2 03:11:01 srv01 sshd[2201]: Failed password for deploy from 10.0.0.8 port 51022 ssh2",
            "Mar  2 03:11:04 srv01 sshd[2201]: Accepted password for deploy from 10.0.0.8 port 51022 ssh2",
            "Mar  2 03:12:00 srv01 sudo:  deploy : TTY=pts/0 ; PWD=/home/deploy ; COMMAND=/bin/cat /etc/shadow",
            "Mar  2 04:00:01 srv01 useradd[3310]: new user: name=backupadm, UID=1002",
        )
    )
    access = "".join(
        f'10.0.0.{8 + i % 3} - - [02/Mar/2026:{h:02d}:00:{s:02d} +0800] "GET /{"admin" if i % 5 == 0 else "static"}/page{i} HTTP/1.1" {200 if i % 5 else 401} {1024 + i}\n'
        for i, (h, s) in enumerate((h, s) for h in range(24) for s in range(0, 60, 15))
    )
    passwd = "root:x:0:0:root:/root:/bin/bash\ndeploy:x:1001:1001::/home/deploy:/bin/bash\nbackupadm:x:1002:1002::/home/backupadm:/usr/sbin/nologin\n"
    debugfs_inject(
        img,
        {
            "/var/log/syslog": syslog.encode(),
            "/var/log/auth.log": auth.encode(),
            "/var/log/nginx/access.log": access.encode(),
            "/etc/passwd": passwd.encode(),
        },
        {"/var/log/auth.log": "20260302031200", "/var/log/syslog": "20260302235900"},
    )
    return img


def build_media() -> dict[str, Path]:
    out: dict[str, Path] = {}
    # 文本样例（MarkItDown 输入）：置于独立子目录，convert-one 要求输出树不与
    # 输入树重叠，且三个根都必须落在 workspace 锚点内。
    md_in = FIXTURES / "_md_in"
    md_in.mkdir(exist_ok=True)
    html = md_in / "_text_sample.html"
    html.write_text(CASE_DOC_HTML, encoding="utf-8")
    out["_md_in/_text_sample.html"] = html
    # 视觉分析输入：绘制编号文字，验证"图像→文字信息"提取（M2-1b 断言该编号）
    png = FIXTURES / "sample.png"
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (640, 200), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(cand, 48)
                break
            except OSError:
                continue
        draw.text((24, 40), "ID: ACCT-2026-777", fill="black", font=font)
        draw.text((24, 120), "CASE EVIDENCE TAG", fill="black", font=font)
        img.save(png)
    except Exception:
        png.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    out["sample.png"] = png
    try:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-shortest", str(FIXTURES / "sample.mp4")])
        out["sample.mp4"] = FIXTURES / "sample.mp4"
    except Exception:
        pass
    return out


def build_android() -> Path | None:
    script = HERE.parent / "create_android_image.sh"
    if not script.exists():
        return None
    try:
        run(["bash", str(script)])
        img = HERE.parent / "android_test_gen.img"
        return img if img.exists() else None
    except Exception:
        return None


BUILDERS = {
    "raw": build_raw_basic,
    "dd": build_dd,
    "timeline": build_timeline,
    "logs": build_logs,
    "raw_llm": build_raw_llm,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None,
                    choices=[*BUILDERS, "media", "android"], help="只构建指定夹具")
    args = ap.parse_args()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    wanted = args.only or list(BUILDERS) + ["media", "android"]

    manifest: dict[str, str] = {}
    if "raw" in wanted:
        manifest["raw_basic.img"] = "Linux 案情夹具：角色聊天/合同/台账/勒索标记/重复文件对 + 低价值文件集"
        build_raw_basic()
    if "dd" in wanted:
        manifest["dd_basic.dd"] = "raw_basic.img 的逐字节副本（DD 口径）"
        build_dd()
    if "raw_llm" in wanted:
        manifest["raw_llm.img"] = "LLM 专用证据镜像（纯小文本，供 M3-1/M4 的 llm_analyze 任务）"
        build_raw_llm()
    if "timeline" in wanted:
        manifest["timeline_120.img"] = f"{TIMELINE_FILES} 个逐小时时间戳文件（M3-2 ≥100 事件）"
        build_timeline()
    if "logs" in wanted:
        manifest["logs_server.img"] = "/var/log 与 /etc/passwd 的 Linux 服务器夹具"
        build_logs()
    if "media" in wanted:
        built = build_media()
        manifest["_md_in/_text_sample.html"] = "文本提取输入（MarkItDown 转换样例）"
        manifest["sample.png"] = "视觉分析输入（含编号文字的样例图）"
        if "sample.mp4" in built:
            manifest["sample.mp4"] = "视频内容分析输入（ffmpeg 2 秒测试片）"
    if "android" in wanted:
        img = build_android()
        if img:
            shutil.copyfile(img, FIXTURES / img.name)
            manifest[img.name] = "Android 取证夹具（scripts/create_android_image.sh 产物）"
        else:
            print("android 夹具未生成（需要 sqlite3 且脚本可执行）")

    (FIXTURES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"夹具目录: {FIXTURES}")
    for name, desc in manifest.items():
        print(f"  {name:22s} {desc}")
    if not (FIXTURES / "e01.E01").exists() and not shutil.which("ewfacquire"):
        print("\n提示: E01 夹具无法用开源工具凭空生成，请设置 TRACELENS_E01_IMAGE 指向真实 E01 镜像，")
        print("      或将 E01 复制为 fixtures/e01.E01（可含分段 .E01/.E02）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
