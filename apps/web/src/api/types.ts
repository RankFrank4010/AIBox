export type PlatformId = 'windows' | 'macos' | 'linux' | 'android' | 'ios' | 'unknown';

export interface PlatformInfo {
  id: PlatformId;
  label: string;
  version: string;
  release: string;
  arch: string;
  hostname: string;
  python: string;
  surfaces: {
    webui: boolean;
    desktop: boolean;
    server: boolean;
    android: string;
    ios: string;
  };
  desktop_note: string;
}

export interface CpuInfo {
  name: string;
  vendor: string;
  cores: number;
  physical_cores: number;
  architecture: string;
}

export interface GpuInfo {
  name: string;
  vendor: string;
  vram_gb: number | null;
  vram_used_gb?: number | null;
  driver?: string | null;
  backend: string;
  compute_capability?: string | null;
  metal?: string | null;
}

export interface NpuInfo {
  name: string;
  vendor: string;
  status: string;
  runtime: string;
  path?: string;
}

export interface Accelerator {
  id: string;
  kind: 'cpu' | 'gpu' | 'npu' | string;
  name: string;
  vendor: string;
  memory_gb: number | null;
  backend: string;
  status: 'ready' | 'detected' | 'unavailable' | string;
  for_asr: boolean;
  detail: string;
}

export interface EngineInfo {
  asr: {
    id: string;
    name: string;
    installed: boolean;
    version: string | null;
    runtime: string | null;
    cuda_devices: number;
    cuda_ready?: boolean;
    devices: string[];
    compute_types: string[];
    status: string;
  };
  media: {
    ffmpeg: string | null;
    ffprobe: string | null;
    ready: boolean;
  };
  accelerators: {
    cuda: {
      status: string;
      device_count: number;
      runtime_ready?: boolean;
      note?: string | null;
    };
    metal: { status: string; note: string };
    npu: { status: string; note: string };
  };
}

export interface StorageInfo {
  data_dir: string;
  models_dir: string;
  tts_models_dir?: string;
  image_models_dir?: string;
  llm_models_dir?: string;
  uploads_dir: string;
  models_bytes: number;
  installed_count: number;
  total_bytes: number | null;
  free_bytes: number | null;
  used_bytes: number | null;
}

export interface AppSettings {
  default_model: string | null;
  default_tts_model: string | null;
  tts_default_voice: string;
  default_image_model: string | null;
  image_provider: 'auto' | 'diffusers' | 'comfyui' | 'demo' | string;
  image_steps: number;
  image_guidance: number;
  default_llm_model: string | null;
  llm_provider: 'auto' | 'llama-cpp' | 'openai' | 'demo' | string;
  llm_temperature: number;
  llm_max_tokens: number;
  llm_system_prompt: string;
  parallel_strategy: 'auto' | 'single' | 'data' | 'tensor' | 'pipeline' | 'hybrid' | string;
  parallel_devices: string[];
  parallel_workers: number;
  asr_device: string;
  tts_device: string;
  image_device: string;
  llm_device: string;
  default_training_model: string;
  training_method: 'lora' | 'qlora' | 'full' | string;
  language: string;
  task: 'transcribe' | 'translate';
  device: 'auto' | 'cpu' | 'cuda' | 'npu' | 'metal';
  compute_type: string;
  beam_size: number;
  vad_filter: boolean;
  word_timestamps: boolean;
  theme: 'dark' | 'light' | 'system';
  max_concurrent_jobs: number;
  keep_audio: boolean;
  elastic_mode: string;
  elastic_idle_ttl_seconds: number;
  elastic_switch_interval_seconds: number;
  elastic_max_loaded_models: number;
  elastic_gpu_reserve_gb: number;
  elastic_ram_reserve_gb: number;
  elastic_pinned_kinds: string[];
}

export interface OpenAIServiceInfo {
  status: string;
  base_url: string;
  transcriptions: string;
  models: string;
  auth_required: boolean;
  response_formats: string[];
}

export interface WebSocketServiceInfo {
  status: string;
  url: string;
  path: string;
  auth_required: boolean;
  formats: string[];
  partial_supported: boolean;
}

export interface GrpcServiceInfo {
  status: string;
  enabled: boolean;
  host?: string;
  port: number;
  service?: string;
  tts_service?: string;
  proto?: string;
  tts_proto?: string;
  auth_required?: boolean;
  error?: string;
}

export interface MrcpServiceInfo {
  status: string;
  enabled: boolean;
  host?: string;
  advertise_host?: string;
  port: number;
  control_port?: number;
  rtp_port_range?: [number, number];
  transport?: string;
  codecs?: string[];
  resource?: string;
  auth_required?: boolean;
  error?: string;
  note?: string;
}

export interface TransportServices {
  openai: OpenAIServiceInfo;
  openai_tts?: {
    status: string;
    base_url: string;
    speech: string;
    auth_required: boolean;
    formats: string[];
    engine?: TtsStatus;
  };
  openai_images?: {
    status: string;
    base_url: string;
    generations: string;
    auth_required: boolean;
    sizes: string[];
    engine?: ImageStatus;
  };
  websocket: WebSocketServiceInfo;
  grpc: GrpcServiceInfo;
  mrcp: MrcpServiceInfo;
}

export interface VoiceProfile {
  id: string;
  name: string;
  language: string;
  path: string;
  source: 'builtin' | 'custom' | string;
  created_at?: string | null;
}

export interface TtsStatus {
  status: string;
  engine: string;
  demo: boolean;
  runtime_ready: boolean;
  runtime_home: string | null;
  runtime_python: string;
  loaded_model: string | null;
  busy: boolean;
  installed_models: string[];
  formats: string[];
  voice_count: number;
}

export interface LoadedRuntimeModel {
  kind: 'asr' | 'tts' | string;
  model_id: string;
  estimated_gb: number;
  loaded_at: number;
  last_used: number;
  uses: number;
  busy: boolean;
  pinned: boolean;
}

export interface RuntimeStatus {  mode: string;
  modes: string[];
  focus: string;
  loaded: LoadedRuntimeModel[];
  pending: Array<Record<string, unknown>>;
  budget: {
    kind: 'vram' | 'ram' | string;
    total_gb: number;
    reserve_gb: number;
    vram_gb: number;
    ram_gb: number;
    used_gb: number;
    available_gb: number;
  };
  demand: {
    asr: number;
    tts: number;
    llm: number;
    window_seconds: number;
  };
  max_loaded_models: number;
  idle_ttl_seconds: number;
  switch_interval_seconds: number;
  pinned_kinds: string[];
  last_rebalance: number;
  evictions: Array<{ kind: string; model_id: string; at: number }>;
}

export interface SystemInfo {
  platform: PlatformInfo;
  cpu: CpuInfo;
  memory_gb: number | null;
  gpus: GpuInfo[];
  npus: NpuInfo[];
  accelerators: Accelerator[];
  engines: EngineInfo;
  recommendation: { model_id: string; reason: string };
  gpu_memory_gb: number | null;
  has_cuda: boolean;
  storage: StorageInfo;
  models: {
    installed_count: number;
    installed_ids: string[];
    asr_installed_count: number;
    asr_installed_ids: string[];
    tts_installed_count: number;
    tts_installed_ids: string[];
    image_installed_count: number;
    image_installed_ids: string[];
    recommended_id: string;
    recommended_installed_id: string | null;
    tts_recommended_id: string;
    tts_recommended_installed_id: string | null;
    image_recommended_id: string;
    image_recommended_installed_id: string | null;
  };
  server: {
    host: string;
    port: number;
    data_dir: string;
    hf_endpoint: string;
    demo: boolean;
    demo_tts?: boolean;
  };
  services: TransportServices;
  tts: TtsStatus;
  image: ImageStatus;
  separation: SeparationStatus;
  video: VideoStatus;
  llm: LLMStatus;
  devices: DeviceStatus;
  training: TrainingStatus;
  runtime: RuntimeStatus;
  community: CommunityPayload;
  settings: AppSettings;
}

export type DownloadStatus =
  | 'queued'
  | 'downloading'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface DownloadTask {
  id: string;
  model_id: string;
  model_name: string;
  status: DownloadStatus;
  bytes_downloaded: number;
  total_bytes: number;
  progress: number;
  files_done: number;
  files_total: number;
  current_file: string | null;
  speed_bps: number;
  eta_seconds: number | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ModelInfo {
  id: string;
  name: string;
  family: string;
  kind: 'asr' | 'tts' | 'image' | 'llm';
  engine: string;
  format: string;
  repo: string;
  parameters: string;
  size_bytes: number;
  size_label: string;
  speed: number;
  accuracy: number;
  languages: string;
  memory_gb: number;
  description: string;
  best_for: string;
  tags: string[];
  english_only: boolean;
  license: string;
  source: string;
  download_url: string | null;
  recursive_download?: boolean;
  required_files?: string[];
  download_files?: string[];
  quantization?: string;
  context_length?: number;
  installed: boolean;
  installed_at: string | null;
  installed_bytes: number;
  path: string | null;
  download: DownloadTask | null;
  external?: boolean;
  community?: boolean;
  adapter_id?: string;
  aliases?: string[];
  homepage?: string;
  install_docs?: string;
  pipeline?: string;
  comfyui_checkpoint?: string;
  default_width?: number;
  default_height?: number;
}

export interface ModelsPayload {
  catalog: ModelInfo[];
  installed: ModelInfo[];
  downloads: DownloadTask[];
  storage: StorageInfo;
  recommendation: {
    model_id: string;
    installed_id: string | null;
    reason: string;
  };
  tts_recommendation: {
    model_id: string;
    installed_id: string | null;
    reason: string;
  };
  image_recommendation: {
    model_id: string;
    installed_id: string | null;
    reason: string;
  };
  llm_recommendation: {
    model_id: string;
    installed_id: string | null;
    reason: string;
  };
}

export interface HealthPayload {
  status: string;
  app: string;
  version: string;
  engine: {
    id: string;
    installed: boolean;
    demo: boolean;
    ready: boolean;
  };
  platform: PlatformId;
  transports?: TransportServices;
  settings: AppSettings;
}

export type TranscriptionStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface SegmentWord {
  word: string;
  start: number;
  end: number;
  probability: number | null;
}

export interface TranscriptSegment {
  id: number;
  start: number;
  end: number;
  text: string;
  words?: SegmentWord[];
}

export interface TranscriptionRecord {
  id: string;
  created_at: string;
  updated_at: string;
  status: TranscriptionStatus;
  stage: string;
  progress: number;
  filename: string;
  audio_size: number;
  duration: number | null;
  model_id: string;
  task: 'transcribe' | 'translate';
  language: string;
  detected_language: string | null;
  language_probability: number | null;
  text: string;
  segments: TranscriptSegment[];
  options: Record<string, unknown>;
  engine: string | null;
  device: string | null;
  compute_type: string | null;
  warning: string | null;
  error: string | null;
  audio_url: string;
  export_urls: Record<string, string>;
  has_audio: boolean;
}

export interface TranscriptionsPayload {
  items: TranscriptionRecord[];
}

export interface CommunityTemplate {
  id: string;
  name: string;
  kind: 'asr' | 'tts';
  description: string;
  languages: string;
  parameters: string;
  memory_gb: number;
  license: string;
  source: string;
  homepage: string;
  tags: string[];
  install: string;
  docs: string;
  adapter_example: Record<string, unknown>;
  template: true;
}

export interface CommunityAdapter {
  id: string;
  name: string;
  kind: 'asr' | 'tts';
  adapter_type: 'openai-http' | 'command' | string;
  adapter: Record<string, unknown>;
  description: string;
  homepage: string;
  docs: string;
  install: string;
  builtin: boolean;
  enabled: boolean;
  template: boolean;
  status: string;
  error: string | null;
  source_path: string | null;
  model: ModelInfo;
}

export interface CommunityPayload {
  templates: CommunityTemplate[];
  adapters: CommunityAdapter[];
  summary: {
    templates: number;
    adapters: number;
    enabled: number;
    ready: number;
  };
  security: {
    allow_commands: boolean;
    allow_remote: boolean;
    adapters_dir: string;
  };
  errors: Array<{ file: string; error: string }>;
}

export interface ImageStatus {
  demo: boolean;
  provider_setting: string;
  comfyui: {
    available: boolean;
    url?: string;
    error?: string;
    stats?: Record<string, unknown>;
  };
  comfyui_url: string;
  diffusers: {
    runtime_ready: boolean;
    python: string;
    loaded_model: string | null;
  };
  installed_models: string[];
  recommended_model: string;
}

export interface ImageJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: string;
  stage: string;
  progress: number;
  prompt: string;
  negative_prompt: string;
  model_id: string;
  provider: string;
  width: number;
  height: number;
  steps: number;
  guidance: number;
  seed: number | null;
  batch: number;
  image_paths?: string[];
  image_urls: string[];
  image_absolute_urls: string[];
  preview_url: string | null;
  warning: string | null;
  error: string | null;
  options?: Record<string, unknown>;
  engine?: ImageStatus;
}

export interface ImageGenerationPayload {
  items: ImageJob[];
}

export interface SeparationModel {
  id: string;
  name: string;
  engine: 'demucs' | 'audio-separator' | string;
  model_arg: string;
  filename: string;
  stems: string[];
  size_label: string;
  description: string;
  best_for: string;
  quality: number;
  speed: number;
  license: string;
  two_stem: boolean;
  available: boolean;
}

export interface SeparationStatus {
  demo: boolean;
  python: string;
  device: string;
  demucs_ready: boolean;
  audio_separator_ready: boolean;
  models: SeparationModel[];
  modes: Array<{ id: string; label: string }>;
}

export interface SeparationOutput {
  role: string;
  label: string;
  filename: string;
  url: string;
}

export interface SeparationJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: string;
  stage: string;
  progress: number;
  filename: string;
  audio_size: number;
  model_id: string;
  mode: string;
  duration: number | null;
  outputs: SeparationOutput[];
  preview_url: string | null;
  error: string | null;
}

export interface SeparationsPayload {
  items: SeparationJob[];
}

export interface VideoModel {
  id: string;
  name: string;
  provider: 'minimax' | 'comfyui' | string;
  model_arg: string;
  durations: number[];
  resolutions: string[];
  description: string;
  best_for: string;
  max_duration: number;
  audio: boolean;
  requires_workflow: boolean;
  license: string;
  homepage: string;
  available: boolean;
}

export interface VideoStatus {
  demo: boolean;
  minimax: {
    configured: boolean;
    base_url: string;
    default_model: string;
  };
  comfyui: {
    available: boolean;
    url?: string;
    error?: string;
  };
  comfyui_url: string;
  models: VideoModel[];
}

export interface VideoJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: string;
  stage: string;
  progress: number;
  prompt: string;
  model_id: string;
  provider: string;
  duration: number;
  resolution: string;
  aspect: string;
  width: number;
  height: number;
  seed: number | null;
  video_url: string | null;
  poster_url: string | null;
  warning: string | null;
  error: string | null;
}

export interface VideosPayload {
  items: VideoJob[];
}

export interface LLMModelInfo {
  id: string;
  name: string;
  kind: string;
  parameters: string;
  size_label: string;
  description: string;
  best_for: string;
  quantization: string;
  context_length: number;
  memory_gb: number;
  speed: number;
  accuracy: number;
  languages: string;
  installed: boolean;
  recommended?: boolean;
  path?: string | null;
  download?: DownloadTask | null;
}

export interface LLMStatus {
  demo: boolean;
  provider_setting: string;
  llama_server: string | null;
  external: {
    configured: boolean;
    base_url: string;
    models: string[];
  };
  installed_models: string[];
  models: LLMModelInfo[];
  recommended_model: string;
  loaded_model: string | null;
  server_port: number | null;
  context: number;
  parallel?: {
    strategy: string;
    cuda_indices: number[];
    split_mode: string;
    tensor_split: number[];
    parallel: number;
  } | null;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ChatCompletionChoice {
  index: number;
  message?: { role: string; content: string };
  delta?: { role?: string; content?: string };
  finish_reason?: string | null;
}

export interface ChatCompletion {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: ChatCompletionChoice[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ComputeDevice {
  id: string;
  name: string;
  kind: string;
  backend: string;
  memory_gb: number | null;
  index: number | null;
  available: boolean;
}

export interface DeviceStatus {
  strategy: string;
  strategies: string[];
  devices: ComputeDevice[];
  selected: string[];
  assignments: Record<string, string[]>;
  preferred: Record<string, string>;
  active: Record<string, number>;
  workers: number;
}

export interface TrainingModelPreset {
  id: string;
  name: string;
  hf_id: string;
  parameters: string;
  license: string;
  qlora_gb: number;
  full_gb: number;
}

export interface TrainingMethod {
  id: string;
  label: string;
  note: string;
}

export interface TrainingDataset {
  id: string;
  name: string;
  format: string;
  size_bytes: number;
  rows: number;
  preview: Array<Record<string, unknown>>;
  created_at: string;
}

export interface TrainingArtifact {
  name: string;
  path: string;
  bytes: number;
  url: string;
}

export interface TrainingJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: string;
  stage: string;
  progress: number;
  name: string;
  base_model: string;
  method: string;
  dataset_id: string;
  device: string;
  parallel_strategy: string;
  config: Record<string, unknown>;
  metrics: Record<string, unknown>;
  error: string | null;
  artifacts: TrainingArtifact[];
  log_url: string;
}

export interface TrainingStatus {
  demo: boolean;
  command: boolean;
  models: TrainingModelPreset[];
  methods: TrainingMethod[];
  parallelism: TrainingMethod[];
  datasets: TrainingDataset[];
  jobs: TrainingJob[];
}

export interface TrainingLogs {
  lines: string[];
  text: string;
}
