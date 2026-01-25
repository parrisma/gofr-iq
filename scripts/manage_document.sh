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
#   # Ingest a document (token determines group ownership)
#   ./manage_document.sh ingest \
#     --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \
#     --title "Tech stocks surge" \
#     --content "Full article text..." \
#     --token "$US_SALES_TOKEN"
#
#   # Query documents
#   ./manage_document.sh query \
#     --query "AI regulation" \
#     --n-results 5 \
#     --token "$US_SALES_TOKEN"
# =============================================================================

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load port configuration from .env file
if [ -f "$PROJECT_DIR/lib/gofr-common/config/gofr_ports.env" ]; then
    set -a  # automatically export all variables
    source "$PROJECT_DIR/lib/gofr-common/config/gofr_ports.env"
    set +a
fi

# Environment mode: prod (docker) or dev (default: prod)
ENV_MODE="prod"

# Default values (will be set based on ENV_MODE)
MCP_HOST=""  # Will be set after parsing --docker/--dev flags
MCP_PORT=""  # Will be set after parsing --docker/--dev flags
SOURCE_GUID=""
TITLE=""
CONTENT=""
CONTENT_FILE=""
LANGUAGE=""
QUERY=""
N_RESULTS=10
AUTH_TOKEN=""

# Delete-specific variables
DOCUMENT_GUID=""
GROUP_GUID=""
DATE_HINT=""
CONFIRM="false"

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
  ./manage_document.sh delete [OPTIONS]

Commands:
  ingest                Ingest a document into the system
  query                 Search for documents
  stats                 Get document statistics (counts)
  delete                Permanently delete a document (admin only)

Ingest Options:
  --docker, --prod     Use production docker ports (default, port 8180)
  --dev                Use development ports (port 8080)
  --host HOST          MCP server host (override auto-detection)
  --port PORT          MCP server port (override auto-detection)
  --source-guid GUID   Source UUID (required - use manage_source.sh to list sources)
  --title TITLE        Document title (required)
  --content TEXT       Document content (required if --content-file not used)
  --content-file FILE  Read content from file
  --language CODE      Language code (en/zh/ja) - auto-detected if omitted
  --token TOKEN        JWT auth token (required - determines group)

Query Options:
  --docker, --prod     Use production docker ports (default, port 8180)
  --dev                Use development ports (port 8080)
  --host HOST          MCP server host (override auto-detection)
  --port PORT          MCP server port (override auto-detection)
  --query TEXT         Search query (required)
  --n-results NUM      Max results to return (default: 10)
  --token TOKEN        JWT auth token (required - for group-based access)

Delete Options:
  --docker, --prod     Use production docker ports (default, port 8180)
  --dev                Use development ports (port 8080)
  --host HOST          MCP server host (override auto-detection)
  --port PORT          MCP server port (override auto-detection)
  --document-guid GUID Document UUID to delete (required)
  --group-guid GUID    Group UUID containing the document (required)
  --date YYYY-MM-DD    Document creation date (optional, speeds lookup)
  --confirm            Must be present to execute deletion (safety check)
  --token TOKEN        JWT auth token (admin required)
  
Common Options:
  --help, -h           Show this help message

AUTHENTICATION:
  This script requires a JWT auth token (--token flag).
  
  IMPORTANT: The token's group determines document ownership.
  - Token with 'us-sales' group → document belongs to 'us-sales'
  - Token with 'apac-sales' group → document belongs to 'apac-sales'
  - Admin token → document belongs to 'admin' group
  
  To obtain tokens:
  
  1. From bootstrap (365-day admin/public tokens):
     cat secrets/bootstrap_tokens.json
  
  2. Create group-specific tokens:
     source <(./lib/gofr-common/scripts/auth_env.sh --docker)
     ./lib/gofr-common/scripts/auth_manager.sh --docker tokens create \
       --groups us-sales --name my-token --expires 31536000
  
  See: lib/gofr-common/scripts/readme.md

Examples:
  # Ingest a document (token determines group ownership)
  ./manage_document.sh ingest \
    --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \
    --title "Tech stocks surge on AI optimism" \
    --content "Technology stocks rallied today..." \
    --token "\$US_SALES_TOKEN"

  # Ingest from file
  ./manage_document.sh ingest \\
    --source-guid "3987a6e4-c06c-44b6-959a-81aae7986ea3" \\
    --title "Market Analysis" \\
    --content-file article.txt \\
    --language en \\
    --token "\$APAC_SALES_TOKEN"

  # Query documents (returns only docs accessible to token's group)
  ./manage_document.sh query \\
    --query "AI regulation China" \\
    --n-results 5 \\
    --token "\$US_SALES_TOKEN"

  # Query on Docker network
  ./manage_document.sh query \\
    --host gofr-iq-mcp \\
    --query "earnings surprises" \\
    --n-results 10 \\
    --token "\$APAC_SALES_TOKEN"

  # Delete a document (requires admin token and --confirm flag)
  ./manage_document.sh delete \\
    --document-guid "550e8400-e29b-41d4-a716-446655440000" \\
    --group-guid "a1b2c3d4-e5f6-7890-abcd-ef1234567890" \\
    --confirm \\
    --token "\$ADMIN_TOKEN"

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
    parse_response "$response" || return 1
    
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
    
    if [[ -z "$auth_token" ]]; then
        log_error "Auth token is required (--token)"
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
    args="{\"query\": ${escaped_query}, \"n_results\": ${n_results}, \"auth_tokens\": [\"${auth_token}\"]}"
    
    # Call query_documents tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "query_documents" "$args") || return 1
    
    # Parse and display response
    echo ""
    log_info "=== Response ==="
    parse_response "$response" || return 1
    
    return 0
}

stats_documents() {
    local host=$1
    local port=$2
    local auth_token=$3
    
    # Validate required parameters
    if [[ -z "$auth_token" ]]; then
        log_error "Auth token is required (--token)"
        return 1
    fi
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Query with broad term to get total_found count
    local escaped_query
    escaped_query=$(echo "a" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')
    
    # Build arguments JSON - request just 1 result to minimize data transfer
    local args
    args="{\"query\": ${escaped_query}, \"n_results\": 1, \"auth_tokens\": [\"${auth_token}\"]}"
    
    # Call query_documents tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "query_documents" "$args") || return 1
    
    # Parse response and extract stats
    local json_data
    json_data=$(echo "$response" | grep "^data:" | sed 's/^data: //')
    
    if [[ -z "$json_data" ]]; then
        log_error "Empty response from server"
        return 1
    fi
    
    # Extract and format statistics using Python via stdin
    echo "$json_data" | python3 -c '
import sys
import json

try:
    data = json.load(sys.stdin)
    content = data.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "{}")
        inner = json.loads(text)
        result_data = inner.get("data", {})
        total_found = result_data.get("total_found", 0)
        exec_time = result_data.get("execution_time_ms", 0)
        
        print(f"Total Documents: {total_found}")
        print(f"Query Time: {exec_time:.1f}ms")
    else:
        print("Total Documents: 0")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
'
    
    return 0
}

delete_document() {
    local host=$1
    local port=$2
    local document_guid=$3
    local group_guid=$4
    local date_hint=$5
    local confirm=$6
    local auth_token=$7
    
    # Validate required parameters
    if [[ -z "$document_guid" ]]; then
        log_error "Document GUID is required (--document-guid)"
        return 1
    fi
    
    if [[ -z "$group_guid" ]]; then
        log_error "Group GUID is required (--group-guid)"
        return 1
    fi
    
    if [[ -z "$auth_token" ]]; then
        log_error "Admin token is required (--token)"
        return 1
    fi
    
    if [[ "$confirm" != "true" ]]; then
        echo -e "${YELLOW}=== DELETION NOT CONFIRMED ===${NC}" >&2
        log_warning "This operation will PERMANENTLY delete:"
        log_warning "  - Document file from storage"
        log_warning "  - All vector embeddings from ChromaDB"
        log_warning "  - All graph entries from Neo4j"
        echo "" >&2
        log_warning "Document GUID: ${document_guid}"
        log_warning "Group GUID: ${group_guid}"
        echo "" >&2
        log_warning "To execute, add --confirm flag to command"
        return 1
    fi
    
    echo -e "${RED}=== DELETING DOCUMENT ===${NC}" >&2
    log_info "Target: ${host}:${port}"
    log_info "Document GUID: ${document_guid}"
    log_info "Group GUID: ${group_guid}"
    [[ -n "$date_hint" ]] && log_info "Date hint: ${date_hint}"
    log_info "Auth: Admin token provided (${#auth_token} chars)"
    echo ""
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Build arguments JSON
    local args="{\"document_guid\": \"${document_guid}\", \"group_guid\": \"${group_guid}\", \"confirm\": true"
    [[ -n "$date_hint" ]] && args="${args}, \"date_hint\": \"${date_hint}\""
    args="${args}, \"auth_tokens\": [\"${auth_token}\"]}"
    
    # Call delete_document tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "delete_document" "$args") || return 1
    
    # Parse and display response
    echo ""
    log_info "=== Response ==="
    parse_response "$response" || return 1
    
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
        --docker|--prod)
            ENV_MODE="prod"
            shift
            ;;
        --dev)
            ENV_MODE="dev"
            shift
            ;;
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
        --document-guid)
            DOCUMENT_GUID="$2"
            shift 2
            ;;
        --group-guid)
            GROUP_GUID="$2"
            shift 2
            ;;
        --date)
            DATE_HINT="$2"
            shift 2
            ;;
        --confirm)
            CONFIRM="true"
            shift
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

# Set host and port based on environment mode if not explicitly provided
if [[ -z "$MCP_HOST" ]]; then
    if [[ "$ENV_MODE" == "prod" ]]; then
        MCP_HOST="gofr-iq-mcp"
    else
        MCP_HOST="localhost"
    fi
fi

if [[ -z "$MCP_PORT" ]]; then
    if [[ "$ENV_MODE" == "prod" ]]; then
        MCP_PORT="${GOFR_IQ_MCP_PORT:-8080}"
    else
        MCP_PORT="${GOFR_IQ_MCP_PORT_TEST:-8280}"
    fi
fi

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
    stats)
        stats_documents "$MCP_HOST" "$MCP_PORT" "$AUTH_TOKEN"
        ;;
    delete)
        delete_document "$MCP_HOST" "$MCP_PORT" "$DOCUMENT_GUID" "$GROUP_GUID" "$DATE_HINT" "$CONFIRM" "$AUTH_TOKEN"
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
