"""
Case persistence module - Database operations
"""

import sqlite3
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CasePersistence:
    """Database persistence for case analysis."""

    def __init__(self, settings):
        self.settings = settings

    def ensure_case_analysis_table(self, db_path: str):
        """Ensure case_analysis table exists."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS case_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                case_description TEXT,
                filtered_files TEXT,
                case_report TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)
        
        conn.commit()
        conn.close()

    def persist_filtered_files(self, db_path: str, task_id: str, filtered_files: List[str]):
        """Persist filtered files."""
        self.ensure_case_analysis_table(db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        now = int(time.time())
        
        cursor.execute("""
            INSERT OR REPLACE INTO case_analysis (task_id, filtered_files, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, json.dumps(filtered_files), now, now))
        
        conn.commit()
        conn.close()

    def persist_case_report(self, db_path: str, task_id: str, case_description: str, case_report: str):
        """Persist case report."""
        self.ensure_case_analysis_table(db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        now = int(time.time())
        
        cursor.execute("""
            INSERT OR REPLACE INTO case_analysis 
            (task_id, case_description, case_report, updated_at)
            VALUES (?, ?, ?, ?)
        """, (task_id, case_description, case_report, now))
        
        conn.commit()
        conn.close()

    def get_case_report(self, files_db_path: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve case report."""
        try:
            conn = sqlite3.connect(files_db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT case_description, case_report, filtered_files, created_at, updated_at
                FROM case_analysis
                WHERE task_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
            """, (task_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "case_description": row[0],
                    "case_report": row[1],
                    "filtered_files": json.loads(row[2]) if row[2] else [],
                    "created_at": row[3],
                    "updated_at": row[4]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve case report: {e}")
            return None

    def get_filtered_files(self, files_db_path: str, task_id: str = "") -> List[str]:
        """Retrieve filtered files."""
        try:
            conn = sqlite3.connect(files_db_path)
            cursor = conn.cursor()
            
            if task_id:
                cursor.execute("""
                    SELECT filtered_files
                    FROM case_analysis
                    WHERE task_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (task_id,))
            else:
                cursor.execute("""
                    SELECT filtered_files
                    FROM case_analysis
                    ORDER BY updated_at DESC
                    LIMIT 1
                """)
            
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0]:
                return json.loads(row[0])
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to retrieve filtered files: {e}")
            return []

    def get_file_list_from_db(self, db_path: str) -> List[Dict[str, str]]:
        """Get all files from database."""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        tables = [
            "images", "videos", "audio_files", "documents", "archives",
            "executables", "databases", "source_code", "web_files",
            "email_files", "system_files", "encrypted_files", "unknown_files"
        ]

        files = []
        for table in tables:
            try:
                cursor.execute(f"""
                    SELECT path, name, size, extension, mtime
                    FROM {table}
                    WHERE is_deleted = 0
                    ORDER BY size DESC
                    LIMIT 1000
                """)
                
                for row in cursor.fetchall():
                    files.append({
                        "path": row[0],
                        "name": row[1],
                        "size": row[2],
                        "extension": row[3],
                        "mtime": row[4],
                        "category": table
                    })
            except sqlite3.OperationalError:
                continue

        conn.close()
        return files

    def build_file_summary(self, files: List[Dict[str, str]]) -> str:
        """Build human-readable file summary."""
        lines = []
        for f in files:
            size_str = self._format_size(f.get("size", 0))
            lines.append(f"{f['path']} | {size_str} | {f.get('extension', 'N/A')}")
        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes) -> str:
        """Format file size."""
        if size_bytes < 1024:
            return f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"

