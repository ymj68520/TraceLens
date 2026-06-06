"""Browser history forensic extractors for Chrome and Firefox."""
import logging
import os
import sqlite3
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _webkit_timestamp_to_datetime(webkit_ts: int) -> datetime:
    if webkit_ts == 0: return None
    try: return datetime.fromtimestamp((webkit_ts - 116444736000000000) / 10000000)
    except: return None


def _unix_microseconds_to_datetime(us: int) -> datetime:
    if us == 0: return None
    try: return datetime.fromtimestamp(us / 1000000)
    except: return None


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


@register_extractor
class ChromeHistoryExtractor(BaseExtractor):
    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size

    async def extract_to_markdown(self, file_path: str) -> str:
        if os.path.isdir(file_path):
            db_path = os.path.join(file_path, 'History')
        else:
            db_path = file_path
        if not os.path.exists(db_path):
            return f"Error: Chrome History database not found at {db_path}"

        import tempfile, shutil
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
        tmp.close()
        shutil.copy2(db_path, tmp.name)
        conn = sqlite3.connect(tmp.name)
        cursor = conn.cursor()

        try:
            result = ["# Chrome Browser History Summary"]
            cursor.execute("SELECT COUNT(*) FROM urls")
            total_urls = cursor.fetchone()[0]
            try:
                cursor.execute("SELECT COUNT(*) FROM downloads")
                total_downloads = cursor.fetchone()[0]
            except: total_downloads = 0

            try:
                cursor.execute("SELECT MIN(last_visit_time), MAX(last_visit_time) FROM urls")
                min_ts, max_ts = cursor.fetchone()
                min_date, max_date = _webkit_timestamp_to_datetime(min_ts), _webkit_timestamp_to_datetime(max_ts)
                if min_date and max_date:
                    result.append(f"**Time Range:** {min_date.strftime('%Y-%m-%d')} ~ {max_date.strftime('%Y-%m-%d')}")
            except: pass

            result.append(f"**Total URLs:** {total_urls:,}")
            result.append(f"**Total Downloads:** {total_downloads:,}")
            result.append("")

            result.append("## Top Sites (by visit count)")
            result.append("| URL | Title | Visits | Last Visit |")
            result.append("| --- | --- | --- | --- |")
            cursor.execute("SELECT url, title, visit_count, last_visit_time FROM urls ORDER BY visit_count DESC LIMIT 50")
            for url, title, vc, lvt in cursor.fetchall():
                lv = _webkit_timestamp_to_datetime(lvt)
                lv_str = lv.strftime('%Y-%m-%d %H:%M') if lv else 'N/A'
                if len(url) > 80: url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60: title = title[:57] + "..."
                result.append(f"| {url} | {title} | {vc:,} | {lv_str} |")
            result.append("")

            result.append(f"## Recent URLs (Last {self.sample_size})")
            result.append("| URL | Title | Last Visit |")
            result.append("| --- | --- | --- |")
            cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT ?", (self.sample_size,))
            for url, title, lvt in cursor.fetchall():
                lv = _webkit_timestamp_to_datetime(lvt)
                lv_str = lv.strftime('%Y-%m-%d %H:%M') if lv else 'N/A'
                if len(url) > 80: url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60: title = title[:57] + "..."
                result.append(f"| {url} | {title} | {lv_str} |")

            if total_downloads > 0:
                result.append("")
                result.append("## Recent Downloads")
                result.append("| File | URL | Time | Size |")
                result.append("| --- | --- | --- | --- |")
                try:
                    cursor.execute("SELECT target_path, url, start_time, total_bytes FROM downloads ORDER BY start_time DESC LIMIT 50")
                    for tp, url, st, tb in cursor.fetchall():
                        st_dt = _webkit_timestamp_to_datetime(st)
                        st_str = st_dt.strftime('%Y-%m-%d %H:%M') if st_dt else 'N/A'
                        fn = os.path.basename(tp).replace('|', '\\|') if tp else 'N/A'
                        sz = _format_size(tb) if tb else 'N/A'
                        if len(url) > 60: url = url[:57] + "..."
                        result.append(f"| {fn} | {url} | {st_str} | {sz} |")
                except: pass
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Chrome History: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)


@register_extractor
class FirefoxHistoryExtractor(BaseExtractor):
    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size

    async def extract_to_markdown(self, file_path: str) -> str:
        if os.path.isdir(file_path):
            db_path = os.path.join(file_path, 'places.sqlite')
        else:
            db_path = file_path
        if not os.path.exists(db_path):
            return f"Error: Firefox places.sqlite not found at {db_path}"

        import tempfile, shutil
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
        tmp.close()
        shutil.copy2(db_path, tmp.name)
        conn = sqlite3.connect(tmp.name)
        cursor = conn.cursor()

        try:
            result = ["# Firefox Browser History Summary"]
            cursor.execute("SELECT COUNT(*) FROM moz_places WHERE visit_count > 0")
            total_urls = cursor.fetchone()[0]
            try:
                cursor.execute("SELECT COUNT(*) FROM moz_bookmarks WHERE type = 1")
                total_bookmarks = cursor.fetchone()[0]
            except: total_bookmarks = 0

            try:
                cursor.execute("SELECT MIN(visit_date), MAX(visit_date) FROM moz_historyvisits")
                min_ts, max_ts = cursor.fetchone()
                if min_ts and max_ts:
                    min_d, max_d = _unix_microseconds_to_datetime(min_ts), _unix_microseconds_to_datetime(max_ts)
                    if min_d and max_d:
                        result.append(f"**Time Range:** {min_d.strftime('%Y-%m-%d')} ~ {max_d.strftime('%Y-%m-%d')}")
            except: pass

            result.append(f"**Total URLs:** {total_urls:,}")
            result.append(f"**Total Bookmarks:** {total_bookmarks:,}")
            result.append("")

            result.append("## Top Sites (by visit count)")
            result.append("| URL | Title | Visits | Last Visit |")
            result.append("| --- | --- | --- | --- |")
            cursor.execute("SELECT p.url, p.title, p.visit_count, p.last_visit_date FROM moz_places p WHERE p.visit_count > 0 ORDER BY p.visit_count DESC LIMIT 50")
            for url, title, vc, lvd in cursor.fetchall():
                lv = _unix_microseconds_to_datetime(lvd)
                lv_str = lv.strftime('%Y-%m-%d %H:%M') if lv else 'N/A'
                if len(url) > 80: url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60: title = title[:57] + "..."
                result.append(f"| {url} | {title} | {vc:,} | {lv_str} |")

            result.append("")
            result.append(f"## Recent URLs (Last {self.sample_size})")
            result.append("| URL | Title | Last Visit |")
            result.append("| --- | --- | --- |")
            cursor.execute("SELECT p.url, p.title, h.visit_date FROM moz_historyvisits h JOIN moz_places p ON h.place_id = p.id ORDER BY h.visit_date DESC LIMIT ?", (self.sample_size,))
            for url, title, vd in cursor.fetchall():
                dt = _unix_microseconds_to_datetime(vd)
                dt_str = dt.strftime('%Y-%m-%d %H:%M') if dt else 'N/A'
                if len(url) > 80: url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60: title = title[:57] + "..."
                result.append(f"| {url} | {title} | {dt_str} |")

            if total_bookmarks > 0:
                result.append("")
                result.append("## Recent Bookmarks")
                result.append("| Title | URL | Added |")
                result.append("| --- | --- | --- |")
                cursor.execute("SELECT b.title, p.url, b.dateAdded FROM moz_bookmarks b JOIN moz_places p ON b.fk = p.id WHERE b.type = 1 ORDER BY b.dateAdded DESC LIMIT 50")
                for title, url, da in cursor.fetchall():
                    dt = _unix_microseconds_to_datetime(da)
                    dt_str = dt.strftime('%Y-%m-%d %H:%M') if dt else 'N/A'
                    title = (title or '').replace('|', '\\|')
                    if len(title) > 40: title = title[:37] + "..."
                    if len(url) > 60: url = url[:57] + "..."
                    result.append(f"| {title} | {url} | {dt_str} |")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Firefox history: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)
