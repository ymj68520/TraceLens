# LM Studio Configuration Guide

This guide explains how to configure LM Studio for optimal performance with the ForensicsProject LLM integration module.

## Context Window Settings

### The Problem
When analyzing large files, the default context window of 4096 tokens may cause errors:
- "Context length exceeded" errors
- Incomplete analysis results
- API request failures

### Solution: Increase Context Length

1. **Open LM Studio**
2. **Select your model** from the left sidebar
3. **Find "Context Length" setting** (also called `n_ctx`)
4. **Increase the value** based on your hardware:

| GPU VRAM | Recommended Context Length | Notes |
|----------|---------------------------|-------|
| 4 GB | 4096 | Default, limited file analysis |
| 8 GB | 8192 | Good for most files |
| 12 GB | 16384 | Better for larger documents |
| 16 GB | 16384 - 24576 | Excellent for most use cases |
| 24 GB+ | 32768+ | Best for very large files |

5. **Apply and reload the model**

## Performance Optimization

### GPU Layers
- Set `GPU Layers` to maximum for faster inference
- Use `--n-gpu-layers 999` for full GPU offload

### Batch Size
- Default: 512
- Increase to 1024 or 2048 for faster processing
- Decrease if running out of memory

### Threads
- Set to your CPU core count for optimal performance
- Example: 8 threads for an 8-core CPU

## Configuration for ForensicsProject

The project's LLM configuration supports these settings in `LLMConfig`:

```cpp
struct LLMConfig {
    // Connection settings
    std::string baseUrl = "http://localhost:1234";
    std::string endpoint = "/v1/chat/completions";
    
    // Model settings
    int maxTokens = 2048;        // Max output tokens
    double temperature = 0.7;    // Creativity level
    
    // Context window management
    int contextLength = 4096;    // Match your LM Studio setting!
    int reservedTokens = 512;    // Reserved for system prompt
    double charsPerToken = 4.0;  // ~4 chars per token for English
};
```

### Important: Sync Settings
**Make sure `contextLength` in your code matches your LM Studio setting!**

Example:
```cpp
LLMConfig config;
config.baseUrl = "http://localhost:1234";
config.contextLength = 8192;  // Match LM Studio!
config.maxTokens = 2048;
```

## Recommended Models

| Model | Context Length | Best For |
|-------|---------------|----------|
| Llama 2 7B | 4096 | Basic text analysis |
| Llama 2 13B | 4096 | Better accuracy |
| Mistral 7B | 8192 | Longer documents |
| Mixtral 8x7B | 32768 | Very large files |
| Qwen 7B/14B | 8192-32768 | Chinese + English |
| CodeLlama | 16384 | Source code analysis |

## Troubleshooting

### "Context Length Exceeded" Error
1. Check your LM Studio context length setting
2. Update `contextLength` in your code to match
3. Consider using chunked analysis for very large files

### Slow Analysis
1. Increase GPU layers
2. Use a smaller model
3. Enable chunked analysis to reduce per-request size

### Out of Memory (OOM)
1. Reduce context length
2. Use a smaller model
3. Lower `maxTokens` setting
4. Close other GPU-intensive applications

### Connection Refused
1. Ensure LM Studio server is running
2. Check the port (default: 1234)
3. Verify no firewall blocking

## Quick Start

1. Install LM Studio
2. Download a model (e.g., Mistral 7B)
3. Load the model with these settings:
   - Context Length: 8192
   - GPU Layers: Maximum
4. Start the local server (default port 1234)
5. Run ForensicsProject with matching config

## Using Smart Truncation

The ForensicsProject now includes intelligent content handling:

- **Smart Truncation**: Automatically truncates at sentence/paragraph boundaries
- **Chunked Analysis**: Splits large files into overlapping chunks
- **Result Merging**: Combines multiple chunk analyses

These features are enabled by default and activate when content exceeds the context window limit.
