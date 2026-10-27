"""Prefetch parsing through libscca, with no filename-derived execution claims."""
import os
from .base import BaseExtractor, ExtractionResult, register_extractor
from .windows_time import filetime_to_datetime, utc_iso


@register_extractor
class PrefetchExtractor(BaseExtractor):
    MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

    async def extract_to_markdown(self, file_path: str) -> str:
        return (await self.extract_result(file_path)).require_content()

    async def extract_result(self, file_path: str) -> ExtractionResult:
        try:
            with open(file_path, "rb") as stream:
                head = stream.read(8)
            if len(head) < 8:
                raise ValueError("PREFETCH_TRUNCATED_HEADER")
            compressed = head[:4] in (b"MAM\x04", b"MAM\x84")
            if not compressed and head[4:8] != b"SCCA":
                raise ValueError("PREFETCH_INVALID_SIGNATURE")
            if compressed and not 84 <= int.from_bytes(head[4:8], "little") <= self.MAX_UNCOMPRESSED_BYTES:
                raise ValueError("PREFETCH_INVALID_DECOMPRESSED_SIZE")
        except (OSError, ValueError) as exc:
            return ExtractionResult("error", "libscca", diagnostics=(str(exc) if isinstance(exc, ValueError) else "PREFETCH_READ_FAILED",))
        try:
            import pyscca
        except ImportError:
            return ExtractionResult("unsupported", "libscca", diagnostics=("PREFETCH_PARSER_UNAVAILABLE",))
        try:
            return self._extract_with_libscca(pyscca, file_path)
        except Exception:
            return ExtractionResult("error", "libscca", diagnostics=("PREFETCH_PARSE_FAILED",))

    def _extract_with_libscca(self, pyscca, file_path: str) -> ExtractionResult:
        source = pyscca.file()
        try:
            source.open(file_path)
            version = source.get_format_version()
            if version not in (17, 23, 26, 30, 31):
                return ExtractionResult("unsupported", "libscca", diagnostics=("PREFETCH_VERSION_UNSUPPORTED",))
            # Essential fields failing makes the outcome unavailable, never fabricated.
            record = {"format_version": version, "executable_name": source.get_executable_filename(),
                      "prefetch_hash": source.get_prefetch_hash(), "run_count": source.get_run_count(),
                      "execution_times": [], "referenced_files": [], "volumes": []}
            warnings = []
            slots = 1 if version in (17, 23) else 8
            for slot in range(slots):
                try:
                    raw = source.get_last_run_time_as_integer(slot)
                    if not raw:
                        continue
                    parsed = filetime_to_datetime(raw)
                    record["execution_times"].append({"slot": slot, "filetime": raw, "utc": utc_iso(parsed)})
                    if parsed is None:
                        warnings.append("PREFETCH_INVALID_TIME")
                except Exception:
                    warnings.append("PREFETCH_TIME_UNAVAILABLE")
            if record["run_count"] and not any(t["slot"] == 0 and t["utc"] for t in record["execution_times"]):
                warnings.append("PREFETCH_LATEST_TIME_UNAVAILABLE")
            try:
                total = source.get_number_of_filenames()
                for index in range(min(60, total)):
                    record["referenced_files"].append(source.get_filename(index))
            except Exception:
                total = None
                warnings.append("PREFETCH_REFERENCES_UNAVAILABLE")
            try:
                for index in range(source.get_number_of_volumes()):
                    volume = source.get_volume_information(index)
                    raw = volume.get_creation_time_as_integer()
                    record["volumes"].append({"device_path": volume.get_device_path(),
                                              "serial": volume.get_serial_number(),
                                              "creation_filetime": raw,
                                              "creation_utc": utc_iso(filetime_to_datetime(raw))})
            except Exception:
                warnings.append("PREFETCH_VOLUMES_UNAVAILABLE")
            coverage = {"record_count": 1, "referenced_file_count": total,
                        "referenced_files_shown": len(record["referenced_files"])}
            if total is not None and total > len(record["referenced_files"]):
                warnings.append("PREFETCH_REFERENCES_SAMPLED")
            return ExtractionResult("partial" if warnings else "ok", "libscca",
                                    parser_version=getattr(pyscca, "get_version", lambda: "unknown")(),
                                    text=self._render(record, file_path), records=(record,),
                                    diagnostics=tuple(sorted(set(warnings))), coverage=coverage)
        finally:
            try:
                source.close()
            except Exception:
                pass

    @staticmethod
    def _render(record: dict, file_path: str) -> str:
        lines = [f"# Prefetch 执行记录 `{os.path.basename(file_path)}`",
                 f"格式版本：{record['format_version']}",
                 f"可执行文件名：{record['executable_name'] or '未知'}",
                 f"执行次数：{record['run_count']}",
                 f"Prefetch 路径哈希：{record['prefetch_hash']:08x}", "", "## 执行时间 UTC"]
        for stamp in record["execution_times"]:
            lines.append(f"- 槽位 {stamp['slot']}：{stamp['utc'] or '未知'}；原始 FILETIME：{stamp['filetime']}")
        if not record["execution_times"]:
            lines.append("未取得执行时间。")
        if record["volumes"]:
            lines.extend(["", "## 卷信息"])
            for volume in record["volumes"]:
                lines.append(f"- {volume['device_path']}；序列号 {volume['serial']:08x}；卷创建时间 UTC：{volume['creation_utc'] or '未知'}")
        if record["referenced_files"]:
            lines.extend(["", "## 引用路径 最多展示 60 条"])
            lines.extend(f"- `{name}`" for name in record["referenced_files"] if name)
        lines.extend(["", "记录反映预取器保存的程序活动；不能仅据此确定操作者身份或推断全部执行历史。"])
        return "\n".join(lines)
