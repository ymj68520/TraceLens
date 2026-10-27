"""Synthetic exported-image fixture, including non-block-aligned directories."""
import importlib.util
from pathlib import Path
import sqlite3
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('xiaomi_reader_fixture', ROOT / 'python_service/httpserver/services/xiaomi_image.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def varint(value):
    out = bytearray()
    while value > 127: out.append((value & 127) | 128); value >>= 7
    out.append(value)
    return bytes(out)


def field(number, value):
    if isinstance(value, str): value = value.encode()
    if isinstance(value, int): return varint(number << 3) + varint(value)
    return varint(number << 3 | 2) + varint(len(value)) + value


def build(root):
    tree = root / 'tree'
    def put(path, value):
        p = tree / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value); return p
    def database(path, sql, wal=False):
        p = put(path, b'')
        con = sqlite3.connect(p)
        if wal: con.execute('PRAGMA journal_mode=WAL')
        con.executescript(sql); con.commit()
        primary = p.read_bytes()
        sidecar = Path(str(p) + '-wal').read_bytes() if wal else None
        con.close(); p.write_bytes(primary)
        if sidecar: Path(str(p) + '-wal').write_bytes(sidecar)
    put('DMF/fixture.dmf', b'unsupported-DMF' + b'x' * 20000)
    put('storage/emulated/0/DCIM/fixture.txt', '中文共享存储样本'.encode())
    put('data/com.miui.notes/miui_att/' + 'a' * 40, b'attachment-fixture')
    note = field(2, 'note-1') + field(5, 1700000000000) + field(6, 1700000001000) + field(8, '合成便签内容') + field(9, field(4, 'a' * 40))
    put('data/com.miui.notes/miui_bak/_tmp_bak', field(6, field(2, note)))
    database('data/com.android.providers.contacts/databases/contacts2.db', '''
        CREATE TABLE contacts(_id INTEGER PRIMARY KEY,name_raw_contact_id INTEGER);
        CREATE TABLE raw_contacts(_id INTEGER PRIMARY KEY,contact_id INTEGER,display_name TEXT);
        CREATE TABLE data(_id INTEGER PRIMARY KEY,raw_contact_id INTEGER,mimetype_id INTEGER,data1 TEXT);
        CREATE TABLE mimetypes(_id INTEGER PRIMARY KEY,mimetype TEXT);
        INSERT INTO contacts VALUES(1,2);
        INSERT INTO raw_contacts VALUES(2,1,'合成联系人');
        INSERT INTO mimetypes VALUES(3,'vnd.android.cursor.item/phone_v2');
        INSERT INTO data VALUES(4,2,3,'synthetic-number');
        CREATE VIEW view_contacts AS SELECT * FROM contacts;
    ''')
    database('data/com.android.providers.contacts/databases/calllog.db', '''
        CREATE TABLE calls(_id INTEGER PRIMARY KEY,number TEXT,date INTEGER,duration INTEGER,type INTEGER);
        INSERT INTO calls VALUES(1,'synthetic-number',1700000000000,5,1);
    ''')
    database('data/com.android.providers.calendar/databases/calendar.db', '''
        CREATE TABLE Events(_id INTEGER PRIMARY KEY,title TEXT,dtstart INTEGER);
        INSERT INTO Events VALUES(1,'仅在 WAL 中的日历',1700000000000);
    ''', wal=True)
    image = root / '小米合成.bin'
    with image.open('wb') as f: f.truncate(64 << 20)
    subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-d', str(tree), str(image)], check=True)
    with reader.ExportImage(image) as source:
        inode_offset, raw = source.inode(2)
        runs = source.runs(raw)
        physical = runs[0][1]
        block = bytearray(source.read(physical, source.bs))
        at = 0
        while at < len(block):
            rec = struct.unpack_from('<H', block, at + 4)[0]
            if at + rec == len(block): break
            at += rec
        used = (8 + block[at + 6] + 3) & ~3
        struct.pack_into('<H', block, at + 4, used)
        block[at + used:] = bytes(len(block) - at - used)
        size = at + used
        dmf_inode = dict(source.directory(dict(source.directory(2))[b'DMF']))[b'fixture.dmf']
        dmf_offset, dmf_raw = source.inode(dmf_inode)
        dmf_physical = source.runs(dmf_raw)[0][1] // source.bs
    # Mutate generated fixtures only. Reproduce the export padding and a rejected overlap.
    with image.open('r+b') as f:
        f.seek(physical); f.write(block)
        f.seek(inode_offset + 4); f.write(struct.pack('<I', size))
        f.seek(dmf_offset + 40)
        f.write(struct.pack('<HHHHI', 0xf30a, 2, 4, 0, 0))
        f.write(struct.pack('<IHHI', 0, 3, 0, dmf_physical))
        f.write(struct.pack('<IHHI', 1, 2, 0, dmf_physical + 3))
    return image
