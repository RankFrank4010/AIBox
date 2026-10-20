# AIBOX Python SDK

```bash
pip install -e sdk/python
```

```python
from aibox_sdk import AIBOXClient

with AIBOXClient("http://127.0.0.1:8765", api_key="...") as client:
    print(client.protocol())
    print(client.models())

    # OpenAI-compatible ASR
    text = client.transcribe("meeting.wav", language="zh")
    print(text)

    # Translation / OCR
    print(client.translate("Hello", target="zh"))
    print(client.ocr("screenshot.png"))

    # Async job + polling
    job = client.create_image(prompt="A quiet mountain lake")
    done = client.wait_job("image", job["id"], timeout=300)
    print(done)
```

The client sends `X-AIBox-Protocol: 1.0`, `X-AIBox-Client`, `X-Request-ID`,
and `Authorization: Bearer` when an API key is configured. Errors are normalized
to `AIBOXAPIError` with `status_code`, `code`, `details`, and `request_id`.

`chat(..., stream=True)` returns an iterator over OpenAI-compatible SSE JSON
chunks and raises `AIBOXAPIError` on an error chunk.
