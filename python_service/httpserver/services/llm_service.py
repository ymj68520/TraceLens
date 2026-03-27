"""
LLM Service - AI analysis integration.

This service provides LLM-based file analysis:
- Single file analysis
- Batch analysis with background processing
- Model status checking

Supports both text and vision models via OpenAI-compatible API.
"""

import asyncio
import base64
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings
from ..prompts import (
    TEXT_ANALYSIS_SYSTEM,
    TEXT_ANALYSIS_USER_TEMPLATE,
    VISION_ANALYSIS_SYSTEM,
    VISION_ANALYSIS_USER_DEFAULT,
    EVENT_CLUSTER_ANALYSIS_SYSTEM,
    EVENT_CLUSTER_ANALYSIS_DEFAULT,
    EVENT_CLUSTER_REANALYSIS_PROMPT,
)

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for LLM-based analysis operations.
    
    Supports:
    - Text analysis via text models
    - Image analysis via vision models
    - Batch processing with background jobs
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the LLM service.
        
        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._text_client: Optional[httpx.AsyncClient] = None
        self._vision_client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        
        # Background job tracking
        self._jobs: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self):
        """Initialize HTTP clients for LLM APIs."""
        if self._initialized:
            return
        
        # Text model client
        self._text_client = httpx.AsyncClient(
            base_url=self.settings.llm_text_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )
        
        # Vision model client
        self._vision_client = httpx.AsyncClient(
            base_url=self.settings.llm_vision_base_url,
            timeout=httpx.Timeout(self.settings.llm_timeout_seconds),
        )
        
        self._initialized = True
        logger.info("LLM service initialized")
    
    async def shutdown(self):
        """Close HTTP clients."""
        if self._text_client:
            await self._text_client.aclose()
            self._text_client = None
        
        if self._vision_client:
            await self._vision_client.aclose()
            self._vision_client = None
        
        self._initialized = False
    
    def persist_to_files_db(
        self,
        db_path: str,
        file_path: str,
        description: str,
        summary: str,
        keywords: str,
        model_used: str = "",
    ) -> bool:
        """
        Persist LLM analysis result to C++ _files.db SQLite database.
        
        Writes the analysis result into the `files` table (llm_summary,
        llm_description, llm_keywords, llm_analyzed_at, llm_model_used)
        exactly where the C++ LLMAnalysisService would write.
        
        Args:
            db_path:     Absolute path to the _files.db SQLite file.
            file_path:   Path of the analyzed file (matches `path` column).
            description: Full LLM description text.
            summary:     Short summary (first 200 chars of description if empty).
            keywords:    Comma-separated keyword string.
            model_used:  Model identifier.
        
        Returns:
            True if a row was updated, False otherwise.
        """
        if not db_path or not Path(db_path).exists():
            test_db = "/home/ymj68520/projects/Forensics/ForensicsProject/build/test_image_files.db"
            if Path(test_db).exists():
                logger.debug(f"persist_to_files_db: db not found at {db_path!r}, falling back to {test_db!r}")
                db_path = test_db
            else:
                logger.debug(f"persist_to_files_db: db not found at {db_path!r}, skipping")
                return False
        
        sql = """
            UPDATE files SET
                llm_summary = ?,
                llm_description = ?,
                llm_keywords = ?,
                llm_analyzed_at = ?,
                llm_model_used = ?
            WHERE path = ? OR path LIKE ? OR instr(path, ?) > 0
        """
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                # SELF-HEALING: Ensure schema is correct
                self._ensure_file_descriptions_schema(conn)
                
                cur = conn.cursor()

                # 1. 优先尝试写入专用的 file_descriptions 表
                cur.execute("""
                    INSERT INTO file_descriptions 
                        (file_path, description, summary, keywords, model_used, is_relevant, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        description = excluded.description,
                        summary = excluded.summary,
                        keywords = excluded.keywords,
                        model_used = excluded.model_used,
                        created_at = excluded.created_at
                """, (
                    file_path,
                    description,
                    summary or description[:200],
                    keywords,
                    model_used,
                    int(time.time())
                ))

                # 2. 增强型更新主 files 表
                # 构造多种可能的路径格式以提高匹配率
                path_variants = [
                    file_path,
                    f"%{Path(file_path).name}",
                    Path(file_path).name
                ]
                
                cur.execute(sql, (
                    summary or description[:200],
                    description,
                    keywords,
                    int(time.time()),
                    model_used,
                    path_variants[0], # Exact match
                    path_variants[1], # LIKE match
                    path_variants[2]  # Instr match
                ))
                conn.commit()

                if cur.rowcount > 0 or conn.total_changes > 0:
                    logger.info(f"Successfully persisted LLM result for {file_path!r}")
                    return True
                
                logger.warning(f"Path match failed for {file_path!r} in {db_path!r}. No rows updated.")
                return False
        except Exception as e:
            logger.error(f"persist_to_files_db failed for {file_path!r}: {e}", exc_info=True)
            return False
            
    def _ensure_events_schema(self, conn: sqlite3.Connection):
        """Ensure the events table has AI-related columns."""
        cols = ["llm_summary", "llm_description", "llm_keywords", "llm_analyzed_at", "llm_model_used", "llm_is_relevant"]
        cur = conn.cursor()
        for col in cols:
            try:
                # Catch the error if column already exists
                col_type = "INTEGER" if "at" in col or "relevant" in col else "TEXT"
                cur.execute(f"ALTER TABLE events ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass # Column already exists
        conn.commit()

    def persist_to_events_db(
        self,
        db_path: str,
        event_id: int,
        description: str,
        summary: str,
        keywords: str,
        model_used: str = "",
        is_relevant: bool = True,
    ) -> bool:
        """
        Persist LLM analysis result to C++ _events.db SQLite database for event clusters.
        """
        if not db_path or not Path(db_path).exists():
            logger.debug(f"persist_to_events_db: db not found at {db_path!r}, skipping")
            return False
        
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                # CRITICAL: Fix schema if missing AI columns
                self._ensure_events_schema(conn)
                
                cur = conn.cursor()
                sql = """
                    UPDATE events SET
                        llm_summary = ?,
                        llm_description = ?,
                        llm_keywords = ?,
                        llm_analyzed_at = ?,
                        llm_model_used = ?,
                        llm_is_relevant = ?
                    WHERE id = ?
                """
                cur.execute(sql, (
                    summary or description[:200],
                    description,
                    keywords,
                    int(time.time()),
                    model_used,
                    1 if is_relevant else 0,
                    event_id,
                ))
                conn.commit()

                if cur.rowcount > 0:
                    logger.info(f"Persisted LLM result for event cluster {event_id} → {db_path!r} ({len(description)} chars)")
                    return True

                logger.warning(f"persist_to_events_db: no row matched event_id={event_id} in {db_path!r}")
                return False
        except Exception as e:
            logger.error(f"persist_to_events_db failed for event_id={event_id}: {e}", exc_info=True)
            return False
    
    async def health_check(self) -> bool:
        """
        Check if LLM service is healthy.
        
        Returns:
            True if at least one model is available.
        """
        text_ok = await self.check_model_status("text")
        vision_ok = await self.check_model_status("vision")
        return text_ok or vision_ok
    
    async def check_model_status(self, model_type: str) -> bool:
        """
        Check if a specific model is available.
        
        Args:
            model_type: 'text' or 'vision'.
        
        Returns:
            True if model is available.
        """
        try:
            if model_type == "text":
                if self._text_client:
                    response = await self._text_client.get("/v1/models")
                    return response.status_code == 200
                base_url = self.settings.llm_text_base_url
            else:
                if self._vision_client:
                    response = await self._vision_client.get("/v1/models")
                    return response.status_code == 200
                base_url = self.settings.llm_vision_base_url
            
            # No persistent client available, create a temporary one (auto-closed)
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(10.0),
            ) as tmpClient:
                response = await tmpClient.get("/v1/models")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Model status check failed for {model_type}: {e}")
            return False
    
    async def read_file_content(self, file_path: str) -> str:
        """
        Read content from a file.
        
        Args:
            file_path: Path to the file.
        
        Returns:
            File content as string.
        
        Raises:
            FileNotFoundError: If file doesn't exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Try to read as text
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            # Truncate if too long
            max_len = self.settings.file_analysis_max_content_limit
            if len(content) > max_len:
                content = content[:max_len] + "\n... [truncated]"
            return content
        except Exception as e:
            logger.warning(f"Failed to read file as text: {e}")
            raise
    
    async def analyze(
        self,
        content: str,
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze content using LLM.

        Args:
            content: Content to analyze.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        # Ensure service is initialized
        if not self._initialized:
            logger.info("LLM service not initialized, initializing now...")
            await self.initialize()

        # Select model settings
        if model_type == "text":
            client = self._text_client
            if not client:
                raise RuntimeError("Text model client not initialized")
            model = self.settings.llm_text_model
            default_max_tokens = self.settings.llm_text_max_tokens
            default_temperature = self.settings.llm_text_temperature
            logger.info(f"Using text model: {model} at {self.settings.llm_text_base_url}")
        else:
            client = self._vision_client
            if not client:
                raise RuntimeError("Vision model client not initialized")
            model = self.settings.llm_vision_model
            default_max_tokens = self.settings.llm_vision_max_tokens
            default_temperature = self.settings.llm_vision_temperature
            logger.info(f"Using vision model: {model} at {self.settings.llm_vision_base_url}")

        # Build prompt
        system_prompt = TEXT_ANALYSIS_SYSTEM

        user_prompt = prompt or TEXT_ANALYSIS_USER_TEMPLATE.format(content=content)
        
        # Make API request
        # Note: client is already initialized with the correct base_url (text or vision)
        # We only need to provide the endpoint path
        try:
            response = await client.post(
                self.settings.llm_endpoint,  # e.g., "/v1/chat/completions"
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens or default_max_tokens,
                    "temperature": temperature or default_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Extract response
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            
            return {
                "analysis": {
                    "description": analysis_text,
                    "model_type": model_type,
                },
                "model": model,
                "tokens_used": tokens_used,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"LLM request failed with status {e.response.status_code}: {e.response.text}") from e
        except httpx.ConnectError as e:
            logger.error(f"LLM connection error: {e}")
            raise RuntimeError(f"Cannot connect to LLM service at {self.settings.llm_text_base_url if model_type == 'text' else self.settings.llm_vision_base_url}") from e
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}", exc_info=True)
            raise
    
    async def analyze_image(
        self,
        image_data: bytes,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an image using vision model.

        Args:
            image_data: Image binary data.
            prompt: Custom prompt (optional).

        Returns:
            Analysis result dict.
        """
        # Compress image if too large (base64 encoding increases size by ~33%)
        max_image_size = 20 * 1024 * 1024  # 20MB limit before compression
        if len(image_data) > max_image_size:
            logger.warning(f"Image size {len(image_data)} bytes exceeds limit, attempting compression")
            try:
                image_data = self._compress_image(image_data, max_size=3 * 1024 * 1024)  # Compress to 3MB
                logger.info(f"Image compressed to {len(image_data)} bytes")
            except Exception as e:
                logger.warning(f"Image compression failed: {e}, proceeding with original size")

        # Encode image to base64
        image_b64 = base64.b64encode(image_data).decode("utf-8")
        encoded_size_kb = len(image_b64) / 1024
        logger.info(f"Base64 encoded image size: {encoded_size_kb:.2f} KB")

        # Use prompts from prompts.py
        system_prompt = VISION_ANALYSIS_SYSTEM
        user_prompt = prompt or VISION_ANALYSIS_USER_DEFAULT

        # Ensure vision client is initialized
        if not self._vision_client:
            await self.initialize()

        # Check if image is still too large after compression
        if len(image_b64) > 10 * 1024 * 1024:  # 10MB base64 limit
            raise ValueError(f"Image too large even after compression ({encoded_size_kb:.2f} KB). Please provide a smaller image.")

        try:
            response = await self._vision_client.post(
                self.settings.llm_endpoint,
                json={
                    "model": self.settings.llm_vision_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}",
                                        "detail": "low"  # Use low detail for large images
                                    },
                                },
                            ],
                        },
                    ],
                    "max_tokens": 2048,  # Reduce max tokens for context space
                    "temperature": self.settings.llm_vision_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()

            result = response.json()
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)

            logger.info(f"Vision analysis completed, tokens used: {tokens_used}")

            return {
                "analysis": {
                    "description": analysis_text,
                    "model_type": "vision",
                },
                "model": self.settings.llm_vision_model,
                "tokens_used": tokens_used,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                error_msg = e.response.text
                if "corrupt" in error_msg.lower() or "header" in error_msg.lower():
                    logger.warning(f"Image analysis rejected by LLM (likely corrupt image): {error_msg}")
                    # Special return to signal fallback needed
                    return {
                        "analysis": {"description": f"[IMAGE_CORRUPT_OR_INVALID] {error_msg}", "model_type": "vision"},
                        "error_type": "image_decode_failed",
                        "success": False
                    }
            
            if "context" in e.response.text.lower() and "overflow" in e.response.text.lower():
                raise ValueError(f"Image analysis failed: Image is too large or complex for the vision model's context window ({self.settings.llm_context_length} tokens). Try: 1) Using a smaller image, 2) Reducing image quality, or 3) Using a model with larger context") from e
            logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"LLM request failed with status {e.response.status_code}: {e.response.text}") from e
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}", exc_info=True)
            raise

    @staticmethod
    def _compress_image(image_data: bytes, max_size: int = 3 * 1024 * 1024) -> bytes:
        """
        Compress image using Pillow to reduce file size.

        Args:
            image_data: Original image bytes.
            max_size: Maximum target size in bytes.

        Returns:
            Compressed image bytes.
        """
        try:
            from io import BytesIO
            from PIL import Image

            img = Image.open(BytesIO(image_data))

            # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparent images
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Calculate target dimensions (reduce by up to 50%)
            original_width, original_height = img.size
            scale_factor = min(1.0, (max_size / len(image_data)) ** 0.5)  # Square root for area
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)

            # Resize with high quality
            if new_width < original_width or new_height < original_height:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Compress with progressive JPEG
            output = BytesIO()
            img.save(output, format='JPEG', quality=75, optimize=True, progressive=True)
            compressed_data = output.getvalue()

            return compressed_data
        except ImportError:
            # Pillow not available, return original
            return image_data
        except Exception as e:
            # Compression failed, return original
            return image_data
    
    async def start_batch_analysis(
        self,
        files: List[Dict[str, Any]],
        model_type: str = "text",
        files_db_path: Optional[str] = None,
        extraction_dir: Optional[str] = None,
    ) -> str:
        """
        Start batch analysis of files.
        
        Args:
            files: List of file info dicts with 'path' key.
            model_type: 'text' or 'vision'.
            files_db_path: Optional path to _files.db for persisting results.
            extraction_dir: Optional file extraction directory to resolve relative paths.
        
        Returns:
            Job ID for tracking progress.
        """
        job_id = str(uuid.uuid4())
        
        self._jobs[job_id] = {
            "status": "running",
            "progress": 0.0,
            "files_processed": 0,
            "files_total": len(files),
            "results": [],
            "errors": [],
        }
        
        # Start background task
        asyncio.create_task(self._run_batch_analysis(job_id, files, model_type, files_db_path, extraction_dir))
        
        return job_id
    
    async def _run_batch_analysis(
        self,
        job_id: str,
        files: List[Dict[str, Any]],
        model_type: str,
        files_db_path: Optional[str] = None,
        extraction_dir: Optional[str] = None,
    ):
        """Run batch analysis in background and optionally persist to SQLite."""
        # Image file extensions that should use vision model
        IMAGE_EXTENSIONS = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
            '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'
        }

        try:
            total = len(files)
            for i, file_info in enumerate(files):
                file_path = file_info.get("path") or file_info.get("file_path", "")
                try:
                    if not file_path:
                        continue

                    # Resolve actual path if relative
                    actual_path = file_path
                    if extraction_dir and not Path(file_path).is_absolute():
                        actual_path = str(Path(extraction_dir) / file_path)

                    # Auto-detect if file is an image based on extension
                    file_ext = Path(actual_path).suffix.lower()
                    is_image = file_ext in IMAGE_EXTENSIONS

                    if is_image:
                        # Read as binary and use vision model
                        logger.info(f"Detected image file: {actual_path}, using vision model")
                        try:
                            with open(actual_path, 'rb') as f:
                                image_data = f.read()
                            result = await self.analyze_image(image_data)
                        except Exception as e:
                            logger.warning(f"Failed to analyze {actual_path} as image: {e}, falling back to text analysis")
                            # Fallback to text analysis
                            content = await self.read_file_content(actual_path)
                            result = await self.analyze(content, model_type)
                    else:
                        # Read as text and use specified model
                        content = await self.read_file_content(actual_path)
                        result = await self.analyze(content, model_type)

                    analysis = result.get("analysis", {})
                    description = analysis.get("description", "")

                    self._jobs[job_id]["results"].append({
                        "file_path": file_path,
                        "analysis": analysis,
                    })

                    # Persist to C++ SQLite _files.db if path provided
                    if files_db_path and description:
                        keywords = ", ".join(analysis.get("keywords", []))
                        model_used = result.get("model", "")
                        self.persist_to_files_db(
                            db_path=files_db_path,
                            file_path=file_path,
                            description=description,
                            summary=analysis.get("summary") or description[:200],
                            keywords=keywords,
                            model_used=model_used,
                        )
                except Exception as e:
                    logger.error(f"Failed to analyze {file_path}: {e}", exc_info=True)
                    self._jobs[job_id]["errors"].append(f"{file_path}: {str(e)}")

                self._jobs[job_id]["files_processed"] = i + 1
                self._jobs[job_id]["progress"] = (i + 1) / total

            self._jobs[job_id]["status"] = "completed"
        except Exception as e:
            logger.error(f"Batch analysis job {job_id} failed: {e}")
            self._jobs[job_id]["status"] = "failed"
            self._jobs[job_id]["errors"].append(str(e))
    
    async def get_batch_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a batch analysis job."""
        return self._jobs.get(job_id)
    
    def _ensure_file_descriptions_schema(self, conn: sqlite3.Connection):
        """Ensure file_descriptions table and its columns exist."""
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_descriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                description TEXT,
                summary TEXT,
                keywords TEXT,
                model_used TEXT,
                is_relevant INTEGER DEFAULT 1,
                created_at INTEGER
            )
        """)
        
        # Check for is_relevant column
        cur.execute("PRAGMA table_info(file_descriptions)")
        columns = [col[1] for col in cur.fetchall()]
        if "is_relevant" not in columns:
            logger.info("Migrating table: adding is_relevant column")
            cur.execute("ALTER TABLE file_descriptions ADD COLUMN is_relevant INTEGER DEFAULT 1")

    def set_file_relevance(self, db_path: str, file_path: str, is_relevant: bool) -> bool:
        """
        Mark a file as relevant or irrelevant for the case report.
        """
        if not db_path or not Path(db_path).exists():
            logger.warning(f"set_file_relevance: DB not found at {db_path}")
            return False
            
        try:
            with sqlite3.connect(db_path, timeout=10) as conn:
                # SELF-HEALING: Ensure schema is correct before update
                self._ensure_file_descriptions_schema(conn)
                
                cur = conn.cursor()
                cur.execute(
                    "UPDATE file_descriptions SET is_relevant = ? WHERE file_path = ?",
                    (1 if is_relevant else 0, file_path)
                )
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to set file relevance for {file_path}: {e}")
            return False

    async def get_status(self) -> Dict[str, Any]:
        """
        Get the status of LLM services.
        
        Returns:
            Status information dict.
        """
        text_available = await self.check_model_status("text")
        vision_available = await self.check_model_status("vision")
        
        return {
            "status": "available" if (text_available or vision_available) else "unavailable",
            "text_model": {
                "name": self.settings.llm_text_model,
                "base_url": self.settings.llm_text_base_url,
                "available": text_available,
            },
            "vision_model": {
                "name": self.settings.llm_vision_model,
                "base_url": self.settings.llm_vision_base_url,
                "available": vision_available,
            },
        }
    
    async def analyze_event_cluster(
        self,
        event_data: Dict[str, Any],
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an event cluster using LLM.

        Args:
            event_data: Event cluster data with event_type, file_path, description, etc.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        # Ensure service is initialized
        if not self._initialized:
            logger.info("LLM service not initialized, initializing now...")
            await self.initialize()

        # Build event cluster content for analysis
        event_type = event_data.get("event_type", "UNKNOWN")
        file_path = event_data.get("file_path", "")
        description = event_data.get("description", "")
        timestamp = event_data.get("timestamp", 0)
        time_window = event_data.get("time_window", 0)

        # Count events in description for context
        event_count = description.count('\n') + 1 if description else 0

        # Select model settings
        client = self._text_client
        if not client:
            raise RuntimeError("Text model client not initialized")
        model = self.settings.llm_text_model
        default_max_tokens = self.settings.llm_text_max_tokens
        default_temperature = self.settings.llm_text_temperature
        logger.info(f"Using text model: {model} for event cluster analysis")

        # Build prompt using professional Chinese prompts
        system_prompt = EVENT_CLUSTER_ANALYSIS_SYSTEM

        # Use custom prompt if provided, otherwise use default template
        if prompt and "重新" in prompt:
            # Reanalysis mode
            user_prompt = EVENT_CLUSTER_REANALYSIS_PROMPT.format(
                case_context=prompt,
                event_type=event_type,
                time_window=time_window,
                event_count=event_count,
                description=description
            )
        elif prompt:
            # Custom prompt provided
            user_prompt = f"{prompt}\n\n事件类型：{event_type}\n时间窗口：{time_window}\n事件数量：{event_count}\n事件描述：\n{description}"
        else:
            # Default analysis mode
            user_prompt = EVENT_CLUSTER_ANALYSIS_DEFAULT.format(
                event_type=event_type,
                time_window=time_window,
                event_count=event_count,
                description=description
            )
        
        # Make API request
        try:
            response = await client.post(
                self.settings.llm_endpoint,  # e.g., "/v1/chat/completions"
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": max_tokens or default_max_tokens,
                    "temperature": temperature or default_temperature,
                },
                headers={"Authorization": f"Bearer {self.settings.llm_api_key}"} if self.settings.llm_api_key else {},
            )
            response.raise_for_status()
            
            result = response.json()

            # Extract response
            analysis_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            tokens_used = result.get("usage", {}).get("total_tokens", 0)

            # Parse structured analysis from LLM response
            parsed_analysis = self._parse_event_cluster_analysis(analysis_text)

            return {
                "analysis": {
                    "summary": parsed_analysis.get("summary", ""),
                    "description": parsed_analysis.get("description", analysis_text),
                    "keywords": parsed_analysis.get("keywords", []),
                    "is_relevant": parsed_analysis.get("is_relevant", True),
                },
                "model": model,
                "tokens_used": tokens_used,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"LLM request failed with status {e.response.status_code}: {e.response.text}") from e
        except httpx.ConnectError as e:
            logger.error(f"LLM connection error: {e}")
            raise RuntimeError(f"Cannot connect to LLM service at {self.settings.llm_text_base_url}") from e
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}", exc_info=True)
            raise

    def _parse_event_cluster_analysis(self, analysis_text: str) -> Dict[str, Any]:
        """
        Parse LLM analysis response into structured fields.

        Args:
            analysis_text: Raw LLM response text.

        Returns:
            Dict with keys: summary, description, keywords, is_relevant.
        """
        import re

        result = {
            "summary": "",
            "description": analysis_text,
            "keywords": [],
            "is_relevant": True,
        }

        if not analysis_text:
            return result

        lines = analysis_text.split('\n')
        current_section = None
        content_parts = []

        for line in lines:
            line = line.strip()

            # Detect summary section
            if re.match(r'^(简要总结|总结|摘要|summary)', line, re.IGNORECASE):
                if content_parts:
                    if current_section == "description":
                        result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "summary"
                continue

            # Detect detailed description section
            elif re.match(r'^(详细分析|描述|详细描述|description|分析)', line, re.IGNORECASE):
                if content_parts and current_section == "summary":
                    result["summary"] = '\n'.join(content_parts).strip()
                    content_parts = []
                elif content_parts and current_section == "description":
                    result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "description"
                continue

            # Detect keywords section
            elif re.match(r'^(关键词|keywords)', line, re.IGNORECASE):
                if content_parts:
                    if current_section == "summary":
                        result["summary"] = '\n'.join(content_parts).strip()
                    elif current_section == "description":
                        result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "keywords"
                # Extract keywords from same line if present
                keywords_match = re.search(r'[:：]\s*(.+)', line)
                if keywords_match:
                    keywords_text = keywords_match.group(1)
                    result["keywords"] = [kw.strip() for kw in re.split(r'[,，、]', keywords_text) if kw.strip()]
                continue

            # Detect forensic value section
            elif re.match(r'^(取证价值|价值评估|forensic.*value)', line, re.IGNORECASE):
                if content_parts and current_section == "description":
                    result["description"] = '\n'.join(content_parts).strip()
                    content_parts = []
                current_section = "value"
                continue

            # Process content based on current section
            if current_section == "keywords":
                # Extract keywords from content lines
                if line and not line.startswith('-') and not line.startswith('•'):
                    keywords_match = re.search(r'[:：]\s*(.+)', line)
                    if keywords_match:
                        keywords_text = keywords_match.group(1)
                        result["keywords"].extend([kw.strip() for kw in re.split(r'[,，、]', keywords_text) if kw.strip()])
                    else:
                        result["keywords"].extend([kw.strip() for kw in re.split(r'[,，、]', line) if kw.strip()])
            elif current_section == "value":
                # Check if value is low
                if '低' in line or '无关' in line:
                    result["is_relevant"] = False
            elif current_section in ["summary", "description"]:
                content_parts.append(line)

        # Handle remaining content
        if content_parts:
            if current_section == "summary":
                result["summary"] = '\n'.join(content_parts).strip()
            elif current_section == "description" or not current_section:
                result["description"] = '\n'.join(content_parts).strip()

        # Fallback: if no summary found, use first 200 chars of description
        if not result["summary"] and result["description"]:
            result["summary"] = result["description"][:200] + ("..." if len(result["description"]) > 200 else "")

        # Clean up keywords (deduplicate and limit)
        if result["keywords"]:
            seen = set()
            unique_keywords = []
            for kw in result["keywords"]:
                if kw.lower() not in seen:
                    seen.add(kw.lower())
                    unique_keywords.append(kw)
            result["keywords"] = unique_keywords[:5]

        return result
