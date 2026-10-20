/**
 * TypeScript SDK for the AIBOX Unified Protocol 1.0.
 *
 * Works in browsers and Node.js 18+ (global fetch, FormData, Blob).
 */

export const PROTOCOL_VERSION = '1.0';

export interface AIBOXConfig {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | Array<Record<string, unknown>>;
}

export interface AIBOXJob {
  id: string;
  status: string;
  stage?: string;
  progress?: number;
  error?: string | null;
  [key: string]: unknown;
}

export interface TranslationRecord {
  id: string;
  text: string;
  translated: string;
  source: string;
  target: string;
  provider: string;
  model: string;
  latency_ms: number;
  [key: string]: unknown;
}

export interface OcrRecord {
  id: string;
  text: string;
  image_url: string;
  filename: string;
  provider: string;
  model: string;
  language: string;
  [key: string]: unknown;
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
const JOB_PATHS: Record<string, string> = {
  transcription: '/api/transcriptions/{id}',
  image: '/api/images/generations/{id}',
  video: '/api/videos/{id}',
  separation: '/api/separations/{id}',
  training: '/api/training/jobs/{id}',
};
const CANCEL_PATHS: Record<string, string> = {
  transcription: '/api/transcriptions/{id}/cancel',
  image: '/api/images/generations/{id}/cancel',
  video: '/api/videos/{id}/cancel',
  separation: '/api/separations/{id}/cancel',
  training: '/api/training/jobs/{id}/cancel',
};

export class AIBOXError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AIBOXError';
  }
}

export class AIBOXAPIError extends AIBOXError {
  statusCode: number;
  code?: string;
  details?: unknown;
  requestId?: string;

  constructor(
    message: string,
    options: {
      statusCode: number;
      code?: string;
      details?: unknown;
      requestId?: string;
    },
  ) {
    super(message);
    this.name = 'AIBOXAPIError';
    this.statusCode = options.statusCode;
    this.code = options.code;
    this.details = options.details;
    this.requestId = options.requestId;
  }
}

export class AIBOXTimeout extends AIBOXError {
  constructor(message: string) {
    super(message);
    this.name = 'AIBOXTimeout';
  }
}

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID().replaceAll('-', '');
  }
  return Math.random().toString(16).slice(2) + Date.now().toString(16);
}

function mimeOf(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.png')) return 'image/png';
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
  if (lower.endsWith('.webp')) return 'image/webp';
  if (lower.endsWith('.mp3')) return 'audio/mpeg';
  if (lower.endsWith('.wav')) return 'audio/wav';
  if (lower.endsWith('.m4a')) return 'audio/mp4';
  if (lower.endsWith('.flac')) return 'audio/flac';
  return 'application/octet-stream';
}

export class AIBOXClient {
  readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(config: AIBOXConfig = {}) {
    this.baseUrl = (config.baseUrl ?? 'http://127.0.0.1:8765').replace(/\/$/, '');
    this.apiKey = config.apiKey;
    this.timeoutMs = config.timeoutMs ?? 60_000;
    this.fetchImpl = config.fetchImpl ?? fetch;
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const headers: Record<string, string> = {
      'X-AIBox-Protocol': PROTOCOL_VERSION,
      'X-AIBox-Client': 'aibox-typescript/1.0',
      'X-Request-ID': randomId(),
      ...extra,
    };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;
    return headers;
  }

  private async parseError(response: Response): Promise<AIBOXAPIError> {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => '');
    }
    const record = (body ?? {}) as Record<string, unknown>;
    const error = record.error as Record<string, unknown> | undefined;
    const detail = record.detail;
    const message =
      (typeof error?.message === 'string' && error.message) ||
      (typeof detail === 'string' && detail) ||
      (Array.isArray(detail) && JSON.stringify(detail)) ||
      response.statusText;
    return new AIBOXAPIError(message, {
      statusCode: response.status,
      code: typeof error?.code === 'string' ? error.code : undefined,
      details: body,
      requestId: response.headers.get('X-Request-ID') ?? undefined,
    });
  }

  async request<T = unknown>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers: this.headers(
          (init.headers as Record<string, string> | undefined) ?? {},
        ),
        signal: controller.signal,
      });
      if (!response.ok) throw await this.parseError(response);
      if (response.status === 204) return undefined as T;
      const text = await response.text();
      return (text ? JSON.parse(text) : undefined) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  async protocol(): Promise<Record<string, unknown>> {
    return this.request('/api/protocol');
  }

  async health(): Promise<Record<string, unknown>> {
    return this.request('/api/health');
  }

  async models(): Promise<Array<Record<string, unknown>>> {
    const payload = await this.request<{ data?: Array<Record<string, unknown>> }>(
      '/v1/models',
    );
    return payload.data ?? [];
  }

  chat(
    messages: ChatMessage[],
    options: {
      model?: string;
      stream?: false;
      temperature?: number;
      maxTokens?: number;
    },
  ): Promise<Record<string, unknown>>;
  chat(
    messages: ChatMessage[],
    options: {
      model?: string;
      stream: true;
      temperature?: number;
      maxTokens?: number;
    },
  ): AsyncGenerator<Record<string, unknown>>;
  chat(
    messages: ChatMessage[],
    options: {
      model?: string;
      stream?: boolean;
      temperature?: number;
      maxTokens?: number;
    } = {},
  ): Promise<Record<string, unknown>> | AsyncGenerator<Record<string, unknown>> {
    const payload: Record<string, unknown> = {
      messages,
      stream: Boolean(options.stream),
    };
    if (options.model) payload.model = options.model;
    if (options.temperature !== undefined) payload.temperature = options.temperature;
    if (options.maxTokens !== undefined) payload.max_tokens = options.maxTokens;
    if (!options.stream) {
      return this.request('/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    }
    return this.streamChat(payload);
  }

  private async *streamChat(
    payload: Record<string, unknown>,
  ): AsyncGenerator<Record<string, unknown>> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: this.headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw await this.parseError(response);
    if (!response.body) throw new AIBOXError('stream response has no body');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index = buffer.indexOf('\n\n');
        while (index >= 0) {
          const event = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          for (const line of event.split('\n')) {
            if (!line.startsWith('data:')) continue;
            const data = line.slice(5).trim();
            if (!data || data === '[DONE]') continue;
            try {
              const chunk = JSON.parse(data) as Record<string, unknown>;
              if (chunk.error) {
                throw new AIBOXAPIError('stream error', {
                  statusCode: response.status,
                  details: chunk,
                });
              }
              yield chunk;
            } catch (error) {
              if (error instanceof AIBOXAPIError) throw error;
            }
          }
          index = buffer.indexOf('\n\n');
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  async transcribe(
    audio: Blob,
    options: {
      filename?: string;
      model?: string;
      language?: string;
      prompt?: string;
      responseFormat?: string;
    } = {},
  ): Promise<Record<string, unknown>> {
    const filename = options.filename ?? 'audio.wav';
    const form = new FormData();
    form.append('file', audio, filename);
    form.append('model', options.model ?? 'whisper-1');
    form.append('response_format', options.responseFormat ?? 'json');
    if (options.language) form.append('language', options.language);
    if (options.prompt) form.append('prompt', options.prompt);
    return this.request('/v1/audio/transcriptions', {
      method: 'POST',
      body: form,
    });
  }

  async speech(
    text: string,
    options: {
      voice?: string;
      model?: string;
      responseFormat?: string;
    } = {},
  ): Promise<Uint8Array> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/v1/audio/speech`, {
        method: 'POST',
        headers: this.headers({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          input: text,
          voice: options.voice ?? 'default',
          model: options.model ?? 'tts-1',
          response_format: options.responseFormat ?? 'wav',
        }),
        signal: controller.signal,
      });
      if (!response.ok) throw await this.parseError(response);
      return new Uint8Array(await response.arrayBuffer());
    } finally {
      clearTimeout(timer);
    }
  }

  async translate(
    text: string,
    options: {
      source?: string;
      target?: string;
      provider?: string;
      model?: string;
    } = {},
  ): Promise<TranslationRecord> {
    const payload: Record<string, unknown> = {
      text,
      source: options.source ?? 'auto',
      target: options.target ?? 'zh',
      provider: options.provider ?? 'auto',
    };
    if (options.model) payload.model = options.model;
    const response = await this.request<{ translation: TranslationRecord }>(
      '/api/translations',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    );
    return response.translation;
  }

  async ocr(
    image: Blob,
    options: {
      filename?: string;
      provider?: string;
      model?: string;
      language?: string;
    } = {},
  ): Promise<OcrRecord> {
    const form = new FormData();
    form.append('file', image, options.filename ?? 'image.png');
    form.append('provider', options.provider ?? 'auto');
    form.append('language', options.language ?? 'auto');
    if (options.model) form.append('model', options.model);
    const response = await this.request<{ record: OcrRecord }>('/api/ocr', {
      method: 'POST',
      body: form,
    });
    return response.record;
  }

  async createImage(
    payload: Record<string, unknown>,
  ): Promise<AIBOXJob> {
    return this.request('/api/images/generations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async createVideo(payload: Record<string, unknown>): Promise<AIBOXJob> {
    return this.request('/api/videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async createSeparation(
    audio: Blob,
    options: { filename?: string; mode?: string; model?: string } = {},
  ): Promise<AIBOXJob> {
    const form = new FormData();
    form.append('file', audio, options.filename ?? 'audio.wav');
    form.append('mode', options.mode ?? 'instrumental');
    if (options.model) form.append('model', options.model);
    return this.request('/api/separations', { method: 'POST', body: form });
  }

  async createTraining(payload: Record<string, unknown>): Promise<AIBOXJob> {
    return this.request('/api/training/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }

  async job(kind: string, id: string): Promise<AIBOXJob> {
    const template = JOB_PATHS[kind];
    if (!template) throw new AIBOXError(`unknown job kind: ${kind}`);
    return this.request(template.replace('{id}', encodeURIComponent(id)));
  }

  async cancelJob(kind: string, id: string): Promise<AIBOXJob> {
    const template = CANCEL_PATHS[kind];
    if (!template) throw new AIBOXError(`unknown job kind: ${kind}`);
    return this.request(template.replace('{id}', encodeURIComponent(id)), {
      method: 'POST',
    });
  }

  async waitJob(
    kind: string,
    id: string,
    options: { timeoutMs?: number; intervalMs?: number } = {},
  ): Promise<AIBOXJob> {
    const deadline = Date.now() + (options.timeoutMs ?? 600_000);
    const interval = options.intervalMs ?? 1_000;
    for (;;) {
      const job = await this.job(kind, id);
      if (TERMINAL.has(String(job.status))) return job;
      if (Date.now() >= deadline) {
        throw new AIBOXTimeout(`${kind} job ${id} did not finish in time`);
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }
}

export { mimeOf };
