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

# Get script directory and load port configuration from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOFR_PORTS_ENV="${SCRIPT_DIR}/../lib/gofr-common/config/gofr_ports.env"

if [[ -f "$GOFR_PORTS_ENV" ]]; then
    set -a  # automatically export all variables
    source "$GOFR_PORTS_ENV"
    set +a
fi

# Environment mode: prod (docker) or dev (default: prod)
ENV_MODE="prod"

# Default values (will be set based on ENV_MODE)
MCP_HOST=""  # Will be set after parsing --docker/--dev flags
MCP_PORT=""  # Will be set after parsing --docker/--dev flags
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
  --docker, --prod     Use production docker ports (default, port 8180)
  --dev                Use development ports (port 8080)
  --host HOST          MCP server host (default: localhost)
  --port PORT          MCP server port (override auto-detection)
  --name NAME          Source name (required for create)
  --url URL            Source URL (required for create)
  --description DESC   Source description (optional for create)
  --source-type TYPE   Source type (optional, default: news_agency)
  --token TOKEN        JWT auth token (required for create - determines group)
  --help, -h           Show this help message

Examples:
  # List all sources (production docker)
  ./manage_source.sh list --docker

  # List sources in dev mode
  ./manage_source.sh list --dev

  # List sources on custom port
  ./manage_source.sh list --docker --port 8180

  # Create a new source (requires auth token)
  ./manage_source.sh create --docker \
    --name "Reuters" \
    --url "https://www.reuters.com" \
    --description "International news agency" \
    --token "$GOFR_ADMIN_TOKEN"

  # Create source with all options
  ./manage_source.sh create --docker \
    --name "Bloomberg" \
    --url "https://www.bloomberg.com" \
    --description "Financial news" \
    --source-type "financial_news" \
    --token "$APAC_SALES_TOKEN" \
    --host localhost
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

# Format and display list sources response
format_list_sources() {
    local json_data=$1
    
    # Extract the inner JSON from the text field
    local sources_json
    sources_json=$(echo "$json_data" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'result' in data and 'content' in data['result']:
    content = data['result']['content']
    if content and len(content) > 0 and 'text' in content[0]:
        inner = json.loads(content[0]['text'])
        print(json.dumps(inner))
" 2>/dev/null)
    
    if [[ -z "$sources_json" ]]; then
        log_error "Failed to parse response"
        return 1
    fi
    
    # Check for errors in inner JSON
    if echo "$sources_json" | grep -q '"status".*:.*"error"'; then
        log_error "API Error:"
        echo "$sources_json" | python3 -m json.tool
        return 1
    fi
    
    # Format sources table
    echo ""
    echo "Source GUID                          Name              Type          Languages  Trust        Active"
    echo "-------------------------------------------------------------------------------------------------------"
    
    echo "$sources_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'data' in data and 'sources' in data['data']:
    sources = data['data']['sources']
    for source in sources:
        guid = source.get('source_guid', 'N/A')[:36]
        name = source.get('name', 'N/A')[:16]
        stype = source.get('type', 'N/A')[:12]
        langs = ','.join(source.get('languages', ['N/A']))[:10]
        trust = source.get('trust_level', 'N/A')[:12]
        active = 'yes' if source.get('active', False) else 'no'
        print(f'{guid:<36} {name:<16} {stype:<12} {langs:<10} {trust:<12} {active}')
    count = data['data'].get('count', 0)
    print(f'\nTotal: {count} source(s)')
" 2>/dev/null
    
    return 0
}

# Format and display create source response
format_create_source() {
    local json_data=$1
    
    # Extract the inner JSON from the text field
    local result_json
    result_json=$(echo "$json_data" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'result' in data and 'content' in data['result']:
    content = data['result']['content']
    if content and len(content) > 0 and 'text' in content[0]:
        inner = json.loads(content[0]['text'])
        print(json.dumps(inner))
" 2>/dev/null)
    
    if [[ -z "$result_json" ]]; then
        log_error "Failed to parse response"
        return 1
    fi
    
    # Check for errors
    if echo "$result_json" | grep -q '"status".*:.*"error"'; then
        log_error "API Error:"
        echo "$result_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Error: {data.get('message', 'Unknown error')}\")
if 'recovery_strategy' in data:
    print(f\"Hint: {data['recovery_strategy']}\")
if 'details' in data:
    print(f\"Details: {json.dumps(data['details'])}\")
" 2>/dev/null
        return 1
    fi
    
    # Display success
    echo ""
    log_success "Source created successfully!"
    echo ""
    echo "$result_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if 'data' in data:
    info = data['data']
    print(f\"Source GUID:   {info.get('source_guid', 'N/A')}\")
    print(f\"Name:          {info.get('name', 'N/A')}\")
    print(f\"Type:          {info.get('type', 'N/A')}\")
    print(f\"Languages:     {', '.join(info.get('languages', []))}\")
    print(f\"Trust Level:   {info.get('trust_level', 'N/A')}\")
    print(f\"Active:        {'yes' if info.get('active', False) else 'no'}\")
    print(f\"Created:       {info.get('created_at', 'N/A')}\")
" 2>/dev/null
    
    return 0
}

# Parse and display tool response
parse_response() {
    local response=$1
    local operation=$2  # "list" or "create"
    
    # Extract data from SSE format
    local json_data
    json_data=$(echo "$response" | grep "^data:" | sed 's/^data: //')
    
    if [[ -z "$json_data" ]]; then
        log_error "Empty response from server"
        return 1
    fi
    
    # Check for errors at MCP level
    if echo "$json_data" | grep -q '"error"'; then
        log_error "MCP error occurred:"
        echo "$json_data" | python3 -m json.tool 2>/dev/null || echo "$json_data"
        return 1
    fi
    
    # Format based on operation type
    case "$operation" in
        list)
            format_list_sources "$json_data"
            ;;
        create)
            format_create_source "$json_data"
            ;;
        *)
            # Fallback to JSON output
            echo "$json_data" | python3 -m json.tool 2>/dev/null || echo "$json_data"
            ;;
    esac
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
    parse_response "$response" "list"
    
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
    parse_response "$response" "create"
    
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
        MCP_PORT="${GOFR_IQ_MCP_PORT_TEST:-8180}"
    else
        MCP_PORT="${GOFR_IQ_MCP_PORT:-8080}"
    fi
fi

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
