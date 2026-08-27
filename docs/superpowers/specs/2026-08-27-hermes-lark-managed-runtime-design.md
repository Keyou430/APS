# Hermes-lark Managed Runtime Design

Date: 2026-08-27 (Asia/Shanghai)

## Goal

Create a shareable Windows runtime bundle at `D:\Hermes-lark` that contains
the platform-downstream integration chain: Hermes Agent, Hermes Web search,
the controlled `hermes-lark-cli` MCP adapter, and lark-cli connectivity to
Feishu. The consuming platform connects to Hermes through its HTTP interface;
Replica's backend and frontend are not included.

## External Interface

Users interact with only one editable configuration file and one command
entry point:

```text
hermes-lark.yaml
hermes-lark.cmd setup
hermes-lark.cmd feishu-login
hermes-lark.cmd start
hermes-lark.cmd status
hermes-lark.cmd stop
hermes-lark.cmd doctor
```

`hermes-lark.yaml` is the only human-edited configuration source. Generated
Hermes profiles, MCP paths, SOUL instructions, logs, PID files, and installed
dependencies live under `.runtime` and must not be edited by users.

## Distribution Model

Use a managed runtime package. The bundle contains the launcher, MCP source,
templates, version manifest, and documentation. `setup` installs the pinned
Hermes and Python dependencies into package-local runtime directories instead
of depending on the source machine's absolute paths.

The initial supported environment is Windows. The pinned baseline is:

- Hermes Agent 0.18.0;
- lark-cli 1.0.90;
- Python 3.11 or 3.12 for the MCP adapter;
- a compatible Node.js runtime for lark-cli.

Hermes is included logically as a managed dependency, not by copying the
current `hermes.exe` trampoline. That executable embeds the source machine's
Python path and is not portable. The bundle may use an already compatible
system installation only when `doctor` verifies its version; otherwise
`setup` installs the pinned package-local runtime.

## Directory Layout

```text
D:\Hermes-lark\
  hermes-lark.yaml
  hermes-lark.cmd
  README.md
  src\
    hermes_lark\
  templates\
    agent-config.yaml
    knowledge-config.yaml
    SOUL.md
    knowledge-SOUL.md
  mcp\
    pyproject.toml
    src\hermes_mcp\
  vendor\
    versions.json
  tests\
  .runtime\
    generated\
    hermes-home\
    knowledge-home\
    python\
    logs\
    pids\
```

Only the files outside `.runtime` are distributable source artifacts.
`.runtime` is created locally and excluded from sharing.

## Configuration Model

The default `hermes-lark.yaml` contains:

```yaml
version: 1

model:
  provider: deepseek
  name: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY
  base_url: https://api.deepseek.com/v1

server:
  host: 127.0.0.1
  agent_port: 8642
  knowledge_port: 8643
  api_key_env: HERMES_API_SERVER_KEY

web:
  provider: ddgs

feishu:
  enabled: true
  identity: user

security:
  browser: false
  terminal: false
  file: false
  code_execution: false
```

Secrets are referenced through environment-variable names. `setup`, `start`,
and `doctor` must never copy secret values into generated YAML, logs, process
status output, or documentation. The launcher may optionally read a local,
ignored `.env` file in a later version, but that is outside this first package.

## Generated Hermes Profiles

The launcher generates two isolated Hermes homes:

- Agent Hermes enables exactly `web` and `hermes-lark-cli` for the API server.
- Knowledge Hermes uses `no_mcp` and cannot access Web or Feishu tools.

The Agent profile registers the MCP through package-relative resolved paths.
It does not contain `D:\Replica1.0`, `D:\TASK\hermes`, user profile paths, or
source-machine credentials. Browser, terminal, file, and code execution remain
disabled.

The generated Agent SOUL defines:

- `web_search` for current public information;
- optional `web_extract` only when an extraction provider is configured;
- normal document prose with titles, paragraphs, and lists;
- actual retrieved URLs in a final `参考来源` section;
- `docs +create` or `docs +update` only after explicit write intent;
- no Feishu mutation for search-only or draft-only requests.

## MCP and Feishu Boundary

The package includes the controlled `hermes-lark-cli` adapter with three MCP
tools:

- `lark_cli_help`;
- `lark_cli_schema`;
- `lark_cli_execute`.

These are generic control tools over the approved lark-cli business domains,
not a three-feature limit. They retain argv validation, no-shell execution,
bounded output, path restrictions, credential redaction, and lark-cli's
high-risk confirmation protocol.

The adapter always performs business operations as the locally authorized
Feishu user. It does not copy, export, or share OAuth credentials. Each user
runs `hermes-lark.cmd feishu-login` on their own machine. User-visible Feishu
resources remain limited by application scopes, user consent, tenant policy,
and resource permissions.

## Command Behavior

### setup

Validate the host, install or verify pinned managed dependencies, install the
MCP adapter, install the `ddgs` Web dependency, generate both Hermes profiles,
and run static configuration checks. It must be idempotent.

### feishu-login

Launch lark-cli's user authorization flow for the approved business domains,
without exposing tokens. A separate `doctor` check confirms `identity=user`,
`verified=true`, and a valid user token.

### start

Validate configuration and required secret environment variables, reject busy
ports, start Agent Hermes and Knowledge Hermes, wait for health endpoints, and
write only package-owned PID and log files. If either process fails, stop only
the processes created by that invocation.

### status

Report PID ownership and health for both gateways without displaying process
environment variables or secrets.

### stop

Stop only processes whose recorded PID and command line match the package's
expected Hermes gateway command. Stale PID files are removed without killing
unrelated processes.

### doctor

Check configuration schema, dependency versions, secret presence without
printing values, port availability or managed-process ownership, generated
profiles, MCP discovery, Web provider availability, and Feishu authorization.
It returns a nonzero exit code when a required check fails.

## Source Collection and Privacy

Packaging uses an explicit allowlist. It may copy MCP source, selected tests,
SOUL/config templates, and version metadata. It must never copy:

- `auth.json`, `.env`, access tokens, refresh tokens, or device codes;
- Hermes state, response, kanban, or session databases;
- logs, PID/lock files, pairing data, memories, caches, uploads, or chat history;
- Replica backend databases, user uploads, frontend build dependencies, or the
  Replica backend/frontend source trees;
- source-machine absolute paths.

## Error Handling

- Missing secret environment variable: fail before creating processes.
- Unsupported configuration version or unknown key: fail with a field-level
  message.
- Missing or incompatible dependency: `doctor` reports the expected and found
  versions; `setup` attempts the managed installation.
- Busy port: report the port and owning PID; do not terminate it.
- Partial startup: roll back only processes created by the current invocation.
- Missing Feishu authorization or scope: return the normalized lark-cli error;
  never fall back to bot identity.
- `ddgs` extraction request: report that it is search-only; do not claim page
  text was extracted.

## Verification

Automated tests cover:

- parsing and validation of the single configuration file;
- rejection of unknown keys and missing environment variables;
- generation of portable Agent and Knowledge profiles;
- exact Agent and Knowledge tool boundaries;
- setup idempotency and pinned version checks;
- start rollback, PID ownership, busy ports, status, and stop behavior;
- absence of source-machine paths and private-runtime filenames in the bundle;
- MCP command allowlist, confirmation protocol, path constraints, bounded
  output, and credential redaction.

Live acceptance on this machine requires:

1. `setup` completes from `D:\Hermes-lark`;
2. `doctor` discovers exactly three MCP control tools;
3. both Hermes health endpoints are healthy;
4. Agent `/v1/toolsets` enables Web and disables browser, terminal, file, and
   code execution;
5. a harmless `web_search` emits tool events and a public URL;
6. lark-cli authorization verifies as a user;
7. a Feishu document create dry-run contains title, prose, list, and
   `参考来源`, without creating a real document;
8. a scan of the output package finds no copied personal authorization,
   runtime database, log, PID, lock, or source-machine absolute path.

## Non-Goals

- Replica backend or frontend packaging;
- LAN or Internet exposure of Hermes gateways;
- sharing one user's Feishu authorization with other users;
- bypassing lark-cli confirmation or Feishu permission controls;
- offline bundling of every Python and Node runtime in the first version;
- automatic real Feishu writes during acceptance.

## Completion Criteria

The package is complete when a user can configure `hermes-lark.yaml`, provide
the referenced secret environment variables, run setup and their own Feishu
login, start both gateways, and connect an external platform to Agent Hermes at
the configured local HTTP endpoint. No other hand-edited configuration file or
copied personal state is required.
