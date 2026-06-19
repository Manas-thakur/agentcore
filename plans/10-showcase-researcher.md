# Part 10: Showcase App — Autonomous Technical Researcher

## Purpose

The showcase app ties every AgentCore component together into a single, impressive demo: an agent that can research complex technical questions thoroughly, read multiple sources, synthesize findings, and produce a well-cited report.

This is the project you'll put on the front page of your resume and demo in interviews.

## What It Does

1. User submits a complex technical question (e.g., "Compare the latest approaches to LLM quantization: GPTQ, AWQ, and GGUF — which is best for which use case?")
2. The agent **plans** its research approach — breaking the question into sub-questions
3. It **searches** the web (DuckDuckGo, optionally Google/arXiv) in parallel
4. It **reads** each search result, extracts main content, and chunks it
5. It **stores** extracted information in a vector index for the session
6. It **synthesizes** a structured report section-by-section
7. It **reviews** the report for accuracy, completeness, and clarity
8. It **revises** based on review, then outputs the final report with inline citations

## Architecture

```
User Query ("Compare GPTQ, AWQ, and GGUF")
    │
    ▼
┌─────────────────────────────┐
│         CLI / API           │
│  (agentcore researcher run) │
└──────────┬──────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│  AgentCore Graph: "Autonomous Research Pipeline" │
│                                                  │
│  parse_query → plan_research →                  │
│      search_web [parallel] →                     │
│      read_and_extract [parallel per source] →    │
│      store_in_index →                            │
│      synthesize_report →                         │
│      review_report →                             │
│      [if fail] revise_report → review_report     │
│      [if pass] output_final_report               │
└──────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│    Final Report (Markdown)  │
│  + JSON Trace + Cost Report │
└─────────────────────────────┘
```

## Key Components Used

| Component | How It's Used |
|-----------|---------------|
| `runtime` | ReAct loop for each sub-task (reading, extracting, synthesizing) |
| `tools` | `web_search`, `web_scrape`, `file_read`, `rag_retrieve` |
| `rag` | Ingest scraped content, chunk, index, retrieve for synthesis |
| `index` | LanceDB for session-level vector index of research findings |
| `graph` | Orchestrate the research pipeline with parallel search + conditional review |
| `agents` | `ResearcherAgent` (main), `ReviewerAgent` (review), `PlannerAgent` (plan) |
| `eval` | Verify final report accuracy against sources |
| `obs` | Full tracing: every search, read, and synthesis step |
| `deploy` | Docker + Cloud Run for web API |

## User Flow

### CLI Mode
```bash
agentcore researcher run "Compare GPTQ, AWQ, and GGUF quantization methods"

# Real-time output:
┌─ Planning research...
│  Sub-questions identified:
│  1. What is GPTQ and how does it work?
│  2. What is AWQ and how does it work?
│  3. What is GGUF and how does it work?
│  4. How do they compare on: accuracy, speed, memory, hardware support?
│  5. Which is best for: edge deployment, cloud serving, fine-tuning?
│
├─ Searching... (5 parallel searches)
│  ✓ Found 12 relevant sources
│
├─ Reading sources... (12 parallel reads)
│  ████████████████░░░░ 8/12 complete
│
├─ Synthesizing report...
│  ████████████████░░░░ Section 3/5
│
├─ Reviewing report...
│  ⚠ Found 2 unverified claims, requesting revision
│
├─ Revising report...
│
└─ ✓ Report ready (2450 words, 14 citations, $0.02 cost)

# Output files:
#   report.md          — Full research report
#   report.trace.json  — Full execution trace
#   report.cost.json   — Cost breakdown
```

### API Mode
```bash
curl -X POST http://localhost:8000/api/v1/researcher/run \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare GPTQ, AWQ, and GGUF", "stream": true}'
```

## Report Output Format

The report is a well-structured markdown document:

```markdown
# LLM Quantization Methods: GPTQ vs AWQ vs GGUF

**Generated:** 2026-06-19 | **Sources:** 14 | **Cost:** $0.02

## Executive Summary

{2-3 paragraph summary of findings}

## 1. Overview of Quantization Methods

### 1.1 GPTQ (Generative Pre-Trained Transformer Quantization)
GPTQ is a post-training quantization method... [1][2]

### 1.2 AWQ (Activation-Aware Weight Quantization)
AWQ takes a different approach by... [3][4]

### 1.3 GGUF (GPT-Generated Unified Format)
GGUF is a file format and quantization framework... [5][6]

## 2. Comparative Analysis

| Metric | GPTQ | AWQ | GGUF |
|--------|------|-----|------|
| Accuracy (perplexity) | +0.5% loss | +0.3% loss | +0.4% loss |
| Inference Speed | Fast | Faster | Fast |
| Memory Usage | Low | Lower | Low |
| Hardware Support | GPU only | GPU only | CPU + GPU |
| Ease of Use | Moderate | Moderate | Easy |

## 3. Recommendations

### Edge Deployment
...

### Cloud Serving
...

### Fine-tuning
...

## 4. Conclusion
{summary}

## Sources
[1] GPTQ: Accurate Post-Training Quantization — {url}
[2] ...
[3] ...
```

## File Structure

```
apps/researcher/
├── __init__.py
├── app.py                    # FastAPI app
├── pipeline.py               # Research pipeline graph definition
├── prompts.py                # System prompts for each sub-agent
├── cli.py                    # CLI entry point
├── models.py                 # Request/response models
├── config.py                 # Researcher-specific config
└── tests/
    ├── test_pipeline.py
    └── test_end_to_end.py
```
