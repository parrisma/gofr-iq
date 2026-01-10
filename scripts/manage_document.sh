#!/bin/bash
# =============================================================================
# GOFR-IQ Document Management Script
# =============================================================================
# Provides document ingestion and query operations via MCP server.
#
# Usage:
#   ./manage_document.sh ingest --source-guid <UUID> --title "..." --content "..." --token <JWT>
#   ./manage_document.sh query --query "search terms" [--token <JWT>]
#
# Examples:
#   # Ingest a document
#   ./manage_document.sh ingest \
#     --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \
#     --title "Tech stocks surge" \
#     --content "Full article text..." \
#     --token "$GOFR_IQ_ADMIN_TOKEN"
#
#   # Query documents
#   ./manage_document.sh query \
#     --query "AI regulation" \
#     --n-results 5 \
#     --token "$GOFR_IQ_ADMIN_TOKEN"
# =============================================================================

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source port configuration
if [ -f "$PROJECT_DIR/lib/gofr-common/config/gofr_ports.sh" ]; then
    source "$PROJECT_DIR/lib/gofr-common/config/gofr_ports.sh"
fi

# Default values
MCP_HOST="${GOFR_IQ_MCP_HOST:-localhost}"
MCP_PORT="${GOFR_IQ_MCP_PORT:-8080}"
SOURCE_GUID=""
TITLE=""
CONTENT=""
CONTENT_FILE=""
LANGUAGE=""
QUERY=""
N_RESULTS=10
AUTH_TOKEN=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

show_help() {
    cat << EOF
GOFR-IQ Document Management Script

Usage:
  ./manage_document.sh ingest [OPTIONS]
  ./manage_document.sh query [OPTIONS]

Commands:
  ingest                Ingest a document into the system
  query                 Search for documents

Ingest Options:
  --host HOST          MCP server host (default: localhost)
  --port PORT          MCP server port (default: from gofr_ports.sh)
  --source-guid GUID   Source UUID (required - use manage_source.sh to list sources)
  --title TITLE        Document title (required)
  --content TEXT       Document content (required if --content-file not used)
  --content-file FILE  Read content from file
  --language CODE      Language code (en/zh/ja) - auto-detected if omitted
  --token TOKEN        JWT auth token (required - determines group)

Query Options:
  --host HOST          MCP server host (default: localhost)
  --port PORT          MCP server port (default: from gofr_ports.sh)
  --query TEXT         Search query (required)
  --n-results NUM      Max results to return (default: 10)
  --token TOKEN        JWT auth token (optional - for group-based access)
  
Common Options:
  --help, -h           Show this help message

Examples:
  # Ingest a document
  ./manage_document.sh ingest \\
    --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \\
    --title "Tech stocks surge on AI optimism" \\
    --content "Technology stocks rallied today..." \\
    --token "\$GOFR_IQ_ADMIN_TOKEN"

  # Ingest from file
  ./manage_document.sh ingest \\
    --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \\
    --title "Market Analysis" \\
    --content-file article.txt \\
    --language en \\
    --token "\$GOFR_IQ_ADMIN_TOKEN"

  # Query documents
  ./manage_document.sh query \\
    --query "AI regulation China" \\
    --n-results 5 \\
    --token "\$GOFR_IQ_ADMIN_TOKEN"

  # Query on Docker network
  ./manage_document.sh query \\
    --host gofr-iq-mcp \\
    --query "earnings surprises" \\
    --n-results 10

EOF
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

# Initialize MCP session and return session ID
mcp_initialize() {
    local host=$1
    local port=$2
    
    log_info "Initializing MCP session at ${host}:${port}..."
    
    # Make request and save headers to temp file
    local temp_headers=$(mktemp)
    curl -s -D "$temp_headers" -X POST "http://${host}:${port}/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "manage_document.sh",
                    "version": "1.0.0"
                }
            }
        }' > /dev/null 2>&1
    
    # Extract session ID from header
    local session_id
    session_id=$(grep -i "mcp-session-id:" "$temp_headers" | cut -d: -f2 | tr -d ' \r')
    rm -f "$temp_headers"
    
    if [[ -z "$session_id" ]]; then
        log_error "Failed to initialize MCP session"
        return 1
    fi
    
    log_success "Session initialized: ${session_id}"
    echo "$session_id"
}

# Call MCP tool and return response
mcp_call_tool() {
    local host=$1
    local port=$2
    local session_id=$3
    local tool_name=$4
    local arguments=$5
    
    log_info "Calling tool: ${tool_name}..."
    
    local response
    response=$(curl -s -X POST "http://${host}:${port}/mcp" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "mcp-session-id: ${session_id}" \
        -d "{
            \"jsonrpc\": \"2.0\",
            \"id\": 2,
            \"method\": \"tools/call\",
            \"params\": {
                \"name\": \"${tool_name}\",
                \"arguments\": ${arguments}
            }
        }" 2>/dev/null)
    
    echo "$response"
}

# Parse and display tool response
parse_response() {
    local response=$1
    
    # Extract data from SSE format
    local json_data
    json_data=$(echo "$response" | grep "^data:" | sed 's/^data: //')
    
    if [[ -z "$json_data" ]]; then
        log_error "Empty response from server"
        return 1
    fi
    
    # Check for errors
    if echo "$json_data" | grep -q '"error"'; then
        log_error "MCP error occurred:"
        echo "$json_data" | python3 -m json.tool 2>/dev/null || echo "$json_data"
        return 1
    fi
    
    # Pretty print the response
    echo "$json_data" | python3 -m json.tool 2>/dev/null || echo "$json_data"
}

# =============================================================================
# Command Implementations
# =============================================================================

ingest_document() {
    local host=$1
    local port=$2
    local source_guid=$3
    local title=$4
    local content=$5
    local language=$6
    local auth_token=$7
    
    # Validate required parameters
    if [[ -z "$source_guid" ]]; then
        log_error "Source GUID is required (--source-guid)"
        return 1
    fi
    
    if [[ -z "$title" ]]; then
        log_error "Document title is required (--title)"
        return 1
    fi
    
    if [[ -z "$content" ]]; then
        log_error "Document content is required (--content or --content-file)"
        return 1
    fi
    
    if [[ -z "$auth_token" ]]; then
        log_error "Auth token is required (--token)"
        log_error "The token determines which group owns the document."
        return 1
    fi
    
    log_info "=== Ingesting Document ==="
    log_info "Target: ${host}:${port}"
    log_info "Source GUID: ${source_guid}"
    log_info "Title: ${title}"
    log_info "Content length: ${#content} chars"
    [[ -n "$language" ]] && log_info "Language: ${language}"
    log_info "Auth: Token provided (${#auth_token} chars)"
    echo ""
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Escape content for JSON
    local escaped_content
    escaped_content=$(echo "$content" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
    
    local escaped_title
    escaped_title=$(echo "$title" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
    
    # Build arguments JSON
    local args
    if [[ -n "$language" ]]; then
        args="{\"source_guid\": \"${source_guid}\", \"title\": ${escaped_title}, \"content\": ${escaped_content}, \"language\": \"${language}\", \"auth_tokens\": [\"${auth_token}\"]}"
    else
        args="{\"source_guid\": \"${source_guid}\", \"title\": ${escaped_title}, \"content\": ${escaped_content}, \"auth_tokens\": [\"${auth_token}\"]}"
    fi
    
    # Call ingest_document tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "ingest_document" "$args") || return 1
    
    # Parse and display response
    echo ""
    log_info "=== Response ==="
    parse_response "$response"
    
    return 0
}

query_documents() {
    local host=$1
    local port=$2
    local query=$3
    local n_results=$4
    local auth_token=$5
    
    # Validate required parameters
    if [[ -z "$query" ]]; then
        log_error "Search query is required (--query)"
        return 1
    fi
    
    log_info "=== Querying Documents ==="
    log_info "Target: ${host}:${port}"
    log_info "Query: ${query}"
    log_info "Max results: ${n_results}"
    [[ -n "$auth_token" ]] && log_info "Auth: Token provided (${#auth_token} chars)"
    echo ""
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Escape query for JSON
    local escaped_query
    escaped_query=$(echo "$query" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
    
    # Build arguments JSON
    local args
    if [[ -n "$auth_token" ]]; then
        args="{\"query\": ${escaped_query}, \"n_results\": ${n_results}, \"auth_tokens\": [\"${auth_token}\"]}"
    else
        args="{\"query\": ${escaped_query}, \"n_results\": ${n_results}}"
    fi
    
    # Call query_documents tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "query_documents" "$args") || return 1
    
    # Parse and display response
    echo ""
    log_info "=== Response ==="
    parse_response "$response"
    
    return 0
}

# =============================================================================
# Main Script
# =============================================================================

# Parse command line arguments
if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi

# First argument is the command
COMMAND=$1
shift

# Parse remaining arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --host)
            MCP_HOST="$2"
            shift 2
            ;;
        --port)
            MCP_PORT="$2"
            shift 2
            ;;
        --source-guid)
            SOURCE_GUID="$2"
            shift 2
            ;;
        --title)
            TITLE="$2"
            shift 2
            ;;
        --content)
            CONTENT="$2"
            shift 2
            ;;
        --content-file)
            CONTENT_FILE="$2"
            shift 2
            ;;
        --language)
            LANGUAGE="$2"
            shift 2
            ;;
        --query)
            QUERY="$2"
            shift 2
            ;;
        --n-results)
            N_RESULTS="$2"
            shift 2
            ;;
        --token)
            AUTH_TOKEN="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

# Read content from file if specified
if [[ -n "$CONTENT_FILE" ]] && [[ -z "$CONTENT" ]]; then
    if [[ ! -f "$CONTENT_FILE" ]]; then
        log_error "Content file not found: $CONTENT_FILE"
        exit 1
    fi
    CONTENT=$(cat "$CONTENT_FILE")
fi

# Execute command
case $COMMAND in
    ingest)
        ingest_document "$MCP_HOST" "$MCP_PORT" "$SOURCE_GUID" "$TITLE" "$CONTENT" "$LANGUAGE" "$AUTH_TOKEN"
        ;;
    query)
        query_documents "$MCP_HOST" "$MCP_PORT" "$QUERY" "$N_RESULTS" "$AUTH_TOKEN"
        ;;
    help|-h|--help)
        show_help
        exit 0
        ;;
    *)
        log_error "Unknown command: $COMMAND"
        echo ""
        show_help
        exit 1
        ;;
esac
