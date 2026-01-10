#!/bin/bash
# =============================================================================
# GOFR-IQ Source Management Script
# =============================================================================
# Manage sources in GOFR-IQ by making MCP calls to list and create sources.
#
# Usage:
#   ./manage_source.sh list [OPTIONS]
#   ./manage_source.sh create --name NAME --url URL [OPTIONS]
#
# Commands:
#   list                  List all sources
#   create                Create a new source
#
# Options:
#   --host HOST          MCP server host (default: localhost)
#   --port PORT          MCP server port (default: from gofr_ports.sh)
#   --name NAME          Source name (required for create)
#   --url URL            Source URL (required for create)
#   --description DESC   Source description (optional for create)
#   --source-type TYPE   Source type (optional, default: news_agency)
#   --token TOKEN        JWT auth token (required for create - determines group)
#   --help, -h           Show this help message
#
# Examples:
#   # List all sources
#   ./manage_source.sh list
#
#   # List sources on custom port
#   ./manage_source.sh list --port 8180
#
#   # Create a new source (requires auth token)
#   ./manage_source.sh create \
#     --name "Reuters" \
#     --url "https://www.reuters.com" \
#     --description "International news agency" \
#     --token "$GOFR_IQ_ADMIN_TOKEN"
#
#   # Create source with all options
#   ./manage_source.sh create \
#     --name "Bloomberg" \
#     --url "https://www.bloomberg.com" \
#     --description "Financial news" \
#     --source-type "financial_news" \
#     --token "$GOFR_IQ_ADMIN_TOKEN" \
#     --host localhost \
#     --port 8080
# =============================================================================

set -e

# Get script directory and source port configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOFR_PORTS_SH="${SCRIPT_DIR}/../lib/gofr-common/config/gofr_ports.sh"

if [[ -f "$GOFR_PORTS_SH" ]]; then
    source "$GOFR_PORTS_SH"
fi

# Default values
MCP_HOST="${MCP_HOST:-localhost}"
MCP_PORT="${MCP_PORT:-${GOFR_IQ_MCP_PORT:-8080}}"
COMMAND=""
SOURCE_NAME=""
SOURCE_URL=""
SOURCE_DESCRIPTION=""
SOURCE_TYPE="news_agency"
AUTH_TOKEN=""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

show_help() {
    cat << 'EOF'
GOFR-IQ Source Management Script

Usage:
  ./manage_source.sh list [OPTIONS]
  ./manage_source.sh create --name NAME --url URL [OPTIONS]

Commands:
  list                  List all sources
  create                Create a new source

Options:
  --host HOST          MCP server host (default: localhost)
  --port PORT          MCP server port (default: from gofr_ports.sh)
  --name NAME          Source name (required for create)
  --url URL            Source URL (required for create)
  --description DESC   Source description (optional for create)
  --source-type TYPE   Source type (optional, default: news_agency)
  --token TOKEN        JWT auth token (required for create - determines group)
  --help, -h           Show this help message

Examples:
  # List all sources
  ./manage_source.sh list

  # List sources on custom port
  ./manage_source.sh list --port 8180

  # Create a new source (requires auth token)
  ./manage_source.sh create \
    --name "Reuters" \
    --url "https://www.reuters.com" \
    --description "International news agency" \
    --token "$GOFR_IQ_ADMIN_TOKEN"

  # Create source with all options
  ./manage_source.sh create \
    --name "Bloomberg" \
    --url "https://www.bloomberg.com" \
    --description "Financial news" \
    --source-type "financial_news" \
    --token "$GOFR_IQ_ADMIN_TOKEN" \
    --host localhost \
    --port 8080
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
                    "name": "manage_source.sh",
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
        log_error "Response: $response"
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

list_sources() {
    local host=$1
    local port=$2
    local auth_token=$3
    
    log_info "=== Listing Sources ==="
    log_info "Target: ${host}:${port}"
    [[ -n "$auth_token" ]] && log_info "Auth: Token provided (${#auth_token} chars)"
    echo ""
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Build arguments JSON
    local args
    if [[ -n "$auth_token" ]]; then
        args="{\"auth_tokens\": [\"${auth_token}\"]}"
    else
        args="{}"
    fi
    
    # Call list_sources tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "list_sources" "$args") || return 1
    
    # Parse and display response
    echo ""
    log_info "=== Response ==="
    parse_response "$response"
    
    return 0
}

create_source() {
    local host=$1
    local port=$2
    local name=$3
    local url=$4
    local description=$5
    local source_type=$6
    local auth_token=$7
    
    # Validate required parameters
    if [[ -z "$name" ]]; then
        log_error "Source name is required (--name)"
        return 1
    fi
    
    if [[ -z "$url" ]]; then
        log_error "Source URL is required (--url)"
        return 1
    fi
    
    if [[ -z "$auth_token" ]]; then
        log_error "Auth token is required (--token)"
        log_error "The token determines which group owns the source."
        log_error "Use GOFR_IQ_ADMIN_TOKEN or GOFR_IQ_PUBLIC_TOKEN from bootstrap."
        return 1
    fi
    
    log_info "=== Creating Source ==="
    log_info "Target: ${host}:${port}"
    log_info "Name: ${name}"
    log_info "URL: ${url}"
    [[ -n "$description" ]] && log_info "Description: ${description}"
    log_info "Type: ${source_type}"
    log_info "Auth: Token provided (${#auth_token} chars)"
    echo ""
    
    # Initialize session
    local session_id
    session_id=$(mcp_initialize "$host" "$port") || return 1
    
    # Build arguments JSON
    local args
    args=$(cat <<EOF
{
    "name": "${name}",
    "url": "${url}",
    "source_type": "${source_type}",
    "auth_tokens": ["${auth_token}"]
    $(if [[ -n "$description" ]]; then echo ", \"description\": \"${description}\""; fi)
}
EOF
)
    
    # Call create_source tool
    local response
    response=$(mcp_call_tool "$host" "$port" "$session_id" "create_source" "$args") || return 1
    
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
        --name)
            SOURCE_NAME="$2"
            shift 2
            ;;
        --url)
            SOURCE_URL="$2"
            shift 2
            ;;
        --description)
            SOURCE_DESCRIPTION="$2"
            shift 2
            ;;
        --source-type)
            SOURCE_TYPE="$2"
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

# Execute command
case $COMMAND in
    list)
        list_sources "$MCP_HOST" "$MCP_PORT" "$AUTH_TOKEN"
        ;;
    create)
        create_source "$MCP_HOST" "$MCP_PORT" "$SOURCE_NAME" "$SOURCE_URL" "$SOURCE_DESCRIPTION" "$SOURCE_TYPE" "$AUTH_TOKEN"
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
