# AIBOX SDKs

AIBOX Unified Protocol 1.0 SDKs and machine-readable contract.

```text
sdk/
  python/     aibox-sdk (httpx)
  typescript/ @aibox/sdk (fetch)
  openapi/    aibox.openapi.json
```

- Protocol: [docs/protocol.md](../docs/protocol.md)
- Live manifest: `GET /api/protocol`
- Python: [sdk/python/README.md](python/README.md)
- TypeScript: [sdk/typescript/README.md](typescript/README.md)

## Python

```bash
pip install -e sdk/python
```

## TypeScript

```bash
cd sdk/typescript
pnpm install
pnpm build
```

Both SDKs:

- send `X-AIBox-Protocol: 1.0`, `X-AIBox-Client`, `X-Request-ID`;
- attach `Authorization: Bearer` when configured;
- normalize native `detail` and OpenAI `error` responses;
- wrap job polling and terminal states;
- support chat SSE streaming.

## Contract changes

The server is the source of truth. Add fields/endpoints for 1.x, keep old fields
for at least one minor release, and update `docs/protocol.md` plus
`services/api/aibox_api/protocol.py` together.
