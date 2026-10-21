"""Unit tests for the Simplified-Chinese graphiti prompt overrides.

Guards the three invariants the Chinese-override layer depends on:
1. The composed library shadows exactly the prompt functions on the live
   add_episode path (combined extraction + both batch summary variants) and
   still passes graphiti's structural validation.
2. Rendered prompts keep every context section the pipeline injects — above
   all <CUSTOM INSTRUCTIONS>, which carries FORENSIC_EXTRACTION_INSTRUCTIONS.
   Dropping it would silently revert forensic extraction to graphiti's
   discard-paths-and-hashes default.
3. Every Graphiti() construction site in GraphitiIngestor receives the same
   prompt library, so concurrent worker clients cannot ingest in English
   while the primary client ingests in Chinese.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import graphiti_core  # noqa: F401
    from graphiti_core.prompts.lib import validate_prompt_library

    _HAS_GRAPHITI = True
except ImportError:
    _HAS_GRAPHITI = False

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

pytestmark = pytest.mark.skipif(not _HAS_GRAPHITI, reason="graphiti-core not installed")


@pytest.fixture
def library():
    from graphiti_integration.chinese_prompts import chinese_prompt_library

    lib = chinese_prompt_library()
    assert lib is not None
    return lib


def _combined_context(**overrides):
    context = {
        "entity_types": [{"entity_type_id": 0, "entity_type_name": "Entity"}],
        "edge_types": [],
        "strict_edge_types": False,
        "custom_extraction_instructions": "FORENSIC POLICY MARKER",
        "previous_episodes": [{"content": "prior", "timestamp": None}],
        "episode_content": "brndlog.txt MD5 8ac346e35f6784d1a9208a098a4d7119",
    }
    context.update(overrides)
    return context


def _summaries_context(**overrides):
    context = {
        "entities": [
            {"name": "brndlog.txt", "summary": "", "entity_types": ["Entity"], "attributes": {}}
        ],
        "episode_content": "Internet Explorer branding setup generated brndlog.txt.",
        "previous_episodes": [],
        "entity_type_descriptions": {},
    }
    context.update(overrides)
    return context


class TestLibraryComposition:
    def test_library_passes_graphiti_validation(self, library):
        validate_prompt_library(library)

    def test_library_is_cached_singleton(self):
        from graphiti_integration.chinese_prompts import chinese_prompt_library

        assert chinese_prompt_library() is chinese_prompt_library()


class TestCombinedExtractionPrompt:
    def test_messages_are_system_then_user(self, library):
        messages = library.extract_nodes_and_edges.extract_message(
            _combined_context()
        ).as_messages()
        assert messages[0].role == "system"
        assert messages[1].role == "user"

    def test_requires_simplified_chinese_facts(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context()
        ).as_messages()[1].content
        assert "简体中文" in content

    def test_keeps_forensic_identifiers_verbatim_rule(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context()
        ).as_messages()[1].content
        assert "保留来源文本的原文" in content
        assert "SCREAMING_SNAKE_CASE" in content

    def test_custom_instructions_section_passthrough(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context()
        ).as_messages()[1].content
        assert "<CUSTOM INSTRUCTIONS>" in content
        assert "FORENSIC POLICY MARKER" in content
        # The precedence rule must survive translation: custom instructions win.
        assert "以 CUSTOM INSTRUCTIONS 为准" in content

    def test_custom_instructions_absent_when_empty(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context(custom_extraction_instructions=None)
        ).as_messages()[1].content
        assert "<CUSTOM INSTRUCTIONS>" not in content

    def test_context_sections_rendered(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context()
        ).as_messages()[1].content
        assert "<ENTITY TYPES>" in content
        assert "brndlog.txt MD5 8ac346e35f6784d1a9208a098a4d7119" in content
        assert "<PREVIOUS MESSAGES>" in content
        assert "<CURRENT MESSAGES>" in content

    def test_strict_edge_types_rule(self, library):
        content = library.extract_nodes_and_edges.extract_message(
            _combined_context(
                edge_types=[
                    {
                        "fact_type_name": "WROTE_FILE",
                        "fact_type_signatures": [("Entity", "Entity")],
                        "fact_type_description": "Process wrote a file.",
                    }
                ],
                strict_edge_types=True,
            )
        ).as_messages()[1].content
        assert "<FACT TYPES>" in content
        assert "WROTE_FILE" in content
        assert "不要新造 relation_type" in content


class TestSummaryPrompts:
    @pytest.mark.parametrize(
        "builder_name",
        ["extract_summaries_batch", "extract_entity_summaries_from_episodes"],
    )
    def test_requires_simplified_chinese(self, library, builder_name):
        builder = getattr(library.extract_nodes, builder_name)
        content = builder(_summaries_context()).as_messages()[1].content
        assert "简体中文" in content

    @pytest.mark.parametrize(
        "builder_name,messages_section",
        [
            ("extract_summaries_batch", "<MESSAGES>"),
            # The episode variant wraps content in <EPISODES>, matching default.
            ("extract_entity_summaries_from_episodes", "<EPISODES>"),
        ],
    )
    def test_sections_rendered(self, library, builder_name, messages_section):
        builder = getattr(library.extract_nodes, builder_name)
        content = builder(
            _summaries_context(
                entity_type_descriptions={"File": "A file stored on disk."}
            )
        ).as_messages()[1].content
        assert messages_section in content
        assert "<ENTITIES>" in content
        assert "brndlog.txt" in content
        assert "<ENTITY_TYPE_DESCRIPTIONS>" in content

    def test_summarize_pair_merges_in_chinese(self, library):
        content = library.summarize_nodes.summarize_pair(
            {"node_summaries": [{"name": "a", "summary": "s1"}, {"name": "b", "summary": "s2"}]}
        ).as_messages()[1].content
        assert "简体中文" in content
        assert "s1" in content and "s2" in content


class TestEdgeFactPrompt:
    """extract_edges.edge is the fact producer on the single add_episode path."""

    def _edge_context(self, **overrides):
        context = {
            "episode_content": "The MD5 hash 8ac346e35f6784d1a9208a098a4d7119 identifies brndlog.txt.",
            "nodes": [{"name": "brndlog.txt", "entity_types": ["Entity"]}],
            "previous_episodes": [],
            "reference_time": "2026-10-21T00:00:00Z",
            "edge_types": [],
            "strict_edge_types": False,
            "custom_extraction_instructions": "FORENSIC POLICY MARKER",
        }
        context.update(overrides)
        return context

    def test_requires_simplified_chinese_facts(self, library):
        content = library.extract_edges.edge(self._edge_context()).as_messages()[1].content
        assert "简体中文" in content
        assert "OUTPUT LANGUAGE (MANDATORY)" in content

    def test_context_sections_rendered(self, library):
        content = library.extract_edges.edge(self._edge_context()).as_messages()[1].content
        assert "<PREVIOUS_MESSAGES>" in content
        assert "8ac346e35f6784d1a9208a098a4d7119" in content
        assert "brndlog.txt" in content
        assert "FORENSIC POLICY MARKER" in content
        assert "<REFERENCE_TIME>" in content

    def test_strict_edge_types_rule(self, library):
        content = library.extract_edges.edge(
            self._edge_context(
                edge_types=[
                    {
                        "fact_type_name": "HASH_IDENTIFIES_FILE",
                        "fact_type_signatures": [("Entity", "Entity")],
                        "fact_type_description": "A hash identifies a file.",
                    }
                ],
                strict_edge_types=True,
            )
        ).as_messages()[1].content
        assert "<FACT_TYPES>" in content
        assert "不要新造 relation_type" in content


class TestKillSwitch:
    def test_en_env_disables_overrides(self, monkeypatch):
        from graphiti_integration.chinese_prompts import LANGUAGE_ENV, chinese_prompt_library

        monkeypatch.setenv(LANGUAGE_ENV, "en")
        assert chinese_prompt_library() is None

    def test_default_is_chinese(self, monkeypatch):
        from graphiti_integration.chinese_prompts import LANGUAGE_ENV, chinese_prompt_library

        monkeypatch.delenv(LANGUAGE_ENV, raising=False)
        assert chinese_prompt_library() is not None


class TestIngestorWiring:
    """Every Graphiti() construction site must pass the same prompt library."""

    def _make_ingestor(self, use_local_llm=True):
        from graphiti_integration.graphiti_ingestor import GraphitiIngestor

        ingestor = GraphitiIngestor.__new__(GraphitiIngestor)
        ingestor.config = MagicMock(use_local_llm=use_local_llm)
        ingestor._client = None
        ingestor._owned_llm_client = MagicMock()
        ingestor._owned_embedder = MagicMock()
        return ingestor

    async def test_initialize_local_llm_branch(self):
        from graphiti_integration import graphiti_ingestor
        from graphiti_integration.chinese_prompts import chinese_prompt_library

        fake_graphiti = MagicMock()
        fake_graphiti.return_value.build_indices_and_constraints = AsyncMock()
        ingestor = self._make_ingestor(use_local_llm=True)
        ingestor._create_llm_client = MagicMock(return_value=MagicMock())
        ingestor._create_embedder = MagicMock(return_value=MagicMock())

        with patch.object(graphiti_ingestor, "Graphiti", fake_graphiti):
            await graphiti_ingestor.GraphitiIngestor.initialize(ingestor)

        assert fake_graphiti.call_args.kwargs["prompt_library"] is chinese_prompt_library()

    async def test_initialize_default_branch(self):
        from graphiti_integration import graphiti_ingestor
        from graphiti_integration.chinese_prompts import chinese_prompt_library

        fake_graphiti = MagicMock()
        fake_graphiti.return_value.build_indices_and_constraints = AsyncMock()
        ingestor = self._make_ingestor(use_local_llm=False)

        with patch.object(graphiti_ingestor, "Graphiti", fake_graphiti):
            await graphiti_ingestor.GraphitiIngestor.initialize(ingestor)

        assert fake_graphiti.call_args.kwargs["prompt_library"] is chinese_prompt_library()

    async def test_worker_client_same_library(self):
        from graphiti_integration import graphiti_ingestor
        from graphiti_integration.chinese_prompts import chinese_prompt_library

        fake_graphiti = MagicMock()
        fake_graphiti.return_value.build_indices_and_constraints = AsyncMock()
        ingestor = self._make_ingestor(use_local_llm=True)
        ingestor._client = MagicMock()

        with patch.object(graphiti_ingestor, "Graphiti", fake_graphiti):
            await graphiti_ingestor.GraphitiIngestor._make_worker_client(ingestor)

        assert fake_graphiti.call_args.kwargs["prompt_library"] is chinese_prompt_library()
