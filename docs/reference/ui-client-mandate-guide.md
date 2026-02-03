# Client Mandate Fields - UI Integration Guide

## Overview

Clients have two mandate-related fields that describe their investment approach:

1. **mandate_type** - Categorical investment style (enum)
2. **mandate_text** - Free-text fund mandate description (0-5000 chars)

## Field Details

### mandate_type
- **Type**: String (enum-like categorical)
- **Values**: 
  - `equity_long_short`
  - `global_macro`
  - `event_driven`
  - `relative_value`
  - `fixed_income`
  - `multi_strategy`
- **Optional**: Yes (can be null/empty)
- **Purpose**: Provides categorical classification of investment strategy

### mandate_text
- **Type**: String (free-text)
- **Length**: 0-5000 characters
- **Optional**: Yes (can be null/empty)
- **Purpose**: Detailed investment guidelines, restrictions, objectives beyond categorical mandate_type
- **Impact**: 
  - Contributes 17.5% to Client Profile Completeness Score (CPCS)
  - Used to enhance document search ranking (semantic + graph matching)
  - Helps personalize news feeds based on detailed investment criteria
- **Special Behavior**:
  - Empty string (`""`) explicitly clears the field
  - Omitting the parameter preserves current value (no change)
  - Text is automatically stripped of leading/trailing whitespace

## MCP Tool Operations

### 1. Create Client with Mandate

```python
create_client(
    name="Quantum Momentum Partners",
    client_type="HEDGE_FUND",
    mandate_type="equity_long_short",
    mandate_text="Our fund focuses on US technology stocks with strong ESG ratings and sustainable business models. We maintain a 130/30 portfolio with long bias toward growth stocks showing momentum signals and short positions in overvalued legacy tech companies.",
    # ... other fields
)
```

### 2. Get Client Profile (includes mandate)

```python
# Returns full profile including both mandate fields
get_client_profile(
    client_guid="550e8400-e29b-41d4-a716-446655440000"
)

# Response structure:
{
    "client_guid": "...",
    "name": "Quantum Momentum Partners",
    "profile": {
        "mandate_type": "equity_long_short",
        "mandate_text": "Our fund focuses on US technology stocks...",
        "benchmark": "SPY",
        "horizon": "medium",
        "esg_constrained": true
    },
    # ... other fields
}
```

### 3. List Clients (optionally include mandate_text)

```python
# By default, mandate_text is excluded (reduces response size)
list_clients(
    limit=50
)

# Explicitly include mandate_text in list results
list_clients(
    include_mandate_text=True,  # Add this flag
    limit=50
)

# Response with include_mandate_text=True:
{
    "clients": [
        {
            "client_guid": "...",
            "name": "Quantum Momentum Partners",
            "client_type": "HEDGE_FUND",
            "mandate_text": "Our fund focuses on...",  # Only present if flag set
            # ... other fields
        }
    ]
}
```

**Important**: `mandate_text` is excluded from `list_clients` by default to keep response sizes manageable when listing many clients. Use `include_mandate_text=True` if you need the full text in list views.

### 4. Update Mandate Fields

```python
# Update mandate_type only (preserves mandate_text)
update_client_profile(
    client_guid="550e8400-e29b-41d4-a716-446655440000",
    mandate_type="global_macro"
    # mandate_text not provided → keeps current value
)

# Update mandate_text only (preserves mandate_type)
update_client_profile(
    client_guid="550e8400-e29b-41d4-a716-446655440000",
    mandate_text="Updated investment guidelines focusing on emerging markets..."
    # mandate_type not provided → keeps current value
)

# Clear mandate_text (empty string)
update_client_profile(
    client_guid="550e8400-e29b-41d4-a716-446655440000",
    mandate_text=""  # Explicitly clears the field
)

# Update both simultaneously
update_client_profile(
    client_guid="550e8400-e29b-41d4-a716-446655440000",
    mandate_type="multi_strategy",
    mandate_text="Diversified approach combining equity, fixed income, and derivatives..."
)
```

## UI Display Recommendations

### 1. Client Profile View
- **mandate_type**: Display as formatted label (e.g., "Equity Long/Short")
- **mandate_text**: Display in expandable text area or dedicated section
- Consider showing character count: "450 / 5000 chars"

### 2. Client List View
- **Default**: Show only mandate_type (lightweight)
- **Detail Mode**: Show truncated mandate_text (first 100 chars) with "..." 
- **Full Detail**: Request with `include_mandate_text=True` and show full text

### 3. Edit Forms
```
┌─────────────────────────────────────────┐
│ Investment Mandate                      │
├─────────────────────────────────────────┤
│ Mandate Type: [Dropdown]                │
│   ▼ Equity Long/Short                   │
│                                         │
│ Detailed Mandate (optional):            │
│ ┌─────────────────────────────────────┐ │
│ │ Our fund focuses on US technology   │ │
│ │ stocks with strong ESG ratings...   │ │
│ │                                     │ │
│ └─────────────────────────────────────┘ │
│ 125 / 5000 characters                   │
│                                         │
│ ℹ️ Mandate text helps personalize your  │
│   news feed and contributes to profile │
│   completeness.                        │
└─────────────────────────────────────────┘
```

## Validation Rules

### mandate_type
- Must be one of the valid enum values
- Can be empty/null
- Case-insensitive (automatically lowercased)

### mandate_text
- Maximum 5000 characters
- Can be empty string (clears field) or null (no change)
- Leading/trailing whitespace automatically trimmed
- Error returned if exceeds 5000 chars

## Error Handling

### mandate_text Too Long
```json
{
    "status": "error",
    "error_code": "MANDATE_TEXT_TOO_LONG",
    "message": "Mandate text exceeds 5000 character limit: 5234 chars",
    "recovery_strategy": "Shorten the text to 5000 characters or less.",
    "details": {
        "length": 5234,
        "max_length": 5000
    }
}
```

**UI Action**: Show inline error, display character count in red, disable save button

### Invalid mandate_type
```json
{
    "status": "error", 
    "error_code": "INVALID_MANDATE_TYPE",
    "message": "Invalid mandate_type: long_only_equity",
    "recovery_strategy": "Use one of: equity_long_short, global_macro, event_driven, relative_value, fixed_income, multi_strategy"
}
```

**UI Action**: Show dropdown validation error, reset to valid value or empty

## Best Practices

1. **Loading Strategy**: 
   - Use `list_clients()` without `include_mandate_text` for initial list
   - Use `get_client_profile()` when viewing/editing specific client
   - Only set `include_mandate_text=True` if showing mandate text in list view

2. **Form UX**:
   - Show character counter that updates in real-time
   - Consider rich text editor for mandate_text (but store as plain text)
   - Provide mandate_type dropdown with human-readable labels
   - Show warning when approaching 5000 char limit (e.g., at 4800 chars)

3. **Partial Updates**:
   - Only send fields that changed (don't send entire profile)
   - Remember: empty string clears, omitting preserves
   - Update one field at a time if user is editing incrementally

4. **Performance**:
   - mandate_text can be large (up to 5000 chars × many clients)
   - Don't include in list views unless necessary
   - Consider pagination or lazy loading for large client lists

## Examples for UI LLM

### Get mandate for display
```typescript
// When viewing client detail page
const profile = await mcpClient.call("get_client_profile", {
    client_guid: selectedClientGuid
});

// Access mandate fields
const mandateType = profile.data.profile.mandate_type;
const mandateText = profile.data.profile.mandate_text;
```

### Update only mandate_text
```typescript
// User edited mandate description
const result = await mcpClient.call("update_client_profile", {
    client_guid: currentClient.guid,
    mandate_text: userInput.trim()
    // Other fields omitted → preserved
});
```

### List with mandate_text
```typescript
// For mandate search/filter view
const clients = await mcpClient.call("list_clients", {
    include_mandate_text: true,
    limit: 50
});
```

## Database Storage

- **mandate_type**: Stored on `ClientProfile` node in Neo4j
- **mandate_text**: Stored on `ClientProfile` node in Neo4j
- Both are optional properties (can be null)
- Retrieved via `OPTIONAL MATCH (c)-[:HAS_PROFILE]->(cp:ClientProfile)`

## Related Documentation

- [Client Profile Completeness Score (CPCS)](./client-profile-completeness.md)
- [MCP Client Tools API](./mcp-client-tools.md)
- [Document Search Ranking](./document-ranking.md)
