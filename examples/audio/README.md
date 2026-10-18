# Sample audio

Generated with Windows SAPI for local testing. They contain no personal data.

| File | Language | Duration |
| --- | --- | --- |
| `english-test.wav` | English | ~9 s |
| `chinese-test.wav` | Chinese | ~9 s |

Use them from the Transcribe page, or run the Playwright flow test:

```powershell
pnpm --filter @aibox/web check:flow
```

The test expects the API at `http://127.0.0.1:8765`, at least one installed model, and Microsoft Edge.
