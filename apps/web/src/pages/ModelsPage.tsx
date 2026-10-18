import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Input,
  ProgressBar,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowRightRegular,
  ArrowSyncRegular,
  CheckmarkRegular,
  DeleteRegular,
  DismissRegular,
  FolderOpenRegular,
  PeopleCommunityRegular,
  SearchRegular,
  StarFilled,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { MetricBar } from '../components/MetricBar';
import { EmptyState } from '../components/EmptyState';
import { HardwareIcon } from '../components/HardwareIcon';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { ModelInfo } from '../api/types';
import { formatBytes, formatEta } from '../utils/format';
import { downloadLabel } from '../utils/status';

type ModelKind = 'asr' | 'tts' | 'image' | 'llm';
type ModelFilter = 'all' | 'installed' | 'light' | 'english' | 'multilingual' | 'community';

const ASR_FILTERS: Array<{ id: ModelFilter; label: string }> = [
  { id: 'all', label: '全部模型' },
  { id: 'installed', label: '已安装' },
  { id: 'light', label: '轻量 · < 500 MB' },
  { id: 'english', label: '英文专用' },
  { id: 'community', label: '社区模型' },
];

const TTS_FILTERS: Array<{ id: ModelFilter; label: string }> = [
  { id: 'all', label: '全部模型' },
  { id: 'installed', label: '已安装' },
  { id: 'multilingual', label: '多语言' },
  { id: 'community', label: '社区模型' },
];

const IMAGE_FILTERS: Array<{ id: ModelFilter; label: string }> = [
  { id: 'all', label: '全部模型' },
  { id: 'installed', label: '已安装' },
  { id: 'light', label: '轻量 · < 10 GB' },
];

const LLM_FILTERS: Array<{ id: ModelFilter; label: string }> = [
  { id: 'all', label: '全部模型' },
  { id: 'installed', label: '已安装' },
  { id: 'light', label: '轻量 · < 5 GB' },
  { id: 'multilingual', label: '中文 / 多语言' },
];

export function ModelsPage() {
  const {
    models,
    settings,
    loading,
    refreshModels,
    refreshSystem,
    updateSettings,
    notify,
  } = useAppData();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [kind, setKind] = useState<ModelKind>(() => {
    const requested = searchParams.get('kind');
    return requested === 'tts' || requested === 'image' || requested === 'llm'
      ? requested
      : 'asr';
  });
  const [filter, setFilter] = useState<ModelFilter>('all');
  const [search, setSearch] = useState('');
  const [busyModel, setBusyModel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ModelInfo | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const seenCompleted = useRef<Set<string>>(new Set());
  const seenFailed = useRef<Set<string>>(new Set());
  const baselineReady = useRef(false);

  const catalog = models?.catalog ?? [];
  const kindCatalog = useMemo(
    () => catalog.filter((model) => model.kind === kind),
    [catalog, kind],
  );
  const kindInstalled = useMemo(
    () => (models?.installed ?? []).filter((model) => model.kind === kind),
    [models, kind],
  );
  const recommendedId =
    kind === 'asr'
      ? models?.recommendation.model_id
      : kind === 'tts'
        ? models?.tts_recommendation.model_id
        : kind === 'image'
          ? models?.image_recommendation.model_id
          : models?.llm_recommendation.model_id;
  const filters =
    kind === 'asr'
      ? ASR_FILTERS
      : kind === 'tts'
        ? TTS_FILTERS
        : kind === 'image'
          ? IMAGE_FILTERS
          : LLM_FILTERS;
  const activeDownloads = useMemo(
    () =>
      (models?.downloads ?? []).filter((task) =>
        ['queued', 'downloading', 'cancelling'].includes(task.status),
      ),
    [models],
  );

  useEffect(() => {
    if (!models) return;
    if (!baselineReady.current) {
      baselineReady.current = true;
      for (const task of models.downloads) {
        if (task.status === 'completed') seenCompleted.current.add(task.id);
        if (task.status === 'failed') seenFailed.current.add(task.id);
      }
      return;
    }
    for (const task of models.downloads) {
      if (task.status === 'completed' && !seenCompleted.current.has(task.id)) {
        seenCompleted.current.add(task.id);
        notify('模型安装完成', `${task.model_name} 现在可以使用了。`);
        void refreshSystem();
      }
      if (task.status === 'failed' && !seenFailed.current.has(task.id)) {
        seenFailed.current.add(task.id);
        notify('模型下载失败', task.error ?? '请检查网络后重试。', 'error');
      }
    }
  }, [models, notify, refreshSystem]);

  const visible = kindCatalog.filter((model) => {
    const matchesSearch =
      !search.trim() ||
      `${model.name} ${model.description} ${model.tags.join(' ')}`
        .toLowerCase()
        .includes(search.trim().toLowerCase());
    if (!matchesSearch) return false;
    if (filter === 'installed') return model.installed;
    if (filter === 'light') {
      if (kind === 'image') return model.size_bytes < 10_000_000_000;
      if (kind === 'llm') return model.size_bytes < 5_000_000_000;
      return model.size_bytes < 500_000_000;
    }
    if (filter === 'english') return model.english_only;
    if (filter === 'multilingual') return model.languages.includes('/');
    if (filter === 'community') return model.external === true;
    return true;
  });

  const changeKind = (next: ModelKind) => {
    setKind(next);
    setFilter('all');
    setSearch('');
  };

  const startDownload = async (model: ModelInfo) => {
    setBusyModel(model.id);
    try {
      await api.startDownload(model.id);
      notify('已加入下载队列', `${model.name} · ${model.size_label}`, 'info');
      await refreshModels();
    } catch (err) {
      notify('无法开始下载', errorMessage(err), 'error');
    } finally {
      setBusyModel(null);
    }
  };

  const cancelDownload = async (taskId: string, modelName: string) => {
    try {
      await api.cancelDownload(taskId);
      notify('正在取消下载', modelName, 'info');
      await refreshModels();
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const setDefaultModel = async (model: ModelInfo) => {
    try {
      await updateSettings(
        model.kind === 'asr'
          ? { default_model: model.id }
          : model.kind === 'image'
            ? { default_image_model: model.id }
            : model.kind === 'llm'
              ? { default_llm_model: model.id }
              : { default_tts_model: model.id },
      );
    } catch (err) {
      notify('设置默认模型失败', errorMessage(err), 'error');
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await api.deleteModel(deleting.id);
      notify('模型已删除', `${deleting.name} 已从本机移除。`, 'success');
      setDeleting(null);
      await Promise.all([refreshModels(), refreshSystem()]);
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="page models-page">
      <PageHeader
        eyebrow="MODEL LIBRARY"
        title="模型库"
        description="管理 Whisper 语音识别与 IndexTTS 语音合成模型。模型保存在本机，可随时下载、切换、删除或设为默认。"
        actions={
          <>
            <Button
              appearance="subtle"
              icon={<PeopleCommunityRegular />}
              onClick={() => navigate('/community')}
            >
              社区适配
            </Button>
            <Button
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={() => void Promise.all([refreshModels(), refreshSystem()])}
            >
              刷新
            </Button>
          </>
        }
      />

      <section className="kind-tabs" role="tablist" aria-label="模型类型">
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'asr'}
          className={kind === 'asr' ? 'is-active' : ''}
          onClick={() => changeKind('asr')}
        >
          <span>Whisper ASR</span>
          <small>语音识别 · {models?.installed.filter((item) => item.kind === 'asr').length ?? 0}</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'tts'}
          className={kind === 'tts' ? 'is-active' : ''}
          onClick={() => changeKind('tts')}
        >
          <span>IndexTTS</span>
          <small>语音合成 · {models?.installed.filter((item) => item.kind === 'tts').length ?? 0}</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'image'}
          className={kind === 'image' ? 'is-active' : ''}
          onClick={() => changeKind('image')}
        >
          <span>图像模型</span>
          <small>SD / FLUX / Qwen · {models?.installed.filter((item) => item.kind === 'image').length ?? 0}</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'llm'}
          className={kind === 'llm' ? 'is-active' : ''}
          onClick={() => changeKind('llm')}
        >
          <span>语言模型</span>
          <small>GGUF · {models?.installed.filter((item) => item.kind === 'llm').length ?? 0}</small>
        </button>
      </section>

      <section className="library-summary">
        <div className="summary-main">
          <div className="summary-icon">
            <HardwareIcon kind={kind === 'tts' ? 'npu' : 'gpu'} size={24} />
          </div>
          <div>
            <span>
              {kind === 'tts'
                ? '已安装 TTS 模型'
                : kind === 'image'
                  ? '已安装图像模型'
                  : kind === 'llm'
                    ? '已安装语言模型'
                    : '已安装 ASR 模型'}
            </span>
            <strong>
              {kindInstalled.length}
              <small> / {kindCatalog.length || 2}</small>
            </strong>
          </div>
        </div>
        <div className="summary-divider" />
        <div className="summary-cell">
          <span>模型占用</span>
          <strong>{formatBytes(models?.storage.models_bytes ?? 0)}</strong>
        </div>
        <div className="summary-cell">
          <span>可用存储</span>
          <strong>{formatBytes(models?.storage.free_bytes ?? null)}</strong>
        </div>
        <div className="summary-cell summary-path">
          <span>存储位置</span>
          <strong title={kind === 'llm' ? models?.storage.llm_models_dir : models?.storage.models_dir}>
            <FolderOpenRegular />
            {(kind === 'llm' ? models?.storage.llm_models_dir : models?.storage.models_dir) ?? '—'}
          </strong>
        </div>
        {activeDownloads.length > 0 && (
          <StatusPill tone="brand">{activeDownloads.length} 个下载进行中</StatusPill>
        )}
      </section>

      {activeDownloads.length > 0 && (
        <section className="download-queue panel">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">DOWNLOADS</span>
              <h3>下载队列</h3>
            </div>
            <span className="queue-hint">来自 Hugging Face · 支持自动校验</span>
          </div>
          <div className="queue-list">
            {activeDownloads.map((task) => (
              <div className="queue-item" key={task.id}>
                <div className="queue-model">
                  <div className="model-glyph model-glyph-sm">
                    <span />
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                  <div>
                    <strong>{task.model_name}</strong>
                    <span>
                      {task.status === 'downloading'
                        ? task.current_file ?? '准备中'
                        : downloadLabel(task.status)}
                      {task.files_total > 0 && ` · ${task.files_done}/${task.files_total} 文件`}
                    </span>
                  </div>
                </div>
                <div className="queue-progress">
                  <div className="queue-progress-meta">
                    <strong>{Math.round(task.progress)}%</strong>
                    <span>
                      {formatBytes(task.bytes_downloaded)} / {formatBytes(task.total_bytes)}
                      {task.speed_bps > 0 && ` · ${formatBytes(task.speed_bps)}/s`}
                      {task.speed_bps > 0 && ` · ${formatEta(task.eta_seconds)}`}
                    </span>
                  </div>
                  <ProgressBar value={task.progress / 100} thickness="medium" />
                </div>
                <Button
                  appearance="subtle"
                  icon={<DismissRegular />}
                  onClick={() => void cancelDownload(task.id, task.model_name)}
                  aria-label={`取消下载 ${task.model_name}`}
                >
                  取消
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="library-toolbar">
        <div className="filter-pills">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`filter-pill${filter === item.id ? ' is-active' : ''}`}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
              {item.id === 'installed' && (
                <span>{kindInstalled.length}</span>
              )}
            </button>
          ))}
        </div>
        <Input
          className="model-search"
          value={search}
          onChange={(_, data) => setSearch(data.value)}
          contentBefore={<SearchRegular />}
          placeholder="搜索模型、能力或语言"
          aria-label="搜索模型"
        />
      </section>

      {loading && catalog.length === 0 ? (
        <section className="model-grid">
          {Array.from({ length: 6 }).map((_, index) => (
            <div className="model-card skeleton-card" key={index} />
          ))}
        </section>
      ) : visible.length === 0 ? (
        <EmptyState
          icon={<SearchRegular />}
          title="没有匹配的模型"
          description={
            kind === 'asr'
              ? '换一个关键词，或切换到「全部模型」查看完整 Whisper 家族。'
              : kind === 'image'
                ? '换一个关键词，或切换到「全部模型」查看 SD / FLUX / Qwen-Image。'
                : kind === 'llm'
                  ? '换一个关键词，或切换到「全部模型」查看 Qwen / Llama / Mistral GGUF。'
                  : '换一个关键词，或切换到「全部模型」查看 IndexTTS 模型。'
          }
          action={
            <Button
              appearance="secondary"
              onClick={() => {
                setSearch('');
                setFilter('all');
              }}
            >
              清除筛选
            </Button>
          }
        />
      ) : (
        <section className="model-grid">
          {visible.map((model) => {
            const task = models?.downloads.find(
              (item) =>
                item.model_id === model.id &&
                ['queued', 'downloading', 'cancelling'].includes(item.status),
            );
            const isRecommended = recommendedId === model.id;
            const isDefault =
              model.kind === 'asr'
                ? settings?.default_model === model.id
                : model.kind === 'image'
                  ? settings?.default_image_model === model.id
                  : model.kind === 'llm'
                    ? settings?.default_llm_model === model.id
                    : settings?.default_tts_model === model.id;
            const isBusy = busyModel === model.id;
            return (
              <article
                key={model.id}
                className={`model-card${isRecommended ? ' is-recommended' : ''}${
                  model.installed ? ' is-installed' : ''
                }`}
              >
                <div className="model-card-top">
                  <div className={`model-glyph model-glyph-${Math.round(model.accuracy)}`}>
                    <span />
                    <span />
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="model-title-wrap">
                    <div className="model-title-row">
                      <h3>{model.name}</h3>
                      {isDefault && (
                        <span className="default-chip">
                          <StarFilled /> 默认
                        </span>
                      )}
                    </div>
                    <span className="model-repo">{model.repo.split('/')[1]}</span>
                  </div>
                  {isRecommended && !model.installed && (
                    <StatusPill tone="brand" dot={false}>
                      推荐
                    </StatusPill>
                  )}
                </div>

                <div className="model-tags">
                  {model.tags.map((tag) => (
                    <span className="model-tag" key={tag}>
                      {tag}
                    </span>
                  ))}
                  <span className="model-tag model-tag-muted">{model.format}</span>
                  {kind === 'llm' && model.quantization && (
                    <span className="model-tag model-tag-muted">{model.quantization}</span>
                  )}
                  {model.external && (
                    <span className="model-tag model-tag-community">社区</span>
                  )}
                </div>

                <p className="model-description">{model.description}</p>

                <div className="model-specs">
                  <div>
                    <span>体积</span>
                    <strong>{model.size_label}</strong>
                  </div>
                  <div>
                    <span>参数</span>
                    <strong>{model.parameters}</strong>
                  </div>
                  <div>
                    <span>内存</span>
                    <strong>{model.memory_gb} GB+</strong>
                  </div>
                  <div>
                    <span>{kind === 'llm' ? '上下文' : '语言'}</span>
                    <strong>
                      {kind === 'llm'
                        ? model.context_length
                          ? `${Math.round(model.context_length / 1024)}K`
                          : '—'
                        : model.languages}
                    </strong>
                  </div>
                </div>

                <div className="model-metrics">
                  <MetricBar label="速度" value={model.speed} max={5} tone="mint" />
                  <MetricBar
                    label={model.kind === 'asr' ? '精度' : '质量'}
                    value={model.accuracy}
                    max={5}
                    tone="brand"
                  />
                </div>

                {task ? (
                  <div className="model-download-state">
                    <div>
                      <span>{downloadLabel(task.status)}</span>
                      <strong>{Math.round(task.progress)}%</strong>
                    </div>
                    <ProgressBar value={task.progress / 100} thickness="medium" />
                    <div className="model-download-meta">
                      <span>
                        {formatBytes(task.bytes_downloaded)} / {formatBytes(task.total_bytes)}
                      </span>
                      <Button
                        appearance="subtle"
                        size="small"
                        onClick={() => void cancelDownload(task.id, task.model_name)}
                      >
                        取消
                      </Button>
                    </div>
                  </div>
                ) : model.installed ? (
                  <div className="model-card-footer">
                    <div className="installed-flag">
                      <CheckmarkRegular /> {model.external ? '社区适配' : '已安装'}
                      <span>
                        {model.external ? '由外部适配器提供' : formatBytes(model.installed_bytes)}
                      </span>
                    </div>
                    <div className="model-actions">
                      {!isDefault && (
                        <Button
                          appearance="subtle"
                          size="small"
                          onClick={() => void setDefaultModel(model)}
                        >
                          设为默认
                        </Button>
                      )}
                      {model.external && (
                        <Button
                          appearance="subtle"
                          size="small"
                          onClick={() => navigate('/community')}
                        >
                          适配器
                        </Button>
                      )}
                      <Button
                        appearance="primary"
                        size="small"
                        icon={<ArrowRightRegular />}
                        onClick={() =>
                          navigate(
                            model.kind === 'tts'
                              ? '/tts'
                              : model.kind === 'image'
                                ? '/images'
                                : model.kind === 'llm'
                                  ? '/chat'
                                  : '/transcribe',
                          )
                        }
                      >
                        使用
                      </Button>
                      {!model.external && (
                        <Dialog
                          open={deleting?.id === model.id}
                          onOpenChange={(_, data) => {
                            if (!data.open) setDeleting(null);
                          }}
                        >
                          <DialogTrigger disableButtonEnhancement>
                            <Button
                              appearance="subtle"
                              size="small"
                              icon={<DeleteRegular />}
                              aria-label={`删除 ${model.name}`}
                              onClick={() => setDeleting(model)}
                            />
                          </DialogTrigger>
                          <DialogSurface>
                            <DialogBody>
                              <DialogTitle>删除 {model.name}？</DialogTitle>
                              <DialogContent>
                                将释放 {formatBytes(model.installed_bytes)} 磁盘空间。模型的
                              manifest 与权重文件会从本机永久移除，已完成的转写记录不受影响。
                            </DialogContent>
                            <DialogActions>
                              <DialogTrigger disableButtonEnhancement>
                                <Button appearance="secondary">取消</Button>
                              </DialogTrigger>
                              <Button
                                appearance="primary"
                                onClick={() => void confirmDelete()}
                                disabled={deleteBusy}
                              >
                                {deleteBusy ? '正在删除…' : '删除模型'}
                              </Button>
                            </DialogActions>
                          </DialogBody>
                        </DialogSurface>
                      </Dialog>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="model-card-footer">
                    <span className="model-source">来源 · {model.source} · {model.license}</span>
                    <Button
                      appearance="primary"
                      size="small"
                      icon={<ArrowDownloadRegular />}
                      disabled={isBusy}
                      onClick={() => void startDownload(model)}
                    >
                      {isBusy ? '创建任务…' : '下载模型'}
                    </Button>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}

      <section className="model-footnote">
        <div>
          <strong>
            {kind === 'tts'
              ? 'IndexTTS · PyTorch 权重'
              : kind === 'image'
                ? 'Stable Diffusion / FLUX / Qwen-Image'
                : kind === 'llm'
                  ? 'GGUF · Qwen / Llama / Mistral / Gemma'
                  : 'Whisper 家族 · CTranslate2 格式'}
          </strong>
          <span>
            {kind === 'tts'
              ? 'IndexTTS 通过独立 Python worker 加载，需要 AIBOX_INDEXTTS_HOME 与运行时环境；模型下载完成后自动校验 config.yaml / gpt.pth。'
              : kind === 'image'
                ? '图像模型通过 Diffusers worker 加载，需要 AIBOX_IMAGE_PYTHON 与 diffusers + torch；也可以改用 ComfyUI 管理权重，不在 AIBox 下载。'
                : kind === 'llm'
                  ? '语言模型为单文件 GGUF，通过 llama-server 运行；设置 AIBOX_LLAMA_SERVER 或安装到 PATH，也可以连接 OpenAI 兼容服务。'
                  : '所有模型由 faster-whisper 加载，支持 CPU int8 与 NVIDIA CUDA float16。下载完成后自动校验 model.bin。'}
          </span>
        </div>
        <div>
          <strong>模型保存在哪里？</strong>
          <span>
            {kind === 'tts'
              ? models?.storage.tts_models_dir ?? '本机数据目录'
              : kind === 'image'
                ? models?.storage.image_models_dir ?? '本机数据目录'
                : kind === 'llm'
                  ? models?.storage.llm_models_dir ?? '本机数据目录'
                  : models?.storage.models_dir ?? '本机数据目录'}
          </span>
        </div>
        <StatusPill tone="neutral" dot={false}>
          可离线使用
        </StatusPill>
      </section>
    </div>
  );
}
