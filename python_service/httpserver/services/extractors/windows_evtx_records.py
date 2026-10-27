"""Provider-scoped EVTX records and explicit parse coverage."""
from collections import Counter
from datetime import datetime, timezone
import heapq
import os
import re
from importlib.metadata import version as package_version, PackageNotFoundError
from .base import BaseExtractor, ExtractionResult, register_extractor
from .windows_evtx_native import NativeEvtxReader

LEVEL_NAMES = {0: "始终记录", 1: "严重", 2: "错误", 3: "警告", 4: "信息", 5: "详细"}
EVENT_ID_DESCRIPTIONS = {
    "Microsoft-Windows-Security-Auditing": {
        4624: "登录成功", 4625: "登录失败", 4634: "注销", 4647: "用户发起注销",
        4648: "使用显式凭据登录", 4672: "为新登录分配特殊权限", 4688: "创建进程",
        4689: "进程退出", 4698: "创建计划任务", 4699: "删除计划任务",
        4700: "启用计划任务", 4701: "禁用计划任务", 4702: "更新计划任务",
        4720: "创建用户账户", 4722: "启用用户账户", 4725: "禁用用户账户", 4726: "删除用户账户",
    },
    "Microsoft-Windows-TerminalServices-LocalSessionManager": {
        21: "远程桌面会话登录", 22: "远程桌面 Shell 启动", 23: "远程桌面会话注销",
        24: "远程桌面会话断开", 25: "远程桌面会话重新连接",
    },
    "Microsoft-Windows-TerminalServices-RemoteConnectionManager": {1149: "远程桌面用户身份验证成功"},
    "Microsoft-Windows-PowerShell": {4103: "PowerShell 模块日志", 4104: "PowerShell 脚本块日志",
                                     4105: "脚本块执行开始", 4106: "脚本块执行结束"},
    "Microsoft-Windows-Windows Defender": {1116: "检测到恶意软件", 1117: "已采取处置操作", 1118: "处置操作失败"},
    "EventLog": {6005: "事件日志服务启动", 6006: "事件日志服务停止", 6008: "意外关机", 6009: "启动时操作系统版本"},
    "Service Control Manager": {7034: "服务异常终止", 7035: "服务控制请求", 7036: "服务状态变化", 7040: "服务启动类型变化"},
    "User32": {1074: "发起关机或重新启动"},
}


def event_description(provider, event_id):
    return EVENT_ID_DESCRIPTIONS.get(provider, {}).get(event_id, "未提供事件说明")


def _timestamp(raw):
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def _cell(value):
    return str(value if value is not None else "未知").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


@register_extractor
class EvtxExtractor(BaseExtractor):
    def __init__(self, sample_size=100, max_scan_records=None):
        self.sample_size = max(1, min(1000, int(sample_size)))
        self.max_scan_records=max_scan_records

    async def extract_to_markdown(self, file_path):
        return (await self.extract_result(file_path)).require_content()

    async def extract_result(self, file_path):
        try:
            import Evtx.Evtx
        except ImportError:
            return ExtractionResult("unsupported", "python-evtx", diagnostics=("EVTX_PARSER_UNAVAILABLE",))
        try:
            return self._extract_with_python_evtx(file_path)
        except Exception:
            return ExtractionResult("error", "python-evtx", diagnostics=("EVTX_PARSE_FAILED",))

    def _extract_with_python_evtx(self, file_path):
        from Evtx.Evtx import Evtx
        from defusedxml import ElementTree as ET
        ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
        samples, distributions, levels = [], Counter(), Counter()
        computers, warnings = set(), set()
        total, failed, unknown_time, visible, native_count = 0, 0, 0, 0, 0
        earliest = latest = None
        with Evtx(file_path) as log, NativeEvtxReader(file_path) as native:
            header = log.get_file_header()
            # python-evtx's verify() hardcodes minor version 1, rejecting valid 3.2 logs.
            if header.magic() != "ElfFile\x00" or header.major_version() != 3 or header.minor_version() not in (1, 2) or header.header_chunk_size() != 4096:
                return ExtractionResult("error", "python-evtx", diagnostics=("EVTX_INVALID_HEADER",))
            if header.checksum() != header.calculate_checksum():
                return ExtractionResult("error", "python-evtx", diagnostics=("EVTX_HEADER_CHECKSUM_INVALID",))
            if os.path.getsize(file_path) < 4096 + header.chunk_count() * 65536:
                warnings.add("EVTX_FILE_TRUNCATED")
            try:
                for index, raw_record in enumerate(log.records()):
                    if self.max_scan_records is not None and index>=self.max_scan_records:
                        warnings.add('EVTX_PROBE_SCAN_LIMIT');break
                    visible += 1
                    try:
                        decoder = "python-evtx"
                        try:
                            xml = raw_record.xml()
                        except Exception:
                            xml = native.read_xml(index, raw_record.record_num())
                            decoder = "libevtx:" + (native.version or "unknown")
                        root = ET.fromstring(xml)
                        system = root.find("e:System", ns)
                        if system is None:
                            raise ValueError("missing System")
                        def value(name):
                            node = system.find("e:" + name, ns)
                            return node.text if node is not None else None
                        def integer(name):
                            text = value(name)
                            if text is None or not text.strip():
                                return None
                            try:
                                return int(text)
                            except ValueError:
                                warnings.add("EVTX_FIELDS_UNKNOWN")
                                return None
                        provider = system.find("e:Provider", ns)
                        when = system.find("e:TimeCreated", ns)
                        raw_time = when.get("SystemTime") if when is not None else None
                        utc = _timestamp(raw_time) if raw_time else None
                        if utc is None:
                            unknown_time += 1
                        else:
                            earliest = min(earliest, utc) if earliest else utc
                            latest = max(latest, utc) if latest else utc
                        record = {"event_id": integer("EventID"), "level": integer("Level"),
                                  "provider": provider.get("Name") if provider is not None else None,
                                  "provider_guid": provider.get("Guid") if provider is not None else None,
                                  "channel": value("Channel"), "version": integer("Version"),
                                  "record_id": integer("EventRecordID"), "computer": value("Computer"),
                                  "raw_timestamp": raw_time, "timestamp_utc": utc.isoformat().replace("+00:00", "Z") if utc else None,
                                  "record_offset": raw_record.offset(), "xml": xml, "decoder": decoder}
                        if record["event_id"] is None or record["level"] not in LEVEL_NAMES or not record["provider"]:
                            warnings.add("EVTX_FIELDS_UNKNOWN")
                        fields = []
                        for node in root.findall("e:EventData/e:Data", ns):
                            fields.append({"name": node.get("Name"), "value": node.text})
                        userdata = root.find("e:UserData", ns)
                        if userdata is not None:
                            fields.extend({"name": n.tag.rsplit("}",1)[-1], "value": n.text}
                                          for n in userdata.iter() if n.text and n.text.strip())
                        record["data"] = fields
                        key = (record["provider"], record["event_id"], record["level"])
                        distributions[key] += 1
                        levels[record["level"]] += 1
                        if record["computer"]:
                            computers.add(record["computer"])
                        total += 1
                        if decoder.startswith("libevtx:"):
                            native_count += 1
                        # Unknown-time records never displace dated records in "recent" sampling.
                        # datetime truncates to microseconds; retain the seventh
                        # fractional digit when ordering native 100 ns timestamps.
                        fraction = re.search(r"T\d{2}:\d{2}:\d{2}\.(\d+)", raw_time or "")
                        subtick = int((fraction.group(1) + "0000000")[6]) if fraction else 0
                        rank = (utc is not None, utc or datetime.min.replace(tzinfo=timezone.utc), subtick, index)
                        item = (*rank, record)
                        if len(samples) < self.sample_size:
                            heapq.heappush(samples, item)
                        elif rank > samples[0][:4]:
                            heapq.heapreplace(samples, item)
                    except Exception:
                        failed += 1
            except Exception:
                warnings.add("EVTX_ITERATION_INCOMPLETE")
        if failed:
            warnings.add("EVTX_RECORDS_UNREADABLE")
        if unknown_time:
            warnings.add("EVTX_TIME_UNKNOWN")
        records = tuple(item[4] for item in sorted(samples, key=lambda item: item[:4], reverse=True))
        coverage = {"record_count": visible, "parsed_record_count": total, "failed_records": failed,
                    "native_xml_records": native_count, "unknown_time_records": unknown_time,
                    "sample_count": len(records), "record_scope": "standard_visible", "recovered_records_included": False,
                    "earliest_utc": earliest.isoformat() if earliest else None, "latest_utc": latest.isoformat() if latest else None}
        limited='EVTX_PROBE_SCAN_LIMIT' in warnings
        if limited:
            coverage.update(record_count=None,scanned_records=visible,record_count_basis='lower_bound',time_scope='scanned_records')
        if not total:
            return ExtractionResult("error" if warnings else "metadata_only", "python-evtx",
                                    diagnostics=tuple(sorted(warnings)) or ("EVTX_NO_VISIBLE_RECORDS",), coverage=coverage)
        if len(records) < total:
            warnings.add("EVTX_RECORDS_SAMPLED")
        lines = [f"# Windows 事件日志 `{os.path.basename(file_path)}`", f"计算机：{', '.join(sorted(computers)) or '未知'}",
                 f"标准可见记录数：{visible}；已解析：{total}；无法解析：{failed}；未知时间：{unknown_time}"]
        if limited:lines[2]=f'本次仅扫描前 {visible} 条记录；以下分布和时间均限于扫描窗口，不代表全文件。'
        if earliest:
            lines.append(f"时间范围 UTC：{earliest.isoformat()} 至 {latest.isoformat()}")
        lines += ["", "## 事件分布 前 20 组", "| 提供程序 | 事件 ID | 级别 | 数量 | 说明 |", "| --- | --- | --- | --- | --- |"]
        for (provider, event_id, level), count in distributions.most_common(20):
            lines.append("| " + " | ".join(map(_cell, (provider, event_id, LEVEL_NAMES.get(level,"未知"), count, event_description(provider,event_id)))) + " |")
        lines += ["", f"## 最近事件 最多 {self.sample_size} 条", "按 UTC 时间倒序；无有效时间的记录排在有时间的记录之后。",
                  "| UTC 时间 | 记录 ID | 事件 ID | 级别 | 提供程序 | 数据片段 |", "| --- | --- | --- | --- | --- | --- |"]
        for record in records:
            message = "; ".join(f"{f['name'] or '数据'}={f['value'] or ''}" for f in record["data"])
            message = message[:300] + ("…（截断）" if len(message) > 300 else "")
            lines.append("| " + " | ".join(map(_cell,(record["timestamp_utc"],record["record_id"],record["event_id"],
                         LEVEL_NAMES.get(record["level"],"未知"),record["provider"],message))) + " |")
        lines.append(f"\n展示 {len(records)} / {total} 条标准可见记录；不含回收记录。事件名称仅表示对应提供程序的记录语义。")
        try:
            version = package_version("python-evtx")
        except PackageNotFoundError:
            version = "unknown"
        if native_count:
            version += ";libevtx=" + (native.version or "unknown")
        return ExtractionResult("partial" if warnings else "ok", "python-evtx", parser_version=version, text="\n".join(lines),
                                records=records, diagnostics=tuple(sorted(warnings)), coverage=coverage)
