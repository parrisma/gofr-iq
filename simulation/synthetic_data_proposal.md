# Synthetic Data Generation

This directory contains tools for generating high-fidelity synthetic financial news and market data to test the Gofr IQ knowledge graph extraction pipeline.

## Overview

The primary tool is `generate_synthetic_stories.py`, which uses an LLM (Claude) to create a consistent "Mock Universe" of companies, executives, and market events. This allows for controlled testing of graph capabilities (entity resolution, relationship extraction) without relying on sensitive or unpredictable real-world data.

## Usage

### Prerequisites
You must have a valid Anthropic API key in your environment variables or `.env` file:
```bash
export ANTHROPIC_API_KEY="sk-..."
```

### Running the Generator

```bash
cd simulation
python generate_synthetic_stories.py
```

## How It Works

1.  **Mock Universe Creation**: The script first invents a set of fictional companies (e.g., "Nebula Dynamics", "Quantum Ledger") and executives.
2.  **Scenario Injection**: It applies specific narrative templates ("Scenarios") to these entities to create meaningful relationships.
3.  **Output**: Generates JSON files in `test_output/` containing the stories and ground-truth graph data.

### Scenarios

The generator supports tiered complexity levels:

*   **Platinum (Complex)**: multi-entity events like Market Crashes or Mergers & Acquisitions. Useful for testing complex relationship traversals.
*   **Gold (Intermediate)**: Tech Breakthroughs or Product Launches. Good for testing causality chains.
*   **Silver (Simple)**: Regulatory Changes or Earnings Reports. Good for basic entity recognition.

## Files

*   `generate_synthetic_stories.py`: Main script for generating data.
*   `ingest_synthetic_stories.py`: (If present) Helper to load generated JSON into the main pipeline.
*   `run_simulation.py`: Orchestrator for running end-to-end simulation tests.
