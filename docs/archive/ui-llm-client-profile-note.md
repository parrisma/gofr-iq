# UI LLM Note: Client Profile Attributes (Display + Edit)

## Purpose
Enable the UI to **display and edit client profile attributes** that influence relevance and alerts. These attributes are stored on the `Client` or `ClientProfile` and should be surfaced in the Client 360 and edit flows.

## What to show (read)
Use `get_client_profile` to fetch current values and display:
- **Mandate Type** (`mandate_type`) – investment style.
- **Mandate Text** (`mandate_text`) – free-text fund mandate description (0-5000 chars, optional).
- **Benchmark** (`benchmark`) – ticker symbol (e.g., SPY).
- **Horizon** (`horizon`) – short | medium | long.
- **ESG Constrained** (`esg_constrained`) – boolean.
- **Alert Frequency** (`alert_frequency`) – realtime | hourly | daily | weekly.
- **Impact Threshold** (`impact_threshold`) – 0–100.

## How to edit (write)
Use MCP tool `update_client_profile` for partial updates. Only send the fields the user changed.

Required input:
- `client_guid`

Optional fields:
- `mandate_type`
- `mandate_text` (0-5000 chars, empty string clears field)
- `benchmark`
- `horizon`
- `esg_constrained`
- `alert_frequency`
- `impact_threshold`

## UX guidance
1. **Client 360 → Profile panel**
   - Show all fields with current values.
   - Add an “Edit” action that opens a modal or inline edit state.

2. **Edit form**
   - **Mandate Type**: dropdown with allowed values.
   - **Mandate Text**: multi-line textarea (4-6 rows), character counter showing "X / 5000 characters".
     - Expandable if text >200 chars.
     - Empty state: "No detailed mandate provided. Click to add."
     - Relationship note: "Use Mandate Type for category, Mandate Text for detailed description."
   - **Benchmark**: text input (uppercase ticker).
   - **Horizon**: segmented control (short/medium/long).
   - **ESG**: toggle.
   - **Alert Frequency**: dropdown.
   - **Impact Threshold**: slider (0–100) with numeric input.

3. **Save behavior**
   - Only send changed fields to `update_client_profile`.
   - On success, refresh using `get_client_profile`.

## Validation rules (UI + backend expectations)
- `alert_frequency`: realtime | hourly | daily | weekly.
- `impact_threshold`: 0–100.
- `horizon`: short | medium | long.
- `mandate_type`: equity_long_short | global_macro | event_driven | relative_value | fixed_income | multi_strategy.
- `mandate_text`: 0–5000 characters. Empty string clears field. Omitting preserves current value.

## CPCS Impact
- **mandate_text** contributes **17.5%** to overall Client Profile Completeness Score (CPCS).
- Specifically: 50% of the Mandate section (which is 35% of total CPCS).
- Adding mandate_text increases profile completeness, improving data quality metrics.

## Future Use
- **mandate_text** will be used to enhance document search ranking for clients.
- Semantic matching will compare document content to mandate description.
- This enables more relevant news/research filtering based on detailed investment guidelines.

## Error handling
- If `update_client_profile` returns `INVALID_ALERT_FREQUENCY` or `INVALID_HORIZON`, show field-level validation.
- If `MANDATE_TEXT_TOO_LONG`, show error: "Mandate text exceeds 5000 character limit. Please shorten."
- If `CLIENT_NOT_FOUND`, prompt user to reselect client.

## API hostnames
When referencing services, use container hostnames (e.g., `gofr-iq-mcp`) rather than `localhost`.
