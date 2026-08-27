# Hermes MCP Server

Unified MCP (Model Context Protocol) server for **Hermes Agent** capabilities —
knowledge retrieval, messaging, webhook management, cron jobs, and general utilities.

## Quick Start

```bash
# Install
cd D:\Replica1.0\hermes\MCP
pip install -e .

# Run (stdio — for Claude Desktop)
python -m hermes_mcp

# Run (HTTP — for remote clients)
python -m hermes_mcp --http --port 9200
```

### Controlled full-business Feishu service

The Agent profile uses the isolated `hermes-lark-cli` service. It exposes three
control tools (`lark_cli_help`, `lark_cli_schema`, and `lark_cli_execute`) over
the approved lark-cli business domains: approval, apps, attendance, Base,
calendar, contacts, docs, drive, events, IM, mail, Markdown, mindnotes,
minutes, notes, OKR, sheets, slides, tasks, video conferences, whiteboards,
and Wiki.

All business calls force the local lark-cli **user** identity and use an argv
array with the native executable. The service does not expose a shell, raw
`lark-cli api`, `auth`, `config`, `profile`, `doctor`, `update`, or `skills`.
Model-supplied `--as`, `--profile`, output-format controls, and `--yes` are
rejected. Local file arguments must be relative paths below `HERMES_HOME`.

```bash
# Run over stdio (recommended for Hermes)
python -m hermes_mcp.lark_cli_full

# Register the stdio service with Hermes after installing Hermes' MCP extra
hermes mcp add hermes-lark-cli --command python \
  --env PYTHONPATH=D:\Replica1.0\hermes\MCP\src \
  --env HERMES_HOME=D:\Replica1.0\hermes \
  --args -m hermes_mcp.lark_cli_full
hermes mcp test hermes-lark-cli
```

Before any real query, configure the target Feishu application and complete
the local user OAuth flow. Verify with `lark-cli auth status --json --verify`;
the service does not fall back to the bot identity.

Scopes remain business-specific: application scopes must be enabled in the
Feishu developer console and then granted to the local user. `auth login` is an
operator action and is intentionally unavailable to the model. After
authorization, verify the registration:

```powershell
$env:HERMES_HOME = "D:\Replica1.0\hermes"
hermes mcp test hermes-lark-cli
```

When lark-cli returns exit code 10 for a high-risk write, the first tool result
contains a short-lived one-time `approval_id`. The model must show the action,
risk, and arguments to the user. Only an explicit confirmation permits a retry
with the same argv, that id, and `confirmed=true`; the adapter then appends one
`--yes` and consumes the ticket before launch.

Full mode does not bypass Feishu visibility or retention. It cannot recover
deleted data, history outside tenant retention, resources the user cannot see,
or APIs/scopes unavailable to the bound application. The legacy
`hermes-feishu-readonly` module remains in the source tree for rollback tests
but is not selected by Agent Hermes.

### Web research to Feishu documents

The three lark-cli tools are controlled entry points, not a three-feature
limit. `lark_cli_execute` can create and update normal Feishu document content
through `docs +create` and `docs +update`, as well as access the other approved
business domains listed above.

Web research is a separate Hermes built-in toolset. The Agent API profile
enables `web` beside `hermes-lark-cli`, which supports this workflow:

1. `web_search` discovers public sources and `web_extract` reads required
   source details.
2. Hermes synthesizes a title, paragraphs, and lists as the actual document
   body.
3. `lark_cli_execute` writes that body to a new or identified Feishu document.
4. The document ends with a reference section containing the URLs actually
   used. URLs support verification; they do not replace the written content.

The project default is the no-key `ddgs` backend. It provides live search
results and summaries but is search-only; `web_extract` requires configuring a
supported extraction provider such as Tavily, Exa, or Firecrawl.

Document mutation requires an explicit user request to write, create, or
update the Feishu document. Search-only and draft-only requests do not mutate
Feishu. Knowledge Hermes remains isolated from both Web and lark-cli tools.

## Claude Desktop Configuration

```json
{
  "mcpServers": {
    "hermes-mcp": {
      "command": "python",
      "args": ["-m", "hermes_mcp"],
      "cwd": "D:/Replica1.0/hermes/MCP"
    }
  }
}
```

## Hermes Integration

```bash
# Register this MCP server with Hermes
python -m hermes_mcp --http --port 9200 &
hermes mcp add hermes-mcp --url http://127.0.0.1:9200/mcp

# Or install as a Hermes Plugin
cp -r src/hermes_mcp/plugin/ ~/.hermes/plugins/hermes-mcp/
hermes plugins enable hermes-mcp
```

## Available Tools

### Knowledge Retrieval
| Tool | Description |
|------|-------------|
| `search_knowledge` | Search three knowledge sources (Experience/Database/Knowledge) |
| `get_retrieval_status` | Check retrieval service health |

### Feishu (controlled full mode)
| Tool | Description |
|------|-------------|
| `lark_cli_help` | Browse the root or an approved business domain and prefer shortcuts |
| `lark_cli_schema` | Inspect typed method parameters, scopes, and risk without accessing Feishu |
| `lark_cli_execute` | Execute a validated business argv as the authorized user, with one-time confirmation for high-risk writes |

### Messaging
| Tool | Description |
|------|-------------|
| `send_message` | Send messages via Hermes gateway |
| `list_platforms` | List configured messaging platforms |
| `test_platform` | Test platform connectivity |

### Webhooks
| Tool | Description |
|------|-------------|
| `create_webhook` | Create webhook subscription |
| `list_webhooks` | List active webhooks |
| `delete_webhook` | Delete a webhook |

### Cron
| Tool | Description |
|------|-------------|
| `create_cron_job` | Schedule a recurring task |
| `list_cron_jobs` | List scheduled jobs |
| `delete_cron_job` | Remove a scheduled job |

### Files
| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `write_file` | Write content to file |
| `glob_files` | Find files by glob pattern |
| `search_files` | Search files by name |

### Text Processing
| Tool | Description |
|------|-------------|
| `regex_match` | Regex pattern matching |
| `json_parse` | Parse and format JSON |
| `yaml_parse` | Convert YAML to JSON |
| `diff_text` | Generate unified diff |

### Codec
| Tool | Description |
|------|-------------|
| `base64` | Base64 encode/decode |
| `hex_codec` | Hex encode/decode |
| `jwt_decode` | Decode JWT tokens |

### Network
| Tool | Description |
|------|-------------|
| `http_request` | Make HTTP requests |
| `dns_lookup` | Resolve hostnames |

### Time
| Tool | Description |
|------|-------------|
| `now` | Current date/time |
| `format_datetime` | Format datetime strings |

## Configuration

Configuration is loaded with this priority (highest wins):
1. CLI arguments
2. `HERMES_MCP_*` environment variables
3. `--config` YAML file
4. `config/default.yaml` (built-in)

```yaml
# config/development.yaml
server:
  transport: stdio
  log_level: DEBUG

hermes:
  mode: auto              # auto | sdk | cli

retrieval:
  base_url: http://localhost:8001
```

## Architecture

```
MCP Client (Claude Code, Hermes, etc.)
    ↓ stdio / HTTP-SSE
FastMCP Server (hermes_mcp)
    ↓
Backend Layer
    ├── HermesSDKBackend (import hermes_cli)
    ├── HermesCLIBackend (subprocess hermes.exe)
    └── RetrievalBackend (HTTP → port 8001)
```

## Requirements

- Python >= 3.11
- Hermes Agent v0.18+ (optional, for messaging/cron/webhook tools)
- Three-source retrieval service on port 8001 (optional, for knowledge search)
