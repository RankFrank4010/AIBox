import type {
  AppSettings,
  CommunityAdapter,
  CommunityPayload,
  HealthPayload,
  ImageGenerationPayload,
  ImageJob,
  ImageStatus,
  LLMStatus,
  ModelsPayload,
  SeparationJob,
  SeparationStatus,
  SeparationsPayload,
  VideoJob,
  VideosPayload,
  VideoStatus,
  RuntimeStatus,
  SystemInfo,
  TtsStatus,
  TranscriptionRecord,
  TranscriptionsPayload,
  VoiceProfile,
} from './types';

const configuredBase = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '');
export const API_BASE = configuredBase ?? '';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError('无法连接 AIBox 本地服务，请确认后端已启动。', 0);
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === 'string') {
        detail = payload.detail;
      } else if (Array.isArray(payload.detail)) {
        detail = payload.detail
          .map((item) => {
            if (typeof item === 'object' && item && 'msg' in item) {
              return String((item as { msg: unknown }).msg);
            }
            return String(item);
          })
          .join('；');
      }
    } catch {
      // Keep the HTTP fallback message.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthPayload>('/api/health'),
  system: (refresh = false) =>
    request<SystemInfo>(refresh ? '/api/system/refresh' : '/api/system'),
  models: () => request<ModelsPayload>('/api/models'),
  startDownload: (modelId: string) =>
    request('/api/models/downloads', {
      method: 'POST',
      body: JSON.stringify({ model_id: modelId }),
    }),
  cancelDownload: (taskId: string) =>
    request(`/api/models/downloads/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
    }),
  deleteModel: (modelId: string) =>
    request(`/api/models/${encodeURIComponent(modelId)}`, { method: 'DELETE' }),
  settings: () => request<AppSettings>('/api/settings'),
  updateSettings: (patch: Partial<AppSettings>) =>
    request<AppSettings>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  transcriptions: (limit = 40) =>
    request<TranscriptionsPayload>(`/api/transcriptions?limit=${limit}`),
  transcription: (id: string) =>
    request<TranscriptionRecord>(`/api/transcriptions/${encodeURIComponent(id)}`),
  createTranscription: (form: FormData) =>
    request<TranscriptionRecord>('/api/transcriptions', {
      method: 'POST',
      body: form,
    }),
  cancelTranscription: (id: string) =>
    request(`/api/transcriptions/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  deleteTranscription: (id: string) =>
    request(`/api/transcriptions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  ttsStatus: () => request<TtsStatus>('/api/tts/status'),
  ttsVoices: () => request<{ voices: VoiceProfile[] }>('/api/tts/voices'),
  createTtsVoice: (form: FormData) =>
    request<VoiceProfile>('/api/tts/voices', { method: 'POST', body: form }),
  deleteTtsVoice: (id: string) =>
    request(`/api/tts/voices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  ttsSynthesize: (payload: {
    text: string;
    model?: string;
    voice?: string;
    language?: string;
    speed?: number;
    response_format?: string;
  }) =>
    requestAudio('/api/tts/synthesize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  runtime: () => request<RuntimeStatus>('/api/runtime'),
  patchRuntime: (patch: Record<string, unknown>) =>
    request<RuntimeStatus>('/api/runtime', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  unloadRuntime: (kind: 'asr' | 'tts') =>
    request<RuntimeStatus>(`/api/runtime/unload/${kind}`, { method: 'POST' }),
  community: () => request<CommunityPayload>('/api/community'),
  communityTemplate: (id: string) =>
    request<Record<string, unknown>>(
      `/api/community/templates/${encodeURIComponent(id)}`,
    ),
  importCommunityAdapter: (manifest: string | Record<string, unknown>) =>
    request<CommunityAdapter>('/api/community/adapters', {
      method: 'POST',
      body: JSON.stringify({ manifest }),
    }),
  toggleCommunityAdapter: (id: string, enabled: boolean) =>
    request<CommunityAdapter>(
      `/api/community/adapters/${encodeURIComponent(id)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ enabled }),
      },
    ),
  deleteCommunityAdapter: (id: string) =>
    request(`/api/community/adapters/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  reloadCommunity: () =>
    request<CommunityPayload>('/api/community/reload', { method: 'POST' }),
  imageStatus: () => request<ImageStatus>('/api/images/status'),
  images: (limit = 30) =>
    request<ImageGenerationPayload>(`/api/images/generations?limit=${limit}`),
  imageJob: (id: string) =>
    request<ImageJob>(`/api/images/generations/${encodeURIComponent(id)}`),
  generateImage: (payload: {
    prompt: string;
    negative_prompt?: string;
    model?: string | null;
    provider?: string;
    width?: number;
    height?: number;
    steps?: number;
    guidance_scale?: number;
    seed?: number | null;
    batch?: number;
    workflow?: Record<string, unknown> | null;
    checkpoint?: string | null;
  }) =>
    request<ImageJob>('/api/images/generations', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelImage: (id: string) =>
    request<ImageJob>(`/api/images/generations/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    }),
  deleteImage: (id: string) =>
    request(`/api/images/generations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  separationStatus: () => request<SeparationStatus>('/api/separations/status'),
  separations: (limit = 30) =>
    request<SeparationsPayload>(`/api/separations?limit=${limit}`),
  separationJob: (id: string) =>
    request<SeparationJob>(`/api/separations/${encodeURIComponent(id)}`),
  createSeparation: (form: FormData) =>
    request<SeparationJob>('/api/separations', { method: 'POST', body: form }),
  cancelSeparation: (id: string) =>
    request<SeparationJob>(`/api/separations/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    }),
  deleteSeparation: (id: string) =>
    request(`/api/separations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  videoStatus: () => request<VideoStatus>('/api/videos/status'),
  videos: (limit = 20) =>
    request<VideosPayload>(`/api/videos?limit=${limit}`),
  videoJob: (id: string) =>
    request<VideoJob>(`/api/videos/${encodeURIComponent(id)}`),
  createVideo: (payload: {
    prompt: string;
    model?: string | null;
    duration?: number;
    resolution?: string;
    aspect?: string;
    seed?: number | null;
    workflow?: Record<string, unknown> | null;
  }) =>
    request<VideoJob>('/api/videos', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelVideo: (id: string) =>
    request<VideoJob>(`/api/videos/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    }),
  deleteVideo: (id: string) =>
    request(`/api/videos/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  llmStatus: () => request<LLMStatus>('/api/llm/status'),
  llmUnload: () => request('/api/llm/unload', { method: 'POST' }),
  url: (path: string) => `${API_BASE}${path}`,
};

export interface AudioResult {
  blob: Blob;
  warning: string | null;
  model: string | null;
  format: string | null;
}

async function requestAudio(path: string, init?: RequestInit): Promise<AudioResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch {
    throw new ApiError('无法连接 AIBox 本地服务，请确认后端已启动。', 0);
  }
  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: { message?: string } };
      if (typeof payload.detail === 'string') detail = payload.detail;
      else if (payload.error?.message) detail = payload.error.message;
    } catch {
      // Keep fallback.
    }
    throw new ApiError(detail, response.status);
  }
  return {
    blob: await response.blob(),
    warning: response.headers.get('x-aibox-warning'),
    model: response.headers.get('x-aibox-model'),
    format: response.headers.get('x-aibox-format'),
  };
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
