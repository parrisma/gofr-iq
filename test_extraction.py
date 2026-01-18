#!/usr/bin/env python3
"""Test graph extraction on a sample document"""

import json
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from app.prompts.graph_extraction import (
    GRAPH_EXTRACTION_SYSTEM_PROMPT,
    build_extraction_prompt,
    parse_extraction_response,
)
from app.services.llm_service import LLMService, ChatMessage, LLMSettings
import os

# Get API key from environment
api_key = os.getenv("GOFR_IQ_OPENROUTER_API_KEY")
if not api_key:
    # Try loading from docker/.env
    env_file = Path("docker/.env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if line.startswith("GOFR_IQ_OPENROUTER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

# Load a test document
test_doc = Path("simulation/test_output_debug/synthetic_1768727613_0_QNTM.json")
if not test_doc.exists():
    # Try another location
    test_doc = Path("simulation/test_output/synthetic_1768727084_0_LUXE.json")
    if not test_doc.exists():
        print("No test document found!")
        sys.exit(1)

print(f"Testing extraction on: {test_doc}")

with open(test_doc) as f:
    doc_data = json.load(f)

# Build extraction prompt
user_prompt = build_extraction_prompt(
    content=doc_data["story_body"],
    title=doc_data["title"],
    source_name=doc_data.get("source_name"),
    published_at=doc_data.get("published_at"),
)

print("\n" + "="*80)
print("USER PROMPT (first 500 chars):")
print("="*80)
print(user_prompt[:500])
print("...")

if not api_key:
    print("ERROR: GOFR_IQ_OPENROUTER_API_KEY not found!")
    sys.exit(1)

# Initialize LLM service
settings = LLMSettings(api_key=api_key)
llm = LLMService(settings=settings)

print("\n" + "="*80)
print("CALLING LLM...")
print("="*80)

# Call LLM
result = llm.chat_completion(
    messages=[
        ChatMessage(role="system", content=GRAPH_EXTRACTION_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_prompt),
    ],
    json_mode=True,
    temperature=0.1,
    max_tokens=1000,
)

print("\n" + "="*80)
print("RAW LLM RESPONSE:")
print("="*80)
print(result.content)

# Parse response
print("\n" + "="*80)
print("PARSED EXTRACTION:")
print("="*80)

extraction = parse_extraction_response(result.content)
print(f"Impact: {extraction.impact_score} ({extraction.impact_tier})")
print(f"Events: {[e.event_type for e in extraction.events]}")
print(f"Instruments: {[f'{i.ticker} ({i.direction})' for i in extraction.instruments]}")
print(f"Companies: {extraction.companies}")
print(f"Regions: {extraction.regions}")
print(f"Sectors: {extraction.sectors}")
print(f"Summary: {extraction.summary}")
