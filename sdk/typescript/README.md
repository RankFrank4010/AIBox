# AIBOX TypeScript SDK

Works in browsers and Node.js 18+.

```ts
import { AIBOXClient } from '@aibox/sdk';

const client = new AIBOXClient({
  baseUrl: 'http://127.0.0.1:8765',
  apiKey: '<AIBOX_TOKEN>',
});

console.log(await client.protocol());

const text = await client.transcribe(await fetch('meeting.wav').then((r) => r.blob()), {
  filename: 'meeting.wav',
  language: 'zh',
});

const translation = await client.translate('Hello', { target: 'zh' });
const ocr = await client.ocr(await fetch('screenshot.png').then((r) => r.blob()), {
  filename: 'screenshot.png',
  language: 'zh',
});

const imageJob = await client.createImage({ prompt: 'A quiet mountain lake' });
const image = await client.waitJob('image', imageJob.id, { timeoutMs: 300_000 });

for await (const chunk of client.chat(
  [{ role: 'user', content: 'Hello' }],
  { stream: true },
)) {
  console.log(chunk);
}
```

Every request sends `X-AIBox-Protocol: 1.0`, `X-AIBox-Client`, and
`X-Request-ID`; `Authorization: Bearer` is added when `apiKey` is set. Errors
become `AIBOXAPIError` with `statusCode`, `code`, `details`, and `requestId`.
