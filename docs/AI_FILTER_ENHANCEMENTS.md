# AI File Filter Enhancements

## Overview

The AI file filtering system has been enhanced with robust response parsing, intelligent duplicate handling, and edge case resilience.

## New Components

### LLMResponseParser

**Location:** `services/case_analysis/llm_response_parser.py`

Handles various LLM response formats:
- JSON with/without markdown code blocks
- Different field names (selected_files, filtered_files, files)
- Array or dict format
- Text with embedded JSON

**Key Methods:**
- `parse_filter_response(response_text, batch_files) -> ParseResult`
- `_extract_json_blocks(text) -> List[str]`
- `_parse_single_json(json_str) -> ParsedItems`
- `_validate_and_match(raw_items, batch_files) -> List[str]`
- `_fallback_parse(response_text, batch_files) -> ParseResult`

### FileMatcher

**Location:** `services/case_analysis/file_matcher.py`

Intelligently matches files with duplicate resolution:
- Composite scoring (path semantic + freshness + size + depth)
- Configurable weights
- Confidence scoring

**Key Methods:**
- `match_files(llm_items, batch_files, case_context) -> MatchResult`
- `_resolve_duplicate(name, candidates, case_context) -> Dict`
- `_calculate_relevance_score(file, case_context) -> float`

**Scoring Weights (default):**
- Path semantic: 0.4
- Freshness: 0.3
- Size: 0.2
- Depth: 0.1

### FilterResultValidator

**Location:** `services/case_analysis/filter_validator.py`

Validates and repairs results:
- Handles invalid responses
- Trims excess files
- Removes invalid items
- Low confidence detection

**Key Methods:**
- `validate_and_repair(parse_result, batch_files, max_files) -> ValidationResult`
- `handle_invalid_response(response_text, batch_files) -> ValidationResult`

### FilterLockManager

**Location:** `services/case_analysis/concurrent_filter.py`

Prevents concurrent filtering conflicts:
- Task-level async locks
- Timeout support
- Singleton pattern

**Key Methods:**
- `instance() -> FilterLockManager` (classmethod)
- `filter_with_lock(task_id, filter_func, *args, timeout, **kwargs) -> T`
- `cleanup_task_lock(task_id) -> None`

## Configuration

Add to your `.env` or settings:

```env
# Enable enhanced parser
ENABLE_ENHANCED_PARSER=true

# Configure scoring weights
SCORE_WEIGHT_PATH_SEMANTIC=0.4
SCORE_WEIGHT_FRESHNESS=0.3
SCORE_WEIGHT_SIZE=0.2
SCORE_WEIGHT_DEPTH=0.1

# Concurrent control
ENABLE_CONCURRENT_LOCK=true
LOCK_TIMEOUT=300
```

## Usage

No API changes required. The enhanced components are automatically used.

For manual control, use feature flags:
```python
from httpserver.config import LLMFilterConfig

filter_config = LLMFilterConfig(
    enable_enhanced_parser=True,
    enable_smart_dedup=True,
    score_weight_path_semantic=0.5,  # Custom weights
)
```

## Testing

Run tests:
```bash
cd python_service
.venv/bin/pytest tests/unit/test_concurrent_filter.py -v
.venv/bin/pytest tests/unit/test_llm_response_parser.py -v
.venv/bin/pytest tests/unit/test_file_matcher.py -v
.venv/bin/pytest tests/unit/test_filter_validator.py -v
.venv/bin/pytest tests/integration/test_file_filter_integration.py -v
```

## Migration Guide

The enhancements are backward compatible. Existing code continues to work with automatic fallback to legacy parsing if needed.

To enable new features in custom code:
```python
from services.case_analysis.llm_response_parser import LLMResponseParser
from services.case_analysis.file_matcher import FileMatcher
from services.case_analysis.filter_validator import FilterResultValidator

parser = LLMResponseParser(settings)
matcher = FileMatcher(settings)
validator = FilterResultValidator(settings)

# Use in your filtering pipeline
parse_result = parser.parse_filter_response(llm_response, batch_files)
validated = validator.validate_and_repair(parse_result, batch_files, max_files)
matched = matcher.match_files(validated.items, batch_files, case_context)
```
