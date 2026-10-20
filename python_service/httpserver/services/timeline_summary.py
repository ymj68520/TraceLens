"""Versioned deterministic statistics over an existing source, with exact drilldown."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

from .timeline_sources import TimelineSource, SourceChanged, digest

STATISTICS_VERSION = "timeline-summary:v1"
MAX_SCAN_ROWS = 100_000
MAX_DAILY_POINTS = 3660
DEDUP_RULE = "same-source-original-id-and-payload:v1"


class SummaryFilters(BaseModel):
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    start_time: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    end_time: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    start_date: date | None = None
    end_date: date | None = None
    event_type: str = Field(default="", max_length=128)
    event_source: str = Field(default="", max_length=128)
    talker: str = Field(default="", max_length=256)
    direction: Literal["all", "sent", "received", "unknown", "system"] = "all"

    @model_validator(mode="after")
    def valid_range(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("请选择有效的 IANA 时区") from exc
        if self.start_time is not None and self.end_time is not None and self.start_time > self.end_time:
            raise ValueError("开始时间不能晚于结束时间")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class RecordSelection(BaseModel):
    hour: int | None = Field(default=None, ge=0, le=23)
    weekday: int | None = Field(default=None, ge=0, le=6)
    day: date | None = None
    direction: Literal["sent", "received", "unknown", "system"] | None = None
    quality: Literal["valid", "missing", "invalid", "inferred", "processing"] = "valid"
    record_ref: str | None = Field(default=None, max_length=100)
    offset: int = Field(default=0, ge=0, le=MAX_SCAN_ROWS)
    limit: int = Field(default=50, ge=1, le=100)


def parse_time(value, unit, tz):
    if value is None or value == "" or value == 0 or value == "0":
        return None, "missing"
    try:
        if isinstance(value, bool):
            raise ValueError()
        n = float(value)
        if not math.isfinite(n) or n <= 0:
            raise ValueError()
        if unit == "milliseconds":
            n /= 1000
        return datetime.fromtimestamp(n, timezone.utc).astimezone(tz), "valid"
    except (ValueError, OverflowError, OSError, TypeError):
        return None, "invalid"


def summarize(source: TimelineSource, filters: SummaryFilters, *, selection: RecordSelection | None = None,
              expected_version: str | None = None, expected_summary: str | None = None,
              scan_limit: int = MAX_SCAN_ROWS):
    if not 1 <= scan_limit <= MAX_SCAN_ROWS:
        raise ValueError("invalid scan limit")
    if source.kind == "events" and (filters.talker or filters.direction != "all"):
        raise ValueError("事件来源不支持通讯筛选")
    if source.kind != "events" and (filters.event_type or filters.event_source):
        raise ValueError("通讯来源不支持事件筛选")
    before = source.revision()
    if expected_version and before != expected_version:
        raise SourceChanged("来源已更新，请重新生成统计后回查")
    tz = ZoneInfo(filters.timezone)
    hourly, weekdays = Counter(), Counter()
    hourly_days, heat = defaultdict(set), Counter()
    daily, daily_directions = Counter(), defaultdict(Counter)
    directions, by_basis, by_type, by_source = Counter(), Counter(), Counter(), Counter()
    direction_hours = defaultdict(Counter)
    counts = Counter()
    seen, keys = set(), {}
    detail_rows, detail_total = [], 0
    table_counts, missing_tables = {}, []
    observed_min = observed_max = None
    scanned_hashes = []
    with closing(source.connect()) as conn:
        tables, missing_tables = source.tables(conn)
        remaining = scan_limit
        # Each table is counted even after the budget is exhausted; partial
        # coverage is always exposed, including a skipped second QQ table.
        for table in tables:
            total, cursor = source.rows(conn, table, filters, remaining)
            table_counts[table] = total
            for raw in cursor:
                remaining -= 1
                counts["scanned_records"] += 1
                row = source.normalize(table, raw)
                payload_hash = digest(row["payload"])
                scanned_hashes.append(digest([row["record_ref"], payload_hash]))
                key = digest(row["dedup_key"])
                if (key, payload_hash) in seen:
                    counts["duplicate_records"] += 1
                    continue
                if key in keys and keys[key] != payload_hash:
                    counts["identity_conflict_records"] += 1
                seen.add((key, payload_hash))
                keys[key] = payload_hash
                if filters.direction != "all" and row["direction"] != filters.direction:
                    counts["outside_direction_records"] += 1
                    continue
                dt, quality = parse_time(row["timestamp_raw"], source.identity["timestamp_unit"], tz)
                # Undatable rows cannot be assigned to a requested date range.
                # Their count belongs to the same non-time scope, explicitly.
                if dt and ((filters.start_time is not None and dt.timestamp() < filters.start_time)
                           or (filters.end_time is not None and dt.timestamp() > filters.end_time)
                           or (filters.start_date and dt.date() < filters.start_date)
                           or (filters.end_date and dt.date() > filters.end_date)):
                    counts["outside_time_records"] += 1
                    continue
                if quality == "valid" and row["time_basis"] in ("inferred", "processing"):
                    quality = row["time_basis"]
                counts[f"{quality}_records"] += 1
                row.update(timestamp_status=quality, timestamp_iso=dt.isoformat() if dt else None,
                           local_date=dt.date().isoformat() if dt else None,
                           local_hour=dt.hour if dt else None, weekday=dt.weekday() if dt else None)
                if quality == "valid":
                    day = dt.date().isoformat()
                    observed_min = min(observed_min, dt.timestamp()) if observed_min is not None else dt.timestamp()
                    observed_max = max(observed_max, dt.timestamp()) if observed_max is not None else dt.timestamp()
                    hourly[dt.hour] += 1
                    hourly_days[dt.hour].add(day)
                    weekdays[dt.weekday()] += 1
                    heat[(dt.weekday(), dt.hour)] += 1
                    daily[day] += 1
                    directions[row["direction"]] += 1
                    daily_directions[day][row["direction"]] += 1
                    direction_hours[row["direction"]][dt.hour] += 1
                    by_basis[row["time_basis"]] += 1
                    by_type[row["event_type"]] += 1
                    by_source[row["event_source"]] += 1
                if selection and quality == selection.quality and (
                    (selection.record_ref is None or row["record_ref"] == selection.record_ref)
                    and (selection.hour is None or row["local_hour"] == selection.hour)
                    and (selection.weekday is None or row["weekday"] == selection.weekday)
                    and (selection.day is None or row["local_date"] == selection.day.isoformat())
                    and (selection.direction is None or row["direction"] == selection.direction)
                ):
                    if selection.offset <= detail_total < selection.offset + selection.limit:
                        detail_rows.append(source.present(row))
                    detail_total += 1
        conn.rollback()
    if before != source.revision():
        raise SourceChanged("统计期间来源发生变化，请重试")
    for name in ("scanned", "valid", "missing", "invalid", "inferred", "processing", "duplicate",
                 "identity_conflict", "outside_time", "outside_direction"):
        counts.setdefault(f"{name}_records", 0)
    total = sum(table_counts.values())
    days = sorted(daily)
    context = {
        "scope": source.identity, "filters": filters.model_dump(mode="json"),
        "time_interval": "start_time <= timestamp <= end_time; local dates inclusive",
        "source_version": before, "source_version_kind": "database-and-wal-file-revision-not-forensic-hash",
        "scanned_content_hash": digest(scanned_hashes), "statistics_version": STATISTICS_VERSION,
        "deduplication": {"rule": DEDUP_RULE, "description": "仅合并同一来源、相同原始记录标识且内容一致的记录；冲突记录保留。不同来源不自动合并。",
                          "identity": "事件 id；微信 msgSvrId（无则 msgId）；派生微信行 id；QQ 表内消息 id。"},
        "counts": dict(counts), "candidate_records": total, "table_counts": table_counts,
        "coverage": {
            "scan_limit": scan_limit, "truncated": total > counts["scanned_records"],
            "scan_order": "source-table-order then SQLite rowid ascending, before time/direction filtering",
            "unscanned_records": total - counts["scanned_records"],
            "missing_tables": missing_tables, "observed_days": len(days),
            "first_observed_time": observed_min, "last_observed_time": observed_max,
            "displayed_days_limit": MAX_DAILY_POINTS, "daily_truncated": len(days) > MAX_DAILY_POINTS,
            "quality_scope": "缺失/无效时间来自同一非时间筛选范围，无法判断其是否落在所选日期内。",
        },
    }
    context_id = digest(context)
    context["context_id"] = context_id
    if expected_summary and context_id != expected_summary:
        raise SourceChanged("回查条件或统计版本与原总结不一致，请重新生成统计")
    if selection:
        return {"context": context, "selection": selection.model_dump(mode="json"),
                "records": detail_rows, "total": detail_total,
                "page_truncated": selection.offset + len(detail_rows) < detail_total}
    def item(**values):
        return {"context_id": context_id, **values}
    hours = [item(hour=h, count=hourly[h], observed_days=len(hourly_days[h]),
                  observed_day_denominator=len(days),
                  share=round(hourly[h] / counts["valid_records"], 6) if counts["valid_records"] else None,
                  selector={"hour": h}) for h in range(24)]
    repeats = sorted((h for h in hours if h["observed_days"] >= 3),
                     key=lambda h: (-h["observed_days"], -h["count"], h["hour"]))[:5]
    changes = []
    for day in days[:MAX_DAILY_POINTS]:
        previous = date.fromordinal(date.fromisoformat(day).toordinal() - 1).isoformat()
        prior_count = daily.get(previous)
        changes.append(item(day=day, count=daily[day], directions=dict(daily_directions[day]),
                            previous_calendar_day=previous, previous_count=prior_count,
                            delta=daily[day] - prior_count if prior_count is not None else None,
                            selector={"day": day}))
    warnings = ["统计范围内没有记录不等于没有活动；记录较少不代表不活跃。",
                "有记录日期不等于完整覆盖日期，记录数不能换算为在线时长或操作次数。",
                "规律为来源记录的时间分布，不直接证明具体人员行为或犯罪性质。"]
    if source.kind == "events":
        warnings.append("文件时间戳与后台事件不等于人为操作；推定删除和处理时间已排除出分布。")
    else:
        warnings.append("收到消息不证明账号主人当时操作；系统消息和未知方向单独计数。")
    if total > counts["scanned_records"]:
        warnings.append("来源扫描已截断，当前结果仅描述已扫描记录，不能代表全量规律。")
    if missing_tables:
        warnings.append("部分来源表缺失，不能将缺失部分视为零条记录。")
    if len(days) < 3:
        warnings.append("有记录日期不足3天，暂不形成重复时段判断。")
    peak = max(hours, key=lambda h: h["count"])
    narrative = ("当前范围没有可用于时间分布的有效记录，不能判断活动规律。" if not counts["valid_records"] else
                 f"已统计 {counts['valid_records']} 条有效时间记录，分布在 {len(days)} 个有记录日期；"
                 f"{peak['hour']:02d}:00—{peak['hour'] + 1:02d}:00 的记录最多，共 {peak['count']} 条，"
                 f"出现在 {peak['observed_days']} 个日期。")
    return {
        "context": context, "warnings": warnings, "summary": item(text=narrative),
        "hours": hours, "repeated_hours": repeats,
        "weekdays": [item(weekday=d, count=weekdays[d]) for d in range(7)],
        "heatmap": [item(weekday=d, hour=h, count=heat[(d, h)], selector={"weekday": d, "hour": h})
                    for d in range(7) for h in range(24)],
        "daily": changes,
        "communication": item(available=source.kind != "events", counts=dict(directions),
                              hourly={k: [v[h] for h in range(24)] for k, v in direction_hours.items()}),
        "time_bases": dict(by_basis), "event_types": dict(by_type), "event_sources": dict(by_source),
    }
