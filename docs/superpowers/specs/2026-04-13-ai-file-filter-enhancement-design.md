# AI File Filter Enhancement Design

**Date**: 2026-04-13
**Status**: Draft
**Author**: Claude Code
**Component**: Python HTTP Server - Case Analysis Service

## 1. Overview

This design enhances the AI-driven file filtering system in the forensics analysis tool to address LLM response parsing instability and improve handling of edge cases including duplicate filenames.

### 1.1 Problem Statement

The current `FileFilter` implementation suffers from:
- **Unstable LLM response parsing**: LLMs return various formats (JSON with/without markdown, different field names, mixed with explanatory text)
- **Incomplete handling of duplicate filenames**: When multiple files share the same name, the system may match incorrectly
- **Lack of robustness for edge cases**: Invalid responses, ambiguous path matching, data truncation, concurrent operations

### 1.2 Solution Approach

A hybrid "prevention + remediation" strategy:
1. **Prevention layer**: Enhanced prompts with structure enforcement and adaptive batching
2. **Parser layer**: New dedicated parsing module with multiple fallback strategies
3. **Matching layer**: Intelligent file matcher with composite scoring for duplicate handling
4. **Defense layer**: Response validation, concurrent control, and retry mechanisms

## 2. Architecture

### 2.1 New Components

```
python_service/httpserver/services/case_analysis/
├── llm_response_parser.py      # LLM response parsing
├── file_matcher.py              # Intelligent file matching
├── filter_validator.py          # Result validation and repair
└── concurrent_filter.py         # Concurrent operation control
```

### 2.2 Data Flow

```
Request → Lock Check → Enhanced Prompt → LLM Call
                                    ↓
                          LLMResponseParser
                                    ↓
                          FilterResultValidator
                                    ↓
                            FileMatcher
                                    ↓
                          Result Persistence
                                    ↓
                               Response
```

## 3. Component Design

### 3.1 LLMResponseParser

**Location**: `services/case_analysis/llm_response_parser.py`

**Purpose**: Parse various LLM response formats into a standardized structure.

**Key Methods**:

```python
class LLMResponseParser:
    def parse_filter_response(
        self,
        response_text: str,
        batch_files: List[Dict]
    ) -> ParseResult

    def _extract_json_blocks(self, text: str) -> List[str]
    def _parse_single_json(self, json_str: str) -> ParsedItems
    def _validate_and_repair(self, items: List[str]) -> List[str]
```

**Return Structure**:

```python
@dataclass
class ParseResult:
    selected_files: List[str]      # Matched full paths
    raw_items: List[str]           # Raw LLM items
    reasoning: str                 # Parsing reason
    confidence: float              # Confidence score (0-1)
    repair_actions: List[str]      # Repair operation log
```

**Supported Formats**:
- `{"selected_files": [...], "reasoning": "..."}`
- `{"filtered_files": [...], "reasoning": "..."}`
- `{"files": [...], "reasoning": "..."}`
- `[...]` (array format)
- Markdown code blocks with any of above
- Text with JSON embedded

### 3.2 FileMatcher

**Location**: `services/case_analysis/file_matcher.py`

**Purpose**: Intelligently match files, handling duplicates with composite scoring.

**Key Methods**:

```python
class FileMatcher:
    def match_files(
        self,
        llm_items: List[str],
        batch_files: List[Dict],
        case_context: Optional[str] = None
    ) -> MatchResult

    def _calculate_relevance_score(
        self,
        file: Dict,
        case_context: str
    ) -> float
```

**Composite Scoring**:

```
score = w1 * path_semantic_score
      + w2 * freshness_score
      + w3 * size_score
      + w4 * depth_score
```

**Default Weights**:
- `w1 = 0.4` (path semantic relevance)
- `w2 = 0.3` (time freshness)
- `w3 = 0.2` (file size)
- `w4 = 0.1` (path depth)

**Duplicate Resolution Strategy**:
1. Build name-to-paths mapping
2. For each LLM-returned name:
   - If single match: use it
   - If multiple matches: score and select highest
   - If no match: try fuzzy matching
3. Return selected files with metadata

### 3.3 FilterResultValidator

**Location**: `services/case_analysis/filter_validator.py`

**Purpose**: Validate results and handle edge cases.

**Key Methods**:

```python
class FilterResultValidator:
    def validate_and_repair(
        self,
        parse_result: ParseResult,
        batch_files: List[Dict],
        max_files: int
    ) -> ValidationResult

    def _handle_invalid_response(
        self,
        response_text: str,
        batch_files: List[Dict]
    ) -> List[str]

    def _resolve_ambiguous_matches(
        self,
        ambiguous: List[Tuple[str, List[str]]]
    ) -> List[str]
```

**Edge Case Handling**:
- **Invalid LLM responses**: Multi-strategy fallback (regex extract → fuzzy match → empty with warning)
- **Ambiguous path matches**: Return all candidates with confidence scores
- **Empty responses**: Log warning and return empty list

### 3.4 FilterLockManager

**Location**: `services/case_analysis/concurrent_filter.py`

**Purpose**: Prevent concurrent filtering conflicts on the same task.

**Key Methods**:

```python
class FilterLockManager:
    @classmethod
    def instance(cls) -> 'FilterLockManager'

    async def acquire_task_lock(self, task_id: str) -> asyncio.Lock
    async def filter_with_lock(
        self,
        task_id: str,
        filter_func: Callable,
        *args,
        **kwargs
    )
```

**Implementation**: Singleton pattern with task-level async locks.

## 4. Enhanced Prompts

### 4.1 System Prompt Template

**Location**: `python_service/httpserver/prompts.py`

```python
FILE_FILTER_SYSTEM_ENHANCED = """你是数字取证专家，需要从文件列表中筛选与案情相关的文件。

## 输出格式要求（必须严格遵守）

你必须只返回JSON格式，不要包含任何其他文字说明。JSON格式如下：

{
  "selected_files": ["文件名1", "文件名2"],
  "reasoning": "简要说明选择原因"
}

## 重要约束

1. selected_files数组中只填写文件名（不含路径）
2. 文件名必须与输入数据第一列完全匹配
3. 如果没有任何相关文件，返回空数组：{"selected_files": [], "reasoning": "无相关文件"}
4. 不要使用markdown代码块包裹JSON
5. 不要添加任何解释性文字，只返回JSON
"""
```

### 4.2 Few-Shot Examples

```python
@dataclass
class FewShotExample:
    case_description: str
    file_list: str
    expected_response: str

FEW_SHOT_EXAMPLES = [
    FewShotExample(
        case_description="查找恶意软件感染证据",
        file_list="malware.exe | /Downloads/malware.exe | 1048576 | executables",
        expected_response='{"selected_files": ["malware.exe"], "reasoning": "发现可疑可执行文件"}'
    ),
    # More examples...
]
```

### 4.3 Adaptive Batching

**Configuration**:
```python
DEFAULT_BATCH_SIZE = 50
MIN_BATCH_SIZE = 10
MAX_BATCH_SIZE = 100
TARGET_TOKEN_RATIO = 0.6
```

**Dynamic Adjustment**:
```python
def calculate_optimal_batch_size(
    avg_file_size: int,
    model_context: int,
    current_batch: int
) -> int:
    estimated_tokens = avg_file_size * current_batch
    if estimated_tokens > model_context * TARGET_TOKEN_RATIO:
        return max(MIN_BATCH_SIZE, current_batch // 2)
    return min(MAX_BATCH_SIZE, current_batch * 2)
```

## 5. Edge Case Handling Matrix

| Edge Case | Handling Strategy |
|-----------|-------------------|
| **A. LLM returns invalid content** | Multi-layer fallback: JSON parse → regex extract → fuzzy match → return empty |
| **B. Path matching ambiguity** | FileMatcher intelligent scoring, return highest confidence match |
| **C. TOON data truncation** | Adaptive batch size, token estimation, dynamic adjustment |
| **D. Special character paths** | Unicode-safe string handling, proper escaping |
| **E. Database connection errors** | Connection pooling, timeout handling, retry with backoff |
| **F. Concurrent filter conflicts** | Task-level async locks |

## 6. Integration Strategy

### 6.1 Backward Compatibility

1. Keep existing `_parse_toon_filter_response` as ultimate fallback
2. If new parser fails, automatically degrade to old method
3. API interface unchanged, return format compatible with existing code

### 6.2 Modified Files

- `services/case_analysis/file_filter.py`: Integrate new parser, matcher, validator
- `services/case_analysis/multi_image_filter.py`: Use enhanced components
- `prompts.py`: Add enhanced prompt templates
- `config.py`: Add new configuration options

### 6.3 New Files

- `services/case_analysis/llm_response_parser.py`
- `services/case_analysis/file_matcher.py`
- `services/case_analysis/filter_validator.py`
- `services/case_analysis/concurrent_filter.py`

## 7. Configuration

**New Configuration Options** (`config.py`):

```python
class LLMFilterConfig:
    # Parser settings
    enable_enhanced_parser: bool = True
    parser_fallback_enabled: bool = True

    # Matcher settings
    match_confidence_threshold: float = 0.3
    enable_smart_dedup: bool = True

    # Scoring weights
    score_weight_path_semantic: float = 0.4
    score_weight_freshness: float = 0.3
    score_weight_size: float = 0.2
    score_weight_depth: float = 0.1

    # Concurrent control
    enable_concurrent_lock: bool = True
    lock_timeout: int = 300

    # Retry settings
    max_parse_retries: int = 2
    retry_delay: int = 1
```

## 8. Testing Strategy

### 8.1 Unit Tests

- `test_llm_response_parser.py`: Test various response formats
- `test_file_matcher.py`: Test duplicate resolution
- `test_filter_validator.py`: Test edge case handling
- `test_concurrent_filter.py`: Test concurrent operations

### 8.2 Integration Tests

- Test full filtering pipeline with mock LLM
- Test concurrent filtering scenarios
- Test database persistence

### 8.3 Edge Case Tests

- Invalid JSON responses
- Empty responses
- Truncated responses
- Special character paths
- Multiple concurrent requests

## 9. Success Criteria

1. **Parsing Robustness**: Successfully parse 95%+ of valid LLM responses
2. **Duplicate Handling**: Correctly select most relevant duplicate file
3. **Concurrent Safety**: No race conditions in parallel filtering
4. **Performance**: No significant performance degradation
5. **Backward Compatibility**: Existing functionality unaffected

## 10. Rollout Plan

1. **Phase 1**: Implement new components with feature flags
2. **Phase 2**: Unit and integration testing
3. **Phase 3**: Gradual rollout with monitoring
4. **Phase 4**: Full deployment after validation

## 11. Open Questions

- Should we persist parsing confidence scores for analysis?
- Do we need a UI for monitoring parsing failures?
- Should we add alerting for low-confidence results?

## 12. References

- Existing `FileFilter` implementation
- `MultiImageFilter` for cross-image deduplication patterns
- OpenAI API best practices for structured output
