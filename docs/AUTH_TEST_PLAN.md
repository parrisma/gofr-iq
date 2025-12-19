# Authentication Test Plan

## Objective
Verify that authentication works correctly in both enabled and disabled modes across all layers (GroupService, Tools, MCP Server, MCPO).

## Test Categories

### 1. Unit Tests: GroupService (`test/test_group_service_auth.py`)

#### Test 1.1: `test_resolve_write_group_no_auth_no_token`
**Goal:** When auth is disabled globally, anonymous users should write to 'public'
- Setup: `init_group_service(auth_service=None)`
- Action: `resolve_write_group(auth_tokens=None)`
- Expected: Returns `"public"`

#### Test 1.2: `test_resolve_write_group_no_auth_empty_list`
**Goal:** Empty auth_tokens list with no auth should return 'public'
- Setup: `init_group_service(auth_service=None)`
- Action: `resolve_write_group(auth_tokens=[])`
- Expected: Returns `"public"`

#### Test 1.3: `test_resolve_write_group_auth_enabled_no_token`
**Goal:** When auth is enabled, anonymous users cannot write
- Setup: `init_group_service(auth_service=<real AuthService>)`
- Action: `resolve_write_group(auth_tokens=None)`
- Expected: Returns `None`

#### Test 1.4: `test_resolve_write_group_auth_enabled_with_valid_token`
**Goal:** When auth is enabled, valid token should return group
- Setup: `init_group_service(auth_service=<real AuthService>)`
- Action: Create valid token, call `resolve_write_group(auth_tokens=[token])`
- Expected: Returns the token's primary group

#### Test 1.5: `test_resolve_write_group_auth_enabled_empty_list`
**Goal:** Empty auth_tokens list with auth enabled should return None
- Setup: `init_group_service(auth_service=<real AuthService>)`
- Action: `resolve_write_group(auth_tokens=[])`
- Expected: Returns `None`

### 2. Integration Tests: Source Tools (`test/test_source_tools_auth.py`)

#### Test 2.1: `test_create_source_no_auth_mode`
**Goal:** create_source works without token when auth disabled
- Setup: `init_group_service(auth_service=None)`
- Action: Call `create_source(..., auth_tokens=None)`
- Expected: Success, `group_guid="public"`

#### Test 2.2: `test_create_source_auth_mode_no_token`
**Goal:** create_source fails without token when auth enabled
- Setup: `init_group_service(auth_service=<real AuthService>)`
- Action: Call `create_source(..., auth_tokens=None)`
- Expected: Error response with `error_code="AUTH_REQUIRED"`

#### Test 2.3: `test_create_source_auth_mode_with_token`
**Goal:** create_source succeeds with valid token when auth enabled
- Setup: `init_group_service(auth_service=<real AuthService>)`
- Action: Create token, call `create_source(..., auth_tokens=[token])`
- Expected: Success, `group_guid=<token's group>`

### 3. End-to-End: MCP Server (`test/test_mcp_server_auth.py`)

#### Test 3.1: `test_mcp_server_no_auth_allows_anonymous`
**Goal:** MCP server with --no-auth allows anonymous writes
- Setup: `create_mcp_server(require_auth=False)`
- Action: POST to tool endpoint without Authorization header
- Expected: 200 OK, successful response

#### Test 3.2: `test_mcp_server_auth_rejects_anonymous`
**Goal:** MCP server with auth rejects anonymous writes
- Setup: `create_mcp_server(require_auth=True)`
- Action: POST to tool endpoint without Authorization header
- Expected: 200 OK with error body (`error_code="AUTH_REQUIRED"`)

#### Test 3.3: `test_mcp_server_auth_accepts_valid_token`
**Goal:** MCP server with auth accepts valid Bearer token
- Setup: `create_mcp_server(require_auth=True)`
- Action: POST with `Authorization: Bearer <valid-token>`
- Expected: 200 OK, successful response

## Implementation Order

1. ✅ Document created
2. ✅ Test 1.1: resolve_write_group no-auth + no token (PASSED)
3. ✅ Test 1.2: resolve_write_group no-auth + empty list (PASSED)
4. ✅ Test 1.3: resolve_write_group auth-enabled + no token (PASSED)
5. ✅ Test 1.4: resolve_write_group auth-enabled + valid token (PASSED)
6. ✅ Test 1.5: resolve_write_group auth-enabled + empty list (PASSED)
7. ⏳ Test 2.1: create_source no-auth mode
8. ⏳ Test 2.2: create_source auth mode no token
9. ⏳ Test 2.3: create_source auth mode with token
10. ⏳ Test 3.1: MCP server no-auth
11. ⏳ Test 3.2: MCP server auth rejects anonymous
12. ⏳ Test 3.3: MCP server auth accepts valid token

## Success Criteria

All tests pass, demonstrating:
- No-auth mode allows writes without tokens
- Auth-enabled mode requires valid tokens for writes
- Auth-enabled mode rejects anonymous write attempts
