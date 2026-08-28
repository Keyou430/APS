ARG HERMES_BASE_IMAGE=hermes-agent:v2026.7.7.2
FROM ${HERMES_BASE_IMAGE}

COPY --from=platform hermes/MCP /opt/platform-hermes-mcp
COPY hermes-evidence/apply_patch.py /tmp/apply_web_evidence_patch.py
RUN uv pip install --python /opt/hermes/.venv/bin/python3 exa-py /opt/platform-hermes-mcp \
    && npm install -g @larksuite/cli@1.0.90 \
    && lark-cli --version \
    && npm cache clean --force \
    && python /tmp/apply_web_evidence_patch.py \
    && rm /tmp/apply_web_evidence_patch.py
