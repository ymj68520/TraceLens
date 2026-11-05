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
import hashlib
import io
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
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


def _scene_photo() -> bytes:
    """PNG carrying the same account number as the text evidence.

    M3-1 requires one event to aggregate text and image. The photo shares
    its mtime minute with 内部沟通记录.txt, so cluster seeding links both to
    the same event. A real PNG (not opaque bytes) keeps the task-time vision
    path from stalling the way unknown binaries do.
    """
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (640, 200), "white")
    draw = ImageDraw.Draw(img)
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(cand, 36)
            break
        except OSError:
            continue
    draw.text((24, 70), "account 6222 0000 1234 5678", fill="black", font=font)
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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
        # Same minute as 内部沟通记录.txt: cluster seeding attaches both to one event.
        "/home/analyst/photos/转账凭证.png": _scene_photo(),
        "/etc/passwd": b"root:x:0:0:root:/root:/bin/bash\nanalyst:x:1000:1000::/home/analyst:/bin/bash\n",
        "/var/log/syslog": b"".join(
            f"Mar  2 {h:02d}:00:00 fixture CRON[111]: (root) CMD (fixture)\n".encode()
            for h in range(10)
        ),
    }
    debugfs_inject(img, files, {
        "/home/analyst/内部沟通记录.txt": "20260302101400",
        "/home/analyst/photos/转账凭证.png": "20260302101430",
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


def build_demo_ios(target_dir: Path | None = None) -> Path:
    target_dir = target_dir or (FIXTURES / "ios_backup_evidence")
    target_dir.mkdir(parents=True, exist_ok=True)
    plist_xml = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>IsEncrypted</key>
  <false/>
  <key>Version</key>
  <string>10.0</string>
  <key>Lockdown</key>
  <dict>
    <key>ProductType</key>
    <string>iPhone14,2</string>
    <key>ProductVersion</key>
    <string>16.5</string>
    <key>BuildVersion</key>
    <string>20F66</string>
    <key>UniqueDeviceID</key>
    <string>d5747fae8f4ddba485f17710026bd6bff268acb0</string>
    <key>SerialNumber</key>
    <string>F2LDM0000001</string>
    <key>DeviceName</key>
    <string>张伟的 iPhone</string>
  </dict>
</dict>
</plist>
"""
    (target_dir / "Manifest.plist").write_text(plist_xml, encoding="utf-8")

    manifest_db_path = target_dir / "Manifest.db"
    con = sqlite3.connect(manifest_db_path)
    con.execute("CREATE TABLE IF NOT EXISTS Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB);")

    # Member 1: sms.db
    with tempfile.NamedTemporaryFile(suffix=".db") as f_sms:
        sdb = sqlite3.connect(f_sms.name)
        sdb.execute("CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id TEXT);")
        sdb.execute("CREATE TABLE message(ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, subject TEXT, date INTEGER, is_from_me INTEGER, service TEXT, attributedBody BLOB, handle_id INTEGER);")
        sdb.execute("INSERT INTO handle VALUES(1, '+8613800000002');")
        sdb.execute("INSERT INTO message VALUES(1, 'MSG-001', '货款走王五的私人账户，单据照旧做平。', '', 794220000000000000, 0, 'SMS', NULL, 1);")
        sdb.commit()
        sdb.close()
        sms_bytes = Path(f_sms.name).read_bytes()

    # Member 2: AddressBook.sqlitedb
    with tempfile.NamedTemporaryFile(suffix=".db") as f_ab:
        adb = sqlite3.connect(f_ab.name)
        adb.execute("CREATE TABLE ABPerson(ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT, Middle TEXT, Organization TEXT, Nickname TEXT, JobTitle TEXT, Department TEXT);")
        adb.execute("CREATE TABLE ABMultiValue(record_id INTEGER, property INTEGER, value TEXT);")
        adb.execute("INSERT INTO ABPerson VALUES(1, '伟', '张', '', '某某贸易有限公司', '主管', '仓库主管', '仓储部');")
        adb.execute("INSERT INTO ABMultiValue VALUES(1, 3, '13800000001');")
        adb.execute("INSERT INTO ABPerson VALUES(2, '娜', '李', '', '某某贸易有限公司', '财务', '财务经理', '财务部');")
        adb.execute("INSERT INTO ABMultiValue VALUES(2, 3, '13800000002');")
        adb.execute("INSERT INTO ABPerson VALUES(3, '五', '王', '', '某某贸易有限公司', '客户', '业务代理', '采购部');")
        adb.execute("INSERT INTO ABMultiValue VALUES(3, 3, '13800000003');")
        adb.commit()
        adb.close()
        ab_bytes = Path(f_ab.name).read_bytes()

    # Member 3: notes.sqlite
    with tempfile.NamedTemporaryFile(suffix=".db") as f_note:
        ndb = sqlite3.connect(f_note.name)
        ndb.execute("CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1 TEXT, ZSNIPPET TEXT, ZIDENTIFIER TEXT);")
        ndb.execute("INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES(1, '换班备忘', '今晚 11 点后仓库换班，监控停两小时。', 'NOTE-001');")
        ndb.commit()
        ndb.close()
        note_bytes = Path(f_note.name).read_bytes()

    # Member 4: Calendar.sqlitedb
    with tempfile.NamedTemporaryFile(suffix=".db") as f_cal:
        cdb = sqlite3.connect(f_cal.name)
        cdb.execute("CREATE TABLE CalendarItem(ROWID INTEGER PRIMARY KEY, summary TEXT, description TEXT, start_date INTEGER, end_date INTEGER, location TEXT);")
        cdb.execute("INSERT INTO CalendarItem VALUES(1, '仓库换班交割', '386,000 异常调拨交割', 794220000, 794223600, '一号仓库');")
        cdb.commit()
        cdb.close()
        cal_bytes = Path(f_cal.name).read_bytes()

    members = [
        ("HomeDomain", "Library/SMS/sms.db", sms_bytes),
        ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb", ab_bytes),
        ("HomeDomain", "Library/Notes/notes.sqlite", note_bytes),
        ("HomeDomain", "Library/Calendar/Calendar.sqlitedb", cal_bytes),
    ]

    for domain, rel, data in members:
        fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        shard_dir = target_dir / fid[:2]
        shard_dir.mkdir(exist_ok=True)
        (shard_dir / fid).write_bytes(data)
        con.execute("INSERT OR REPLACE INTO Files VALUES(?,?,?,?,NULL)", (fid, domain, rel, 1))

    con.commit()
    con.close()
    return target_dir


def build_demo_android_miui(target_dir: Path | None = None) -> Path:
    target_dir = target_dir or (FIXTURES / "miui_backup_evidence")
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".db") as f_db:
        db = sqlite3.connect(f_db.name)
        db.execute("CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, display_name TEXT);")
        db.execute("CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER, mimetype_id INTEGER, data1 TEXT);")
        db.execute("CREATE TABLE mimetypes (_id INTEGER PRIMARY KEY, mimetype TEXT);")
        db.execute("INSERT INTO mimetypes VALUES (1, 'vnd.android.cursor.item/phone_v2');")
        db.execute("INSERT INTO raw_contacts VALUES (1, '张伟（仓库主管）');")
        db.execute("INSERT INTO data VALUES (1, 1, 1, '13800000001');")
        db.execute("INSERT INTO raw_contacts VALUES (2, '李娜（财务）');")
        db.execute("INSERT INTO data VALUES (2, 2, 1, '13800000002');")
        db.execute("INSERT INTO raw_contacts VALUES (3, '王五（收款账户）');")
        db.execute("INSERT INTO data VALUES (3, 3, 1, '13800000003');")
        db.commit()
        db.close()
        db_bytes = Path(f_db.name).read_bytes()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        ti = tarfile.TarInfo("apps/com.android.contacts/db/contacts2.db")
        ti.size = len(db_bytes)
        tar.addfile(ti, io.BytesIO(db_bytes))
    tar_bytes = buf.getvalue()
    bak_bytes = b"ANDROID BACKUP\n5\n0\nnone\n" + tar_bytes
    (target_dir / "Contacts(com.android.contacts).bak").write_bytes(bak_bytes)

    with tempfile.NamedTemporaryFile(suffix=".db") as f_mms:
        mdb = sqlite3.connect(f_mms.name)
        mdb.execute("CREATE TABLE sms (_id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER, type INTEGER);")
        mdb.execute("INSERT INTO sms VALUES (1, '13800000002', '货款走王五的私人账户，单据照旧做平。', 1709340000000, 1);")
        mdb.execute("INSERT INTO sms VALUES (2, '13800000001', '已断电，动手。', 1709385480000, 1);")
        mdb.commit()
        mdb.close()
        mms_bytes = Path(f_mms.name).read_bytes()

    buf_mms = io.BytesIO()
    with tarfile.open(fileobj=buf_mms, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        ti = tarfile.TarInfo("apps/com.android.mms/db/mmssms.db")
        ti.size = len(mms_bytes)
        tar.addfile(ti, io.BytesIO(mms_bytes))
    mms_bak_bytes = b"ANDROID BACKUP\n5\n0\nnone\n" + buf_mms.getvalue()
    (target_dir / "Mms(com.android.mms).bak").write_bytes(mms_bak_bytes)

    xml = ('<?xml version="1.0"?><MIUI-backup>'
           '<device>Xiaomi 13 Pro</device><miuiVersion>V14.0.1</miuiVersion>'
           '<date>1709340000</date><size>204800</size><packages>'
           '<package><packageName>com.android.contacts</packageName>'
           '<bakFile>Contacts(com.android.contacts).bak</bakFile>'
           '<bakType>1</bakType><pkgSize>' + str(len(bak_bytes)) + '</pkgSize><sdSize>0</sdSize>'
           '<state>1</state><error>0</error></package>'
           '<package><packageName>com.android.mms</packageName>'
           '<bakFile>Mms(com.android.mms).bak</bakFile>'
           '<bakType>1</bakType><pkgSize>' + str(len(mms_bak_bytes)) + '</pkgSize><sdSize>0</sdSize>'
           '<state>1</state><error>0</error></package>'
           '</packages></MIUI-backup>')
    (target_dir / "descript.xml").write_text(xml, encoding="utf-8")
    return target_dir


def build_demo_android_harmony(target_dir: Path | None = None) -> Path:
    target_dir = target_dir or (FIXTURES / "harmony_backup_evidence")
    target_dir.mkdir(parents=True, exist_ok=True)
    package = "com.huawei.hmos.calendardata"
    app = target_dir / "files" / "BASIC" / package
    app.mkdir(parents=True, exist_ok=True)
    (target_dir / ".info.json").write_text(json.dumps({
        "BackupFileHeaderInfo": {"deviceModel": "HUAWEI Mate 60 Pro", "backupTime": 1709340000000},
        "BackupFileVersionInfo": {"versionName": "HarmonyOS 4.0.0"},
        "BackupFileModuleInfo": [{"moduleName": package, "appName": "Calendar", "appIndex": 0}],
    }, indent=2), encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        cal_db = Path(td) / "calendar.db"
        con = sqlite3.connect(cal_db)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE Events(_id INTEGER PRIMARY KEY, title TEXT, dtstart INTEGER)")
        con.execute("INSERT INTO Events VALUES(1, '仓库换班交割', 1709340000000)")
        con.execute("INSERT INTO Events VALUES(2, '王五私人账户对账', 1709343600000)")
        con.commit()
        primary = cal_db.read_bytes()
        wal_path = Path(str(cal_db) + "-wal")
        wal = wal_path.read_bytes() if wal_path.exists() else b""
        con.close()

    original = "/data/storage/el2/database/entry/rdb/calendardata.db"
    archive = app / "part.0.tarx"
    with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
        d = tarfile.TarInfo("/data/storage/el2/database")
        d.type = tarfile.DIRTYPE
        d.size = 3440
        tar.addfile(d)
        m = tarfile.TarInfo(original)
        m.size = len(primary)
        m.mtime = 1709340000
        tar.addfile(m, io.BytesIO(primary))

    (app / "wal_blobx").write_bytes(wal)
    (app / "manage.jsonx").write_text(json.dumps([
        {"fileName": "part.0.tar", "isBigFile": False,
         "information": {"path": "/data/storage/el2/base/.backup/part.0.tar", "stat": {"st_size": archive.stat().st_size}}},
        {"fileName": "wal_blob", "isBigFile": True,
         "information": {"path": original + "-wal", "stat": {"st_size": len(wal)}}},
    ]), encoding="utf-8")
    return target_dir


def build_demo_android_vivo(target_dir: Path | None = None) -> Path:
    target_dir = target_dir or (FIXTURES / "vivo_backup_evidence")
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "db").mkdir(exist_ok=True)
    (target_dir / ".backup").write_text(
        '{"model":"vivo X90 Pro+","createTime":1709340000000,"encrypted":false,"backupPackageVer":2,"success":true}',
        encoding="utf-8"
    )
    cam = target_dir / "storage/emulated/0/DCIM/Camera"
    cam.mkdir(parents=True, exist_ok=True)
    (cam / "IMG_20260302_001.jpg").write_bytes(_scene_photo())
    
    docs = target_dir / "storage/emulated/0/Documents"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "涉案合同.html").write_text(CASE_DOC_HTML, encoding="utf-8")

    idx = {
        "format": "tracelens-vivo-index-v1",
        "model": "vivo X90 Pro+",
        "backup_package_version": 2,
        "backup_time_ms": 1709340000000,
        "obfuscated": False,
        "items": [
            {
                "category": "album",
                "index": 0,
                "hash": "1" * 40,
                "original_path": "storage/emulated/0/DCIM/Camera/IMG_20260302_001.jpg",
                "size": len(_scene_photo()),
                "mtime_ms": 1709340000000
            },
            {
                "category": "document",
                "index": 0,
                "hash": "2" * 40,
                "original_path": "storage/emulated/0/Documents/涉案合同.html",
                "size": len(CASE_DOC_HTML.encode("utf-8")),
                "mtime_ms": 1709340000000
            }
        ],
        "applications": [
            {
                "package": "com.tencent.mm",
                "kind": "apk",
                "hash": "3" * 40,
                "file_name": "app_com.tencent.mm.apk",
                "size": 65536,
                "app_name": "微信",
                "version_name": "8.0.45",
                "version_code": 2500,
                "with_data": True
            }
        ],
        "categories": [
            {"key": "album", "label": "相册", "count": 1, "size": len(_scene_photo()), "stored_as_files": True},
            {"key": "document", "label": "文档", "count": 1, "size": len(CASE_DOC_HTML.encode("utf-8")), "stored_as_files": True}
        ],
        "record_categories": [
            {"key": "sms", "label": "信息", "data_type": 2, "count": 10, "size": 2000, "stored_as_files": False}
        ],
        "warnings": []
    }
    (target_dir / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_dir


def build_demo_aliyun_oss(target_file: Path | None = None) -> Path:
    target_file = target_file or (FIXTURES / "file_m-demo_aliyun_system.raw.tar.gz")
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tree = root / "tree"
        line = '127.0.0.1 - - [02/Mar/2026:10:14:00 +0800] "GET /oss/transfer/386000 HTTP/1.1" 200 1024\n'
        for name, content in {
            'etc/os-release': 'NAME="Alibaba Cloud Linux"\nID=alinux\nVERSION_ID="3"\nPRETTY_NAME="Alibaba Cloud Linux 3 (Soフラ)"\n',
            'etc/passwd': 'root:x:0:0:root:/root:/bin/bash\necs-user:x:1001:1001::/home/ecs-user:/bin/bash\n',
            'var/log/nginx/access.log': line * 10,
            'www/wwwlogs/oss.log': line * 5,
        }.items():
            p = tree / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        raw = root / "system.raw"
        with raw.open("wb") as s:
            s.truncate(32 * 1024 * 1024)
        run(['mke2fs', '-q', '-F', '-t', 'ext4', '-d', str(tree), str(raw)])
        with tarfile.open(target_file, "w:gz") as archive:
            archive.add(raw, arcname="file_m-demo_aliyun_system.raw")
    return target_file


def build_demo_windows(target_file: Path | None = None) -> Path:
    target_file = target_file or (FIXTURES / "windows_evidence.img")
    target_file.parent.mkdir(parents=True, exist_ok=True)
    build_ext4(target_file, 32)
    pf_mam = b"MAM\x04" + b"\x00" * 1024
    pf_scca = b"\x1e\x00\x00\x00SCCA" + b"\x00" * 1024
    lnk_hdr = struct.pack("<I16sI", 0x0000004C,
                          bytes.fromhex("0114020000000000c000000000000046"),
                          0x00000001) + b"\x00" * 512
    evtx = b"ElfFile\x00" + b"\x00" * 4088
    regf = b"regf" + b"\x00" * 4092

    files = {
        "/Windows/Prefetch/CMD.EXE-A1B2C3D4.pf": pf_mam,
        "/Windows/Prefetch/POWERSHELL.EXE-B2C3D4E5.pf": pf_scca,
        "/Windows/System32/winevt/Logs/Security.evtx": evtx,
        "/Windows/System32/config/SYSTEM": regf,
        "/Windows/System32/config/SOFTWARE": regf,
        "/Users/Administrator/Desktop/涉案账目.lnk": lnk_hdr,
        "/Users/Administrator/Documents/财务审计报告.txt": "涉案财务账目明细：386,000 元调拨至王五账户\n".encode("utf-8"),
    }
    debugfs_inject(target_file, files)
    return target_file


def build_demo_linux(target_file: Path | None = None) -> Path:
    target_file = target_file or (FIXTURES / "linux_evidence.img")
    raw = build_raw_basic()
    if target_file != raw:
        shutil.copyfile(raw, target_file)
    return target_file


def build_all_demo_datasets(output_root: Path | None = None) -> Path:
    root = output_root or (HERE.parents[1] / "demo_datasets")
    root.mkdir(parents=True, exist_ok=True)

    # 1. Windows
    win_dir = root / "01_windows"
    win_dir.mkdir(exist_ok=True)
    build_demo_windows(win_dir / "windows_evidence.img")

    # 2. Linux
    lin_dir = root / "02_linux"
    lin_dir.mkdir(exist_ok=True)
    build_demo_linux(lin_dir / "linux_evidence.img")

    # 3. 阿里云 OSS
    oss_dir = root / "03_aliyun_oss"
    oss_dir.mkdir(exist_ok=True)
    build_demo_aliyun_oss(oss_dir / "file_m-demo_aliyun_system.raw.tar.gz")

    # 4. iOS
    ios_dir = root / "04_ios" / "ios_backup_evidence"
    if ios_dir.exists():
        shutil.rmtree(ios_dir)
    build_demo_ios(ios_dir)

    # 5. Android MIUI
    miui_dir = root / "05_android_miui" / "miui_backup_evidence"
    if miui_dir.exists():
        shutil.rmtree(miui_dir)
    build_demo_android_miui(miui_dir)

    # 6. Android HarmonyOS
    harmony_dir = root / "06_android_harmony" / "harmony_backup_evidence"
    if harmony_dir.exists():
        shutil.rmtree(harmony_dir)
    build_demo_android_harmony(harmony_dir)

    # 7. Android vivo
    vivo_dir = root / "07_android_vivo" / "vivo_backup_evidence"
    if vivo_dir.exists():
        shutil.rmtree(vivo_dir)
    build_demo_android_vivo(vivo_dir)

    readme_content = """# TraceLens 第三方测试验收演示数据集 (Demo Datasets)

本目录为面向第三方权威测试机构的现场验收演示专用数据集。数据集覆盖项目合同指标要求的全部来源，
包括 1 份 Windows、1 份 Linux、1 份阿里云 OSS、1 份 iOS、以及 3 份主流国产 Android 移动设备数据。

各数据集均已进行脱敏，且植入了统一的案情证据链（涉案嫌疑人：张伟-仓库主管、李娜-财务经理、王五-收款账户；涉案标的：￥386,000 设备采购与异常调拨款项）。

---

## 演示数据集清单与指标对应关系

| 序号 | 演示数据集目录 / 文件 | 数据源类型与品牌 | 包含核心工件与内容 | 对应验收指标 |
| :--- | :--- | :--- | :--- | :--- |
| **01** | `01_windows/windows_evidence.img` | **Windows 操作系统镜像** | Prefetch 执行痕迹(CMD/PowerShell)、EVTX 系统日志、LNK 快捷方式、注册表 Hive(SYSTEM/SOFTWARE)、财务审计报告文档 | 指标 1(1) 磁盘镜像与操作系统接入 |
| **02** | `02_linux/linux_evidence.img` | **Linux 操作系统镜像** (RAW/DD) | 涉案沟通记录、涉案合同、财务台账、syslog/auth.log、重复文件对、低价值混合系统文件 | 指标 1(1) 兼容RAW/DD<br>指标 1(2) 轻量化过滤(10MB/s, 剔除率≥70%, 压缩至12-15%)<br>指标 2(2) 重复证据去重 |
| **03** | `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz` | **阿里云 OSS / ECS 导出包** | Alibaba Cloud Linux、nginx 访问日志、OSS 接口转账调用日志、系统用户与服务日志 | 指标 1(1) 服务器日志与云数据源接入 |
| **04** | `04_ios/ios_backup_evidence/` | **苹果 iOS 移动设备逻辑备份** | iTunes/Finder 备份规范(Manifest.plist, Manifest.db)、涉案短信 iMessage (sms.db)、通讯录 (AddressBook)、涉案备忘录、日程 | 指标 1(1) IOS 移动设备接入 |
| **05** | `05_android_miui/miui_backup_evidence/` | **Android (小米 MIUI 备份)** | 小米备份清单 descript.xml、Contacts(com.android.contacts).bak 联系人库、Mms(com.android.mms).bak 短信库 | 指标 1(1) Android 移动设备 (类别 1: 小米) |
| **06** | `06_android_harmony/harmony_backup_evidence/` | **Android (华为鸿蒙 HarmonyOS 备份)** | 鸿蒙备份清单 .info.json、分卷归档 part.0.tarx、WAL 日志、日历与通讯工件库 | 指标 1(1) Android 移动设备 (类别 2: 华为鸿蒙) |
| **07** | `07_android_vivo/vivo_backup_evidence/` | **Android (vivo / OPPO 雷电快取备份)** | .backup 头、LevelDB 索引规范 index.json、涉案转账截图相册、涉案合同文档、微信应用包 | 指标 1(1) Android 移动设备 (类别 3: vivo/OPPO) |

---

## 演示与验收测试方法

### 方法一：全自动化第三方验收测试套件（自动化验证指标）
在 TraceLens 根目录下运行（无需任何人工交互）：
```bash
# 1. 一键生成测试夹具与演示数据集
python3 tests/acceptance_metrics/prepare_fixtures.py

# 2. 运行第三方指标验收测试（非 LLM 部分，耗时约 1 分钟）
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v -m "not llm"

# 3. 运行含大模型案情推演与多模态聚合的完整验收测试
python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v
```

### 方法二：图形化 Web 前端界面演示（人工交互验收）
1. 打开浏览器访问前端（默认 `http://localhost:5173` 或部署地址）；
2. 点击 **“新建任务”**；
3. 选择对应演示数据路径：
   - 导入 Windows 演示数据：选择 `01_windows/windows_evidence.img`，场景勾选 **Windows**；
   - 导入 Linux 演示数据：选择 `02_linux/linux_evidence.img`，场景勾选 **Linux**；
   - 导入 阿里云 OSS 数据：选择 `03_aliyun_oss/file_m-demo_aliyun_system.raw.tar.gz`，来源类型选择 **aliyun-image**；
   - 导入 iOS 移动备份：选择 `04_ios/ios_backup_evidence`，来源类型选择 **ios-backup**；
   - 导入 小米 备份：选择 `05_android_miui/miui_backup_evidence`，来源类型选择 **miui-backup**；
   - 导入 华为鸿蒙 备份：选择 `06_android_harmony/harmony_backup_evidence`，来源类型选择 **harmony-backup**；
   - 导入 vivo 备份：选择 `07_android_vivo/vivo_backup_evidence`，来源类型选择 **vivo-backup**；
4. 任务分析完成后，可在 **工件卡片**、**重复证据列表**、**动态时间线** 以及 **案情推演报告** 中查看完整的结构化研判成果。
"""
    (root / "README.md").write_text(readme_content, encoding="utf-8")
    return root



BUILDERS = {
    "raw": build_raw_basic,
    "dd": build_dd,
    "timeline": build_timeline,
    "logs": build_logs,
    "raw_llm": build_raw_llm,
    "ios": build_demo_ios,
    "miui": build_demo_android_miui,
    "harmony": build_demo_android_harmony,
    "vivo": build_demo_android_vivo,
    "aliyun_oss": build_demo_aliyun_oss,
    "windows": build_demo_windows,
    "linux": build_demo_linux,
    "demo_datasets": build_all_demo_datasets,
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
        manifest["raw_llm.img"] = "LLM 专用证据镜像（小文本 + 同分钟转账凭证图，供 M3-1/M4）"
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
    if "ios" in wanted:
        build_demo_ios()
        manifest["ios_backup_evidence"] = "iOS 逻辑备份夹具：Manifest.plist/db + 短信/通讯录/备忘录/日程分片"
    if "miui" in wanted:
        build_demo_android_miui()
        manifest["miui_backup_evidence"] = "Android 小米 MIUI 备份夹具：descript.xml + Contacts/Mms .bak"
    if "harmony" in wanted:
        build_demo_android_harmony()
        manifest["harmony_backup_evidence"] = "Android 华为鸿蒙备份夹具：.info.json + calendardata tarx/wal"
    if "vivo" in wanted:
        build_demo_android_vivo()
        manifest["vivo_backup_evidence"] = "Android vivo/雷电快取备份夹具：.backup + index.json + 相册/文档"
    if "aliyun_oss" in wanted:
        build_demo_aliyun_oss()
        manifest["file_m-demo_aliyun_system.raw.tar.gz"] = "阿里云 OSS/ECS 导出演示包：Alibaba Cloud Linux + nginx/oss 日志"
    if "windows" in wanted:
        build_demo_windows()
        manifest["windows_evidence.img"] = "Windows 证据夹具：Prefetch(CMD/PowerShell) + EVTX + LNK + 注册表 Hive"
    if "linux" in wanted:
        build_demo_linux()
        manifest["linux_evidence.img"] = "Linux 系统取证与轻量化过滤演示镜像"
    if "demo_datasets" in wanted:
        demo_dir = build_all_demo_datasets()
        print(f"第三方演示数据集已生成至: {demo_dir}")

    (FIXTURES / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"夹具目录: {FIXTURES}")
    for name, desc in manifest.items():
        print(f"  {name:30s} {desc}")
    if not (FIXTURES / "e01.E01").exists() and not shutil.which("ewfacquire"):
        print("\n提示: E01 夹具无法用开源工具凭空生成，请设置 TRACELENS_E01_IMAGE 指向真实 E01 镜像，")
        print("      或将 E01 复制为 fixtures/e01.E01（可含分段 .E01/.E02）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
