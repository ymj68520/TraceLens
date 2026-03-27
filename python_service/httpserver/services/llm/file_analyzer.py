"""
File Analyzer Module - File content analysis operations.

This module handles:
- Single file analysis (text and image)
- Batch file analysis with background processing
- File content reading and preparation
"""

import asyncio
import base64
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ...config import Settings
from ...prompts import (
    TEXT_ANALYSIS_SYSTEM,
    TEXT_ANALYSIS_USER_TEMPLATE,
    VISION_ANALYSIS_SYSTEM,
    VISION_ANALYSIS_USER_DEFAULT,
)

logger = logging.getLogger(__name__)


class FileAnalyzer:
    """
    Handles file analysis operations for LLM service.

    Supports:
    - Text file analysis
    - Image file analysis
    - Batch processing with job tracking
    """

    # Image file extensions for auto-detection
    IMAGE_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
        '.svg', '.ico', '.heic', '.heif', '.raw', '.cr2', '.nef', '.arw'
    }

    def __init__(self, settings: Settings):
        """
        Initialize file analyzer.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self._jobs: Dict[str, Dict[str, Any]] = {}

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

    async def analyze_file(
        self,
        content: str,
        text_client: httpx.AsyncClient,
        vision_client: httpx.AsyncClient,
        model_type: str = "text",
        prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Analyze content using LLM.

        Args:
            content: Content to analyze.
            text_client: HTTP client for text model.
            vision_client: HTTP client for vision model.
            model_type: 'text' or 'vision'.
            prompt: Custom prompt (optional).
            max_tokens: Max response tokens (optional).
            temperature: Model temperature (optional).

        Returns:
            Analysis result dict.
        """
        # Select model settings
        if model_type == "text":
            client = text_client
            if not client:
                raise RuntimeError("Text model client not initialized")
            model = self.settings.llm_text_model
            default_max_tokens = self.settings.llm_text_max_tokens
            default_temperature = self.settings.llm_text_temperature
            logger.info(f"Using text model: {model} at {self.settings.llm_text_base_url}")
        else:
            client = vision_client
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
        try:
            response = await client.post(
                self.settings.llm_endpoint,
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
            base_url = self.settings.llm_text_base_url if model_type == 'text' else self.settings.llm_vision_base_url
            raise RuntimeError(f"Cannot connect to LLM service at {base_url}") from e
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}", exc_info=True)
            raise

    async def analyze_image(
        self,
        image_data: bytes,
        vision_client: httpx.AsyncClient,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze an image using vision model.

        Args:
            image_data: Image binary data.
            vision_client: HTTP client for vision model.
            prompt: Custom prompt (optional).

        Returns:
            Analysis result dict.
        """
        # Compress image if too large
        max_image_size = 20 * 1024 * 1024  # 20MB limit before compression
        if len(image_data) > max_image_size:
            logger.warning(f"Image size {len(image_data)} bytes exceeds limit, attempting compression")
            try:
                image_data = self._compress_image(image_data, max_size=3 * 1024 * 1024)
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

        # Check if image is still too large after compression
        if len(image_b64) > 10 * 1024 * 1024:  # 10MB base64 limit
            raise ValueError(f"Image too large even after compression ({encoded_size_kb:.2f} KB)")

        try:
            response = await vision_client.post(
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
                                        "detail": "low"
                                    },
                                },
                            ],
                        },
                    ],
                    "max_tokens": 2048,
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
                    return {
                        "analysis": {"description": f"[IMAGE_CORRUPT_OR_INVALID] {error_msg}", "model_type": "vision"},
                        "error_type": "image_decode_failed",
                        "success": False
                    }

            if "context" in e.response.text.lower() and "overflow" in e.response.text.lower():
                raise ValueError(f"Image analysis failed: Image too large for context window") from e

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

            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Calculate target dimensions
            original_width, original_height = img.size
            scale_factor = min(1.0, (max_size / len(image_data)) ** 0.5)
            new_width = int(original_width * scale_factor)
            new_height = int(original_height * scale_factor)

            # Resize if needed
            if new_width < original_width or new_height < original_height:
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Compress with progressive JPEG
            output = BytesIO()
            img.save(output, format='JPEG', quality=75, optimize=True, progressive=True)
            return output.getvalue()
        except ImportError:
            return image_data
        except Exception:
            return image_data

    async def start_batch_analysis(
        self,
        files: List[Dict[str, Any]],
        text_client: httpx.AsyncClient,
        vision_client: httpx.AsyncClient,
        model_type: str = "text",
        files_db_path: Optional[str] = None,
        extraction_dir: Optional[str] = None,
        persist_callback: Optional[callable] = None,
    ) -> str:
        """
        Start batch analysis of files.

        Args:
            files: List of file info dicts with 'path' key.
            text_client: HTTP client for text model.
            vision_client: HTTP client for vision model.
            model_type: 'text' or 'vision'.
            files_db_path: Optional path to _files.db for persisting results.
            extraction_dir: Optional file extraction directory.
            persist_callback: Optional callback for persisting results.

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
        asyncio.create_task(
            self._run_batch_analysis(
                job_id, files, text_client, vision_client,
                model_type, files_db_path, extraction_dir, persist_callback
            )
        )

        return job_id

    async def _run_batch_analysis(
        self,
        job_id: str,
        files: List[Dict[str, Any]],
        text_client: httpx.AsyncClient,
        vision_client: httpx.AsyncClient,
        model_type: str,
        files_db_path: Optional[str] = None,
        extraction_dir: Optional[str] = None,
        persist_callback: Optional[callable] = None,
    ):
        """Run batch analysis in background."""
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

                    # Auto-detect if file is an image
                    file_ext = Path(actual_path).suffix.lower()
                    is_image = file_ext in self.IMAGE_EXTENSIONS

                    if is_image:
                        logger.info(f"Detected image file: {actual_path}, using vision model")
                        try:
                            with open(actual_path, 'rb') as f:
                                image_data = f.read()
                            result = await self.analyze_image(image_data, vision_client)
                        except Exception as e:
                            logger.warning(f"Failed to analyze {actual_path} as image: {e}, falling back to text")
                            content = await self.read_file_content(actual_path)
                            result = await self.analyze_file(content, text_client, vision_client, model_type)
                    else:
                        content = await self.read_file_content(actual_path)
                        result = await self.analyze_file(content, text_client, vision_client, model_type)

                    analysis = result.get("analysis", {})
                    description = analysis.get("description", "")

                    self._jobs[job_id]["results"].append({
                        "file_path": file_path,
                        "analysis": analysis,
                    })

                    # Persist results if callback provided
                    if persist_callback and description:
                        await persist_callback(
                            db_path=files_db_path,
                            file_path=file_path,
                            description=description,
                            summary=analysis.get("summary") or description[:200],
                            keywords=", ".join(analysis.get("keywords", [])),
                            model_used=result.get("model", ""),
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
