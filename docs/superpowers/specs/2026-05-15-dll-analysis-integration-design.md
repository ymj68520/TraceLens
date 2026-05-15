# DLL Analysis Integration Design

**Date**: 2026-05-15  
**Status**: Approved  
**Approach**: Option 2b - RPC over HTTP

## 1. Architecture Overview

```
Files.jsx (React Frontend)
    ↓
Python FastAPI Service (port 8090)
    ↓ POST /api/llm/analyze/dll
    ↓
C++ Crow Server (port 8080)
    ↓ POST /api/forensics/dlls/analyze
    ↓
DLLAnalyzer (C++ Core)
    ↓
DLLAnalysisResult → Markdown Report → LLM Analysis → Results
```

## 2. C++ Server: New Endpoint

### Endpoint Specification

**Route**: `POST /api/forensics/dlls/analyze`  
**File**: `src/network/HTTPServer/routes/DLLAnalysisRoutes.cpp`

**Request**:
```json
{
  "file_path": "/absolute/path/to/file.dll",
  "task_id": "optional_task_id_for_db_lookup"
}
```

**Response**:
```json
{
  "success": true,
  "file_path": "/path/to/file.dll",
  "file_name": "file.dll",
  "file_size": 12345,
  "format": "PE",
  "machine_type": "x64",
  "threat_score": 75,
  "signature_status": "Unsigned",
  "md5": "...",
  "sha256": "...",
  "sections": [...],
  "imports": [...],
  "exports": [...],
  "anomalies": [...],
  "compile_timestamp": 1234567890
}
```

### Implementation Details

- Reuse existing `DLLAnalyzer::analyzeDLL()` for single-file analysis
- Skip full DLL database initialization, parse file directly
- Timeout: 30 seconds (prevent blocking on large files)
- Error handling: file not found, permission denied, parse failure

## 3. Python Service Integration

### New Files

#### `python_service/httpserver/services/dll_analyzer.py`

```python
class DLLAnalyzerClient:
    """Client for calling C++ DLL analysis endpoint"""
    
    def __init__(self, cpp_backend_url: str):
        self.cpp_backend_url = cpp_backend_url
    
    async def analyze_dll(self, file_path: str) -> dict:
        """Call C++ backend to analyze DLL file"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.cpp_backend_url}/api/forensics/dlls/analyze",
                json={"file_path": file_path},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
```

#### `python_service/httpserver/routes/dll.py`

```python
@router.post("/api/llm/analyze/dll")
async def analyze_dll(request: DLLAnalysisRequest):
    """Analyze DLL file with C++ parser + LLM"""
    # 1. Call C++ backend for binary parsing
    dll_data = await dll_client.analyze_dll(request.file_path)
    
    # 2. Convert to Markdown
    markdown = DLLMarkdownGenerator.generate(dll_data)
    
    # 3. Call LLM for security analysis
    llm_result = await llm_service.analyze(
        content=markdown,
        prompt=DLL_SECURITY_ANALYSIS_PROMPT,
        model_type="text"
    )
    
    # 4. Persist to database (optional)
    if request.files_db_path:
        persist_to_files_db(...)
    
    return llm_result
```

### Data Flow

1. Receive file path from frontend
2. Call `DLLAnalyzerClient.analyze_dll()` to get parsed data
3. Use `DLLMarkdownGenerator` to convert results to Markdown
4. Call LLM for security analysis (reuse existing LLM service)
5. Return LLM analysis result

## 4. Markdown Report Generator

### File: `python_service/httpserver/services/dll/dll_markdown_generator.py`

**Template Structure**:

```markdown
# DLL 文件分析报告

## 文件信息
- **文件名**: file.dll
- **文件大小**: 12.3 KB
- **文件格式**: PE
- **架构**: x64

## 哈希值
- MD5: ...
- SHA1: ...
- SHA256: ...

## PE 头信息
- **编译时间**: 2024-01-01 00:00:00
- **入口点**: 0x1000
- **子系统**: Windows GUI
- **数字签名**: ❌ 未签名

## 节表
| 节名称 | 虚拟地址 | 虚拟大小 | 熵值 | 权限 |
|--------|----------|----------|------|------|
| .text  | 0x1000   | 4096     | 5.23 | R-X  |
| .data  | 0x2000   | 1024     | 2.15 | RW-  |

## 导入函数
### kernel32.dll
- CreateThread
- VirtualAlloc
- WriteProcessMemory

### advapi32.dll
- RegOpenKeyEx
- RegSetValueEx

## 导出函数
- DllInstall @1
- DllUnregisterServer @2

## 异常检测
### [高熵节] .text 节熵值较高 (5.23)
- **风险分数**: 70
- **说明**: 可能包含加密或压缩代码

### [无数字签名] 文件未签名
- **风险分数**: 30
- **说明**: 缺乏代码签名验证

## 威胁评分: 75/100
```

### Implementation

```python
class DLLMarkdownGenerator:
    @staticmethod
    def generate(dll_data: dict) -> str:
        sections = [
            DLLMarkdownGenerator._format_header(dll_data),
            DLLMarkdownGenerator._format_hashes(dll_data),
            DLLMarkdownGenerator._format_pe_info(dll_data),
            DLLMarkdownGenerator._format_sections(dll_data),
            DLLMarkdownGenerator._format_imports(dll_data),
            DLLMarkdownGenerator._format_exports(dll_data),
            DLLMarkdownGenerator._format_anomalies(dll_data),
            DLLMarkdownGenerator._format_threat_score(dll_data),
        ]
        return "\n\n".join(filter(None, sections))
```

## 5. LLM Prompt Template

### DLL Security Analysis Prompt

```python
DLL_SECURITY_ANALYSIS_PROMPT = """你是一位专业的恶意软件分析专家。请基于以下DLL文件的技术分析报告,提供安全评估。

{markdown_report}

请提供以下分析:
1. **功能评估**: 该DLL的主要功能和可能用途
2. **威胁级别**: 基于以下标准评估:
   - 🟢 低风险 (0-30): 正常系统DLL,无异常特征
   - 🟡 中风险 (31-60): 存在可疑特征但可能是合法软件
   - 🟠 高风险 (61-80): 多个恶意指标,高度可疑
   - 🔴 严重 (81-100): 确认为恶意软件或非常可疑
3. **可疑行为**: 基于导入/导出函数的恶意行为推测
4. **MITRE ATT&CK**: 可能的攻击技术映射
5. **缓解建议**: 具体的处置建议

请以JSON格式返回:
{
  "threat_level": "低/中/高/严重",
  "confidence": "高/中/低",
  "function_assessment": "...",
  "suspicious_behaviors": ["行为1", "行为2"],
  "mitre_attack_techniques": ["T1055", "T1012"],
  "iocs": ["可疑指标1", "可疑指标2"],
  "recommendations": "处置建议"
}
"""
```

## 6. Frontend Integration

### File: `web/src/pages/Files.jsx`

**Modify**: `handleAnalyzeSingleFile()` function (lines 247-361)

**New Logic**:
```javascript
// Check if file is DLL/EXE/SYS
const dllExtensions = ['dll', 'exe', 'sys', 'ocx', 'cpl'];
const isDLL = dllExtensions.includes(extension);

if (isDLL) {
  // Call DLL analysis endpoint
  const result = await analyzeDLLFile({
    filePath: filePath,
    filesDbPath: currentTask?.output_files_db || null
  });
  
  // Display LLM analysis result
  setLlmResults(prev => ({
    ...prev,
    [filePath]: {
      summary: result.llm_analysis.summary,
      description: result.llm_analysis.description,
      keywords: result.llm_analysis.keywords,
      model: result.model_used,
      timestamp: result.timestamp,
      isDLLAnalysis: true  // Mark as DLL analysis
    }
  }));
} else {
  // Existing file analysis logic
  const result = await analyzeContent({...});
}
```

**New API Function**:
```javascript
const analyzeDLLFile = async ({ filePath, filesDbPath }) => {
  const response = await fetch('/api/llm/analyze/dll', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      file_path: filePath,
      files_db_path: filesDbPath
    })
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'DLL分析失败');
  }
  
  return await response.json();
};
```

## 7. Error Handling & Timeouts

### C++ Layer

- File read timeout: 30 seconds
- LLM call timeout: 60 seconds (configurable)
- Return structured errors: `{"error": "...", "file_path": "..."}`

### Python Layer

- C++ backend unavailable: 503 + user-friendly message
- File parse failure: 400 + error details
- LLM analysis failure: 500 + fallback (return raw text)

### Frontend Layer

- Network error: prompt user to check service status
- Timeout error: prompt "Analysis taking too long, please retry"
- File not found: prompt to extract file first

## 8. Configuration & Dependencies

### `.env` Additions

```env
# DLL Analysis
DLL_ANALYSIS_ENABLED=true
DLL_ANALYSIS_TIMEOUT=30
DLL_CPP_BACKEND_URL=http://localhost:8080
```

### Dependencies

- **Python**: `httpx>=0.24.0` (already exists)
- **C++**: No new dependencies (reuse existing DLLAnalyzer)

## 9. Testing Plan

### Unit Tests

- Python: `test_dll_analyzer_client.py` (test RPC calls)
- Python: `test_dll_markdown_generator.py` (test Markdown generation)
- C++: Reuse existing DLLAnalyzer tests

### Integration Tests

- End-to-end: Files.jsx → Python → C++ → DLLAnalyzer → LLM → Display
- Error scenarios: file not found, C++ offline, LLM timeout

### Manual Test Steps

1. Start C++ server (port 8080)
2. Start Python service (port 8090)
3. In Files.jsx, select a DLL file
4. Click "AI Analysis"
5. Verify: LLM result includes DLL-specific analysis (threat level, MITRE ATT&CK, IOCs)

## 10. Advantages & Risks

### Advantages

- Minimal code changes (reuse existing C++ DLLAnalyzer)
- Clear separation of concerns (C++ parsing → Python business logic → LLM)
- Extensible (support more binary formats in future)
- Graceful degradation (user-friendly message if C++ service unavailable)

### Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Timeout control needs tuning | Configurable timeout, async processing for large files |
| Large files (>10MB) slow to parse | Add size limit warning, background processing option |
| Windows/Linux path differences | Use path normalization, test on both platforms |
| C++ service unavailable | Clear error message, fallback to basic analysis |

---

**Implementation Status**: Ready for planning phase
