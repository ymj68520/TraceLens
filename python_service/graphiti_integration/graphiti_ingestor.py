"""
Graphiti ingestor module for batch ingestion into the knowledge graph.
"""

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .llm_patch import apply_patch  # noqa: F401 — must run before graphiti_core
apply_patch()

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

from . import episode_gate
from .chinese_prompts import chinese_prompt_library
from .config import GraphitiConfig
from .exceptions import IngestionError
from .toon_transformer import EpisodeData, TOONTransformer

logger = logging.getLogger(__name__)


# Custom extraction guidance injected into Graphiti's entity/edge prompts via
# the ``custom_extraction_instructions`` parameter of ``add_episode``.
#
# Why this matters: Graphiti's default ``extract_json`` prompt actively tells
# the LLM to NEVER extract dates, hashes, IDs, paths, IPs, hostnames, etc.,
# treating them as "generic field values". That is the single biggest reason
# forensic knowledge graphs end up nearly empty — the most forensically
# relevant entities (usernames, hostnames, IPs, file paths, registry keys,
# USB serials, URLs) are exactly what the default prompt discards.
#
# This instruction re-enables them and tells the extractor to also model
# relationships (e.g. user LOGGED_IN_AT host, process WROTE file), which is
# what populates the RELATES_TO edges the frontend visualises.
FORENSIC_EXTRACTION_INSTRUCTIONS = """
This is a DIGITAL FORENSICS knowledge graph. Treat the content as a forensic
analysis record of evidence extracted from a disk image / system artifact.

EXTRACT these entities liberally (they are NOT "generic values" here):
- Usernames, account names, group names (e.g. "Administrator", "root", "nobody")
- Hostnames, computer names, domain names, workgroup names
- IP addresses, MAC addresses, SSIDs, network share paths
- File paths and file names (full paths are meaningful identifiers here)
- Registry key paths, service names, scheduled task names
- Executable / process names (e.g. "cmd.exe", "powershell.exe", "svchost.exe")
- URLs, domains, email addresses, phone numbers
- USB device names, vendor/product IDs, serial numbers
- MD5 / SHA hashes and file-inode references as Identifier entities
- Application / package names and versions
- Event IDs, log source names (e.g. "Security", "Syslog")

ALSO extract RELATIONSHIPS between these entities when the content supports it,
using screaming-snake-case predicates such as:
- USER_ACCOUNT ACCESSED FILE
- PROCESS EXECUTED_FILE
- HOST CONNECTED_TO IP / DOMAIN
- USER LOGGED_IN_FROM IP
- DEVICE_MOUNTED_AS DRIVE
- APPLICATION ACCESSED URL
- REGISTRY_KEY REFERENCES PATH
- HASH_IDENTIFIES FILE

Prefer concrete, named entities over generic words. Every entity that is
named or uniquely identifiable in the content SHOULD be extracted.
""".strip()


@dataclass
class IngestionResult:
    """Result of an ingestion operation."""
    
    total_episodes: int = 0
    successful: int = 0
    failed: int = 0
    errors: list = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_episodes == 0:
            return 0.0
        return (self.successful / self.total_episodes) * 100


class GraphitiIngestor:
    """
    Handles batch ingestion of episodes into Graphiti knowledge graph.
    
    Uses the Graphiti SDK to add episodes that will be processed into
    nodes and edges in the graph database.
    """
    
    def __init__(
        self,
        config: GraphitiConfig,
        graphiti_client: Optional[Graphiti] = None,
    ):
        """
        Initialize ingestor.
        
        Args:
            config: Graphiti configuration.
            graphiti_client: Optional pre-configured Graphiti client.
        """
        self.config = config
        self._client = graphiti_client
        self._owned_llm_client = None
        self._owned_embedder = None
        self._initialized = False
        # add_episode replaces self.driver whenever the group id differs from
        # the driver's database name, and Neo4jDriver.clone is a no-op. One
        # shared client therefore cannot run two episodes at once. Slots above
        # the first each own a Graphiti instance; they are closed with this one.
        self._worker_clients: list = []
    
    def _create_llm_client(self) -> OpenAIGenericClient:
        """Create LLM client configured for local or OpenAI."""
        llm_config = LLMConfig(
            api_key=self.config.llm_api_key,
            model=self.config.llm_model,
            small_model=self.config.llm_model,  # Use same model for both
            base_url=self.config.llm_base_url,
        )
        return OpenAIGenericClient(config=llm_config)
    
    def _create_embedder(self) -> OpenAIEmbedder:
        """Create embedder - uses local LLM or OpenAI based on config."""
        if self.config.use_local_llm:
            # Use local LLM for embeddings too. EMBEDDING_BASE_URL overrides
            # the endpoint so the embedder can differ from the chat LLM
            # (e.g. cloud chat + local nomic embeddings).
            embedder_base = self.config.embedder_base_url or self.config.llm_base_url
            embedder_base = embedder_base.rstrip("/")
            if not embedder_base.endswith("/v1"):
                embedder_base += "/v1"
            embedder_config = OpenAIEmbedderConfig(
                api_key=self.config.embedder_api_key or self.config.llm_api_key or "local",
                embedding_model=self.config.embedder_model,  # Configured embedding model
                embedding_dim=self.config.embedder_dim,
                base_url=embedder_base,
            )
        else:
            # Use OpenAI
            embedder_config = OpenAIEmbedderConfig(
                api_key=self.config.embedder_api_key,
                embedding_model=self.config.embedder_model,
                embedding_dim=self.config.embedder_dim,
            )
        return OpenAIEmbedder(config=embedder_config)
    
    def _validate_and_prepare_episode(
        self,
        episode: EpisodeData,
    ) -> tuple[str, bool]:
        """
        Validate episode token count and prepare the body for ingestion.

        Renders the episode to extraction-friendly text (see
        ``_render_episode_for_extraction``) and truncates it if it exceeds the
        configured token budget. Kept as a helper so callers that need the
        prepared body independently of ``ingest_episode`` get the same
        text-rendering + truncation behaviour.

        Args:
            episode: The episode data to validate.

        Returns:
            Tuple of (prepared_body, was_truncated).
        """
        rendered_body, _ = self._render_episode_for_extraction(episode)
        max_tokens = self.config.max_episode_tokens

        estimated = TOONTransformer.estimate_episode_tokens(rendered_body)
        if estimated <= max_tokens:
            return rendered_body, False

        logger.warning(
            f"Episode '{episode.name}' exceeds token limit: "
            f"~{estimated} tokens > {max_tokens} max"
        )
        prepared = TOONTransformer.truncate_if_needed(rendered_body, max_tokens)
        new_estimate = TOONTransformer.estimate_episode_tokens(prepared)
        logger.info(
            f"Truncated episode '{episode.name}': "
            f"{estimated} -> {new_estimate} tokens"
        )
        return prepared, True

    @staticmethod
    def _render_episode_for_extraction(
        episode: EpisodeData,
    ) -> tuple[str, "EpisodeType"]:
        """Render an episode body in the form Graphiti's extractor consumes best.

        The episode_body stored in EpisodeData is a JSON string. Feeding it to
        Graphiti as ``source=EpisodeType.json`` selects the ``extract_json``
        prompt, whose instructions ("NEVER extract dates/hashes/IDs/generic field
        values", "extract the primary entity the JSON represents") discard most
        forensically relevant tokens and yield very few entities.

        Instead we render the JSON to readable key:value text and ingest as
        ``EpisodeType.text``, which uses ``extract_text`` — a prompt that
        extracts named entities from free-form text far more liberally.

        The original structured fields are preserved as ``Field: value`` lines
        so the extractor still sees paths, hashes, usernames, IPs, etc. as
        first-class content rather than "generic field values".

        Returns:
            Tuple of (rendered_body, EpisodeType).
        """
        body = episode.episode_body or ""
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                lines = []
                # Header gives the extractor strong semantic context.
                title = episode.name or data.get("category") or "Forensic analysis"
                lines.append(f"# {title}")
                for key, value in data.items():
                    if value is None or value == "":
                        continue
                    if isinstance(value, (dict, list)):
                        value = json.dumps(value, ensure_ascii=False)
                    lines.append(f"{key}: {value}")
                rendered = "\n".join(lines)
                return rendered, EpisodeType.text
            # Non-dict JSON (list/scalar): fall back to the raw text.
            return body, EpisodeType.text
        except (json.JSONDecodeError, TypeError):
            # Already plain text — ingest as text unchanged.
            return body, EpisodeType.text

    async def initialize(self) -> None:
        """
        Initialize Graphiti client and database indices.

        This should be called before ingestion to ensure the graph
        database is ready.
        """
        if self._client is None:
            logger.info(f"Connecting to Neo4j at {self.config.neo4j_uri}")
            
            if self.config.use_local_llm:
                logger.info(f"Using local LLM at {self.config.llm_base_url}")
                logger.info(f"Model: {self.config.llm_model}")
                
                llm_client = self._create_llm_client()
                embedder = self._create_embedder()
                self._owned_llm_client = llm_client
                self._owned_embedder = embedder
                
                # Create reranker using the same LLM client
                llm_config = LLMConfig(
                    api_key=self.config.llm_api_key,
                    model=self.config.llm_model,
                    base_url=self.config.llm_base_url,
                )
                cross_encoder = OpenAIRerankerClient(
                    client=llm_client,
                    config=llm_config,
                )
                
                self._client = Graphiti(
                    uri=self.config.neo4j_uri,
                    user=self.config.neo4j_user,
                    password=self.config.neo4j_password,
                    llm_client=llm_client,
                    embedder=embedder,
                    cross_encoder=cross_encoder,
                    prompt_library=chinese_prompt_library(),
                )
            else:
                # Default OpenAI-based configuration
                self._client = Graphiti(
                    uri=self.config.neo4j_uri,
                    user=self.config.neo4j_user,
                    password=self.config.neo4j_password,
                    prompt_library=chinese_prompt_library(),
                )
        
        # Build indices and constraints
        logger.info("Building Graphiti indices and constraints...")
        await self._client.build_indices_and_constraints()
        self._initialized = True
        logger.info("Graphiti initialized successfully")

    async def _make_worker_client(self):
        """A Graphiti instance that does not share our driver.

        The primary client is the one ``initialize`` built. Every extra slot
        gets its own driver so concurrent ``add_episode`` calls cannot swap
        each other's database out from under them. LLM and embedder clients
        are stateless HTTP pools and are shared.
        """
        if self._client is None or not self.config.use_local_llm:
            return None
        llm_config = LLMConfig(
            api_key=self.config.llm_api_key,
            model=self.config.llm_model,
            base_url=self.config.llm_base_url,
        )
        client = Graphiti(
            uri=self.config.neo4j_uri,
            user=self.config.neo4j_user,
            password=self.config.neo4j_password,
            llm_client=self._owned_llm_client,
            embedder=self._owned_embedder,
            cross_encoder=OpenAIRerankerClient(
                client=self._owned_llm_client,
                config=llm_config,
            ),
            prompt_library=chinese_prompt_library(),
        )
        await client.build_indices_and_constraints()
        return client

    async def _clients_for_concurrency(self, concurrency: int) -> list:
        """One Graphiti client per in-flight episode, the primary first.

        A real client grows extra drivers up to ``concurrency``. A stand-in
        that cannot build drivers (tests, or a caller-supplied client) is
        repeated so the batch still runs; that caller owns its own safety.
        """
        primary = getattr(self, "_client", None)
        if primary is None:
            return [None] * concurrency
        if not hasattr(self, "_worker_clients"):
            self._worker_clients = []
        while len(self._worker_clients) < concurrency - 1:
            worker = await self._make_worker_client()
            if worker is None:
                break
            self._worker_clients.append(worker)
        clients = [primary, *self._worker_clients]
        if len(clients) < concurrency:
            clients = [primary] * concurrency
        return clients[:concurrency]

    async def close(self) -> None:
        """Close owned HTTP pools and the Graphiti/Neo4j driver (D4b).

        A Graphiti instance supplied by a caller owns its own clients and is
        therefore not closed here. Clients created in ``initialize`` are
        per-ingestor owned resources and must be closed independently: one
        failure must not prevent the other resources from being released.
        """
        errors = []
        for worker in self._worker_clients:
            try:
                await worker.close()
            except Exception as exc:
                errors.append(exc)
                logger.warning("Failed to close Graphiti worker client: %s", type(exc).__name__)
        self._worker_clients = []
        for resource in (self._owned_llm_client, self._owned_embedder):
            if resource is None:
                continue
            close = getattr(resource, "aclose", None)
            if close is None:
                close = getattr(resource, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                errors.append(exc)
                logger.warning("Failed to close owned Graphiti client: %s", type(exc).__name__)
        self._owned_llm_client = None
        self._owned_embedder = None
        if self._client:
            try:
                await self._client.close()
            except Exception as exc:
                errors.append(exc)
                logger.warning("Failed to close Graphiti driver: %s", type(exc).__name__)
            finally:
                self._client = None
                self._initialized = False
        if errors:
            raise errors[0]
    
    async def ingest_episode(
        self,
        episode: EpisodeData,
        group_id: Optional[str] = None,
        client=None,
    ) -> bool:
        """
        Ingest a single episode into Graphiti.
        
        Args:
            episode: The episode data to ingest.
            group_id: Optional group ID for organizing data.
        
        Returns:
            True if successful, False otherwise.
        
        Raises:
            IngestionError: If ingestion fails after retries.
        """
        if not self._initialized:
            await self.initialize()

        group_id = group_id or self.config.group_id

        # Render the structured JSON body to extraction-friendly text first
        # (see _render_episode_for_extraction), then enforce the token limit
        # on the rendered text so very large forensic analyses don't overflow
        # the LLM context window.
        rendered_body, source_type = self._render_episode_for_extraction(episode)
        max_tokens = self.config.max_episode_tokens
        if TOONTransformer.estimate_episode_tokens(rendered_body) > max_tokens:
            rendered_body = TOONTransformer.truncate_if_needed(rendered_body, max_tokens)
            logger.debug(f"Truncated rendered body for '{episode.name}' to ~{max_tokens} tokens")

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                # Determine the episode source type and rendered body.
                #
                # Graphiti selects its extraction prompt by source:
                #   - EpisodeType.json  -> extract_json:  actively DROPS dates,
                #     hashes, IDs, paths, "generic field values". This is why the
                #     forensic graph ended up nearly empty.
                #   - EpisodeType.text  -> extract_text:  extracts entities from
                #     free-form text, which is far richer for forensic narratives.
                #
                # We therefore render the structured body to readable text and
                # ingest as text, while still passing custom_extraction_instructions
                # so the LLM keeps forensically-relevant tokens (usernames, IPs,
                # paths, hashes) that the default prompts discard.
                await (client or self._client).add_episode(
                    name=episode.name,
                    episode_body=rendered_body,
                    source_description=episode.source_description,
                    reference_time=episode.reference_time,
                    source=source_type,
                    group_id=group_id,
                    custom_extraction_instructions=FORENSIC_EXTRACTION_INSTRUCTIONS,
                )
                return True
            
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Ingestion attempt {attempt + 1}/{self.config.max_retries} "
                    f"failed for {episode.name}: {e}"
                )
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
        
        raise IngestionError(
            f"Failed to ingest episode {episode.name} after {self.config.max_retries} attempts: {last_error}"
        )

    async def _extract_episode(self, episode: EpisodeData, group_id: Optional[str], client=None):
        """Run one add_episode. Returns None on success, otherwise the error."""
        try:
            # Only a real per-slot client is passed through. Test stand-ins
            # override ingest_episode without the parameter, and the serial
            # path has no slot client at all.
            if client is not None and client is not getattr(self, "_client", None):
                await self.ingest_episode(episode, group_id, client=client)
            else:
                await self.ingest_episode(episode, group_id)
            logger.debug(f"Ingested episode: {episode.name}")
            return None
        except Exception as e:
            if isinstance(e, IngestionError):
                logger.error(f"Failed to ingest episode {episode.name}: {e}")
            else:
                logger.error(f"Unexpected error ingesting {episode.name}: {e}")
            return e

    def _record_outcome(self, episode: EpisodeData, error: Optional[BaseException], result: IngestionResult) -> None:
        if error is None:
            result.successful += 1
            return
        result.failed += 1
        result.errors.append({
            "episode": episode.name,
            "file_path": episode.file_path,
            "error": str(error),
        })

    async def _ingest_one(
        self,
        episode: EpisodeData,
        index: int,
        total: int,
        group_id: Optional[str],
        result: IngestionResult,
        *,
        run_gate: bool = True,
    ) -> bool:
        """Ingest one episode into ``result``.

        Returns False when the before-episode gate aborts the batch. The
        aborting episode and every episode after it are counted as failed.
        """
        if run_gate:
            try:
                await episode_gate.run_before_episode({
                    "index": index,
                    "total": total,
                    "group_id": group_id,
                    "episode": episode.name,
                })
            except episode_gate.GateAborted as e:
                remaining = total - index
                result.failed += remaining
                result.errors.append({
                    "episode": episode.name,
                    "file_path": episode.file_path,
                    "error": f"aborted by episode gate after {index} episode(s): {e}; "
                             f"{remaining} episode(s) not attempted",
                })
                logger.warning(
                    f"Batch ingestion aborted at episode {index + 1}/{total}: {e}"
                )
                return False

        self._record_outcome(episode, await self._extract_episode(episode, group_id), result)
        return True

    async def _report_progress(self, progress_callback, current: int, total: int) -> None:
        # Callers register either a plain function or a coroutine (the job
        # manager's _ep_progress is async); calling the async form without
        # awaiting it only builds a coroutine that is never scheduled, so the
        # reported percentage never moved.
        if not progress_callback:
            return
        outcome = progress_callback(current, total)
        if inspect.isawaitable(outcome):
            await outcome

    async def batch_ingest(
        self,
        episodes: list[EpisodeData],
        group_id: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> IngestionResult:
        """
        Ingest a batch of episodes into Graphiti.
        
        Args:
            episodes: List of episodes to ingest.
            group_id: Optional group ID for organizing data.
            progress_callback: Optional callback(current, total) for progress tracking.
        
        Returns:
            IngestionResult with statistics and any errors.
        """
        if not self._initialized:
            await self.initialize()

        result = IngestionResult(total_episodes=len(episodes))
        # _ingest_one mutates the shared result. The serial path never overlaps;
        # the concurrent path does, so every mutation takes this lock.
        result_lock = asyncio.Lock()
        # Test stand-ins and older callers construct an ingestor without a
        # GraphitiConfig; missing config keeps the historical serial loop.
        config = getattr(self, "config", None)
        try:
            concurrency = int(getattr(config, "max_concurrency", 1) or 1)
        except (TypeError, ValueError):
            concurrency = 1
        concurrency = max(1, concurrency)

        # GRAPHITI_MAX_CONCURRENCY=1 keeps the historical single-flight loop:
        # the before-episode gate runs between episodes, and an abort stops
        # the batch before any later episode starts.
        if concurrency == 1:
            for i, episode in enumerate(episodes):
                if not await self._ingest_one(episode, i, len(episodes), group_id, result):
                    break
                await self._report_progress(progress_callback, result.successful + result.failed, len(episodes))
        else:
            # The gate still runs before an episode may start, and it runs
            # one episode at a time so a GateAborted stops later episodes
            # from starting. Episodes already past the gate finish together,
            # bounded by the semaphore. Graphiti's in-group dedup assumes
            # sequential add_episode; raising this races that dedup.
            logger.info(
                "Graphiti extraction concurrency=%d for %d episode(s); "
                "in-group dedup is not serialised within this batch",
                concurrency, len(episodes),
            )
            # Acquired before the gate so at most `concurrency` episodes are
            # admitted, and released only after that episode's extraction
            # finishes. Holding it across the gate is what keeps a pause or
            # abort from racing ahead of the worker cap.
            abort_reason: Optional[BaseException] = None
            started = 0
            # One driver per in-flight episode. add_episode writes the group id
            # onto its client's driver, so a client may run one episode at a
            # time and the next episode for that client waits until it returns.
            clients = await self._clients_for_concurrency(concurrency)
            free_clients: asyncio.Queue = asyncio.Queue()
            for worker_client in clients:
                free_clients.put_nowait(worker_client)

            async def _run(index: int, episode: EpisodeData, worker_client) -> None:
                try:
                    # The gate already ran before this task was created, so the
                    # LLM call itself stays outside result_lock.
                    outcome = await self._extract_episode(episode, group_id, client=worker_client)
                    async with result_lock:
                        self._record_outcome(episode, outcome, result)
                        completed = result.successful + result.failed
                    await self._report_progress(progress_callback, completed, len(episodes))
                finally:
                    free_clients.put_nowait(worker_client)

            pending: set[asyncio.Task] = set()
            for i, episode in enumerate(episodes):
                worker_client = await free_clients.get()
                try:
                    await episode_gate.run_before_episode({
                        "index": i,
                        "total": len(episodes),
                        "group_id": group_id,
                        "episode": episode.name,
                    })
                except episode_gate.GateAborted as e:
                    free_clients.put_nowait(worker_client)
                    abort_reason = e
                    break
                except Exception:
                    free_clients.put_nowait(worker_client)
                    raise
                started = i + 1
                pending.add(asyncio.create_task(_run(i, episode, worker_client)))

            if pending:
                done, _ = await asyncio.wait(pending)
                for task in done:
                    task.result()

            if abort_reason is not None:
                remaining = len(episodes) - started
                async with result_lock:
                    result.failed += remaining
                result.errors.append({
                    "episode": episodes[started].name,
                    "file_path": episodes[started].file_path,
                    "error": f"aborted by episode gate after {started} episode(s): {abort_reason}; "
                             f"{remaining} episode(s) not attempted",
                })
                logger.warning(
                    f"Batch ingestion aborted at episode {started + 1}/{len(episodes)}: {abort_reason}"
                )

        logger.info(
            f"Batch ingestion complete: {result.successful}/{result.total_episodes} "
            f"successful ({result.success_rate:.1f}%)"
        )
        
        return result
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
