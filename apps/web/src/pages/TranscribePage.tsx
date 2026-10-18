import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import {
  Button,
  ProgressBar,
  Select,
  Slider,
  Spinner,
  Switch,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowUploadRegular,
  CheckmarkRegular,
  CopyRegular,
  DismissRegular,
  DocumentTextRegular,
  HistoryRegular,
  MicRegular,
  PlayRegular,
  SettingsRegular,
  StopRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { AudioPlayer, type AudioPlayerHandle } from '../components/AudioPlayer';
import { Waveform } from '../components/Waveform';
import { EmptyState } from '../components/EmptyState';
import { HardwareIcon } from '../components/HardwareIcon';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { TranscriptionRecord } from '../api/types';
import {
  formatBytes,
  formatDate,
  formatDuration,
  formatTimestamp,
  languageLabel,
} from '../utils/format';
import { transcriptionLabel, transcriptionTone } from '../utils/status';

const AUDIO_EXTENSIONS = [
  '.wav',
  '.mp3',
  '.m4a',
  '.flac',
  '.ogg',
  '.oga',
  '.opus',
  '.webm',
  '.mp4',
  '.aac',
  '.wma',
  '.aiff',
  '.aif',
  '.caf',
];

const STEP_LABELS = ['上传音频', '加载模型', '语音识别', '字幕生成'];

function stepFromRecord(record: TranscriptionRecord): number {
  if (record.status === 'completed') return 4;
  if (record.progress >= 98) return 3;
  if (record.progress >= 6) return 2;
  if (record.stage.includes('模型')) return 1;
  return 0;
}

export function TranscribePage() {
  const { system, models, settings, notify, refreshSystem } = useAppData();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const jobId = searchParams.get('job');

  const installed = models?.installed?.filter((model) => model.kind === 'asr') ?? [];
  const [selectedModelId, setSelectedModelId] = useState('');
  const [language, setLanguage] = useState('auto');
  const [task, setTask] = useState<'transcribe' | 'translate'>('transcribe');
  const [device, setDevice] = useState('auto');
  const [computeType, setComputeType] = useState('auto');
  const [beamSize, setBeamSize] = useState(5);
  const [vad, setVad] = useState(true);
  const [wordTimestamps, setWordTimestamps] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [fileDuration, setFileDuration] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [active, setActive] = useState<TranscriptionRecord | null>(null);
  const [history, setHistory] = useState<TranscriptionRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [resultTab, setResultTab] = useState<'segments' | 'text'>('segments');
  const [audioTime, setAudioTime] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const audioPlayerRef = useRef<AudioPlayerHandle>(null);
  const initialized = useRef(false);
  const completionNotified = useRef<string | null>(null);
  const failureNotified = useRef<string | null>(null);

  const selectedModel = useMemo(
    () => installed.find((model) => model.id === selectedModelId) ?? null,
    [installed, selectedModelId],
  );
  const isActive = Boolean(
    active && ['queued', 'running', 'cancelling'].includes(active.status),
  );

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.transcriptions(14);
      setHistory(data.items);
    } catch {
      // Connection errors are surfaced in the shell banner.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (!settings || initialized.current) return;
    initialized.current = true;
    setLanguage(settings.language);
    setTask(settings.task);
    setDevice(settings.device);
    setComputeType(settings.compute_type);
    setBeamSize(settings.beam_size);
    setVad(settings.vad_filter);
    setWordTimestamps(settings.word_timestamps);
  }, [settings]);

  useEffect(() => {
    if (selectedModelId && installed.some((model) => model.id === selectedModelId)) return;
    if (installed.length === 0) {
      if (selectedModelId) setSelectedModelId('');
      return;
    }
    const preferred =
      settings?.default_model && installed.some((model) => model.id === settings.default_model)
        ? settings.default_model
        : installed.find((model) => !model.english_only)?.id ?? installed[0].id;
    setSelectedModelId(preferred);
  }, [installed, selectedModelId, settings]);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    void api
      .transcription(jobId)
      .then((record) => {
        if (cancelled) return;
        setActive(record);
        setResultTab(record.segments.length > 0 ? 'segments' : 'text');
      })
      .catch((err) => {
        if (!cancelled) notify('无法读取转写记录', errorMessage(err), 'error');
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, notify]);

  useEffect(() => {
    if (!active?.id || !isActive) return;
    const activeId = active.id;
    let cancelled = false;
    const tick = async () => {
      try {
        const record = await api.transcription(activeId);
        if (cancelled) return;
        setActive(record);
        if (record.status === 'completed' && completionNotified.current !== record.id) {
          completionNotified.current = record.id;
          notify('转写完成', `${record.filename} · ${formatDuration(record.duration)}`, 'success');
          setResultTab(record.segments.length > 0 ? 'segments' : 'text');
          void loadHistory();
          void refreshSystem();
        }
        if (
          (record.status === 'failed' || record.status === 'cancelled') &&
          failureNotified.current !== record.id
        ) {
          failureNotified.current = record.id;
          if (record.status === 'failed') {
            notify('转写失败', record.error ?? '请查看任务详情后重试。', 'error');
          } else {
            notify('任务已取消', record.filename, 'info');
          }
          void loadHistory();
        }
      } catch (err) {
        if (!cancelled) {
          // Keep polling on transient failures.
          console.warn(errorMessage(err));
        }
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 950);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active?.id, isActive, loadHistory, notify, refreshSystem]);

  useEffect(() => {
    if (!active?.id || !isActive) {
      setElapsed(0);
      return;
    }
    const start = new Date(active.created_at).getTime();
    const tick = () => setElapsed(Math.max(0, Math.round((Date.now() - start) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1_000);
    return () => window.clearInterval(timer);
  }, [active?.id, active?.created_at, isActive]);

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl],
  );

  const acceptFile = (next: File) => {
    const extension = `.${next.name.split('.').pop()?.toLowerCase() ?? ''}`;
    if (!AUDIO_EXTENSIONS.includes(extension)) {
      notify('不支持的音频格式', '请选择 WAV、MP3、M4A、FLAC、OGG、WEBM 等格式。', 'error');
      return;
    }
    if (next.size > 512 * 1024 * 1024) {
      notify('音频过大', '当前版本单个文件上限为 512 MB。', 'error');
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const url = URL.createObjectURL(next);
    setFile(next);
    setPreviewUrl(url);
    setFileDuration(null);
    setAudioTime(0);
    const probe = new Audio(url);
    probe.onloadedmetadata = () => {
      if (Number.isFinite(probe.duration)) setFileDuration(probe.duration);
    };
    setActive(null);
    completionNotified.current = null;
    failureNotified.current = null;
    setResultTab('segments');
    if (jobId) setSearchParams({}, { replace: true });
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) acceptFile(dropped);
  };

  const removeFile = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(null);
    setPreviewUrl('');
    setFileDuration(null);
    setAudioTime(0);
  };

  const openRecord = (record: TranscriptionRecord) => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(null);
    setPreviewUrl('');
    setFileDuration(null);
    setAudioTime(0);
    setActive(record);
    setResultTab(record.segments.length > 0 ? 'segments' : 'text');
    setSearchParams({ job: record.id }, { replace: true });
  };

  const submit = async () => {
    if (!file || !selectedModel || submitting) return;
    setSubmitting(true);
    const form = new FormData();
    form.append('file', file);
    form.append('model_id', selectedModel.id);
    form.append('language', language);
    form.append('task', task);
    form.append('beam_size', String(beamSize));
    form.append('vad_filter', String(vad));
    form.append('word_timestamps', String(wordTimestamps));
    form.append('device', device);
    form.append('compute_type', computeType);
    try {
      const record = await api.createTranscription(form);
      completionNotified.current = null;
      failureNotified.current = null;
      setActive(record);
      setAudioTime(0);
      setResultTab('segments');
      setSearchParams({ job: record.id }, { replace: true });
      notify(
        '转写任务已开始',
        `${selectedModel.name} · ${device === 'auto' ? '自动选择设备' : device.toUpperCase()}`,
        'info',
      );
      void loadHistory();
    } catch (err) {
      notify('无法开始转写', errorMessage(err), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const cancelActive = async () => {
    if (!active) return;
    try {
      await api.cancelTranscription(active.id);
      setActive({ ...active, status: 'cancelling', stage: '正在取消' });
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const copyText = async () => {
    if (!active?.text) return;
    try {
      await navigator.clipboard.writeText(active.text);
      notify('已复制到剪贴板', `${active.text.length} 个字符`, 'success');
    } catch {
      notify('复制失败', '浏览器拒绝访问剪贴板。', 'error');
    }
  };

  const chooseFile = () => fileInputRef.current?.click();
  const activeSegment =
    active?.segments.find((segment) => audioTime >= segment.start && audioTime < segment.end) ??
    null;
  const progress = active?.progress ?? 0;

  return (
    <div className="page transcribe-page">
      <PageHeader
        eyebrow="ASR WORKSPACE"
        title="语音转写"
        description="上传音频，选择 Whisper 模型与推理设备。转写、时间轴与字幕导出都在本机完成。"
        actions={
          installed.length > 0 ? (
            <StatusPill tone="success">
              {installed.length} 个模型可用
            </StatusPill>
          ) : (
            <StatusPill tone="warning">需要先安装模型</StatusPill>
          )
        }
      />

      <section className="transcribe-layout">
        <aside className="transcribe-config">
          <div className="panel config-panel">
            <div className="config-section-head">
              <span className="step-badge">01</span>
              <div>
                <h3>音频文件</h3>
                <p>WAV / MP3 / M4A / FLAC / OGG，最大 512 MB</p>
              </div>
            </div>

            <input
              ref={fileInputRef}
              type="file"
              accept={AUDIO_EXTENSIONS.join(',')}
              className="visually-hidden"
              onChange={(event) => {
                const next = event.target.files?.[0];
                if (next) acceptFile(next);
              }}
            />

            <div
              className={`dropzone${dragging ? ' is-dragging' : ''}${file ? ' has-file' : ''}`}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={file ? undefined : chooseFile}
              role={file ? undefined : 'button'}
              tabIndex={file ? undefined : 0}
              onKeyDown={(event) => {
                if (!file && (event.key === 'Enter' || event.key === ' ')) chooseFile();
              }}
            >
              {file ? (
                <div className="selected-file">
                  <div className="selected-file-top">
                    <div className="audio-file-icon">
                      <Waveform bars={13} compact />
                    </div>
                    <div className="selected-file-copy">
                      <strong title={file.name}>{file.name}</strong>
                      <span>
                        {formatBytes(file.size)} · {formatDuration(fileDuration)}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="icon-button icon-button-sm"
                      aria-label="移除音频"
                      onClick={(event) => {
                        event.stopPropagation();
                        removeFile();
                      }}
                    >
                      <DismissRegular />
                    </button>
                  </div>
                  {previewUrl && (
                    <div onClick={(event) => event.stopPropagation()}>
                      <AudioPlayer src={previewUrl} onTimeUpdate={(time) => setAudioTime(time)} />
                    </div>
                  )}
                  <button
                    type="button"
                    className="dropzone-replace"
                    onClick={(event) => {
                      event.stopPropagation();
                      chooseFile();
                    }}
                  >
                    更换音频文件
                  </button>
                </div>
              ) : (
                <div className="dropzone-empty">
                  <div className="dropzone-icon">
                    <ArrowUploadRegular />
                  </div>
                  <strong>拖入音频，或点击选择</strong>
                  <span>文件只会上传到本机 AIBox 服务</span>
                  <button type="button" className="dropzone-browse">
                    浏览文件
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="panel config-panel">
            <div className="config-section-head">
              <span className="step-badge">02</span>
              <div>
                <h3>模型与参数</h3>
                <p>为当前音频选择推理方式</p>
              </div>
            </div>

            {installed.length === 0 ? (
              <EmptyState
                compact
                icon={<HardwareIcon kind="gpu" size={24} />}
                title="还没有安装 Whisper 模型"
                description="下载一个模型后即可开始。Small 适合多数 CPU，Large v3 Turbo 适合独立显卡。"
                action={
                  <Button appearance="primary" onClick={() => navigate('/models')}>
                    前往模型库
                  </Button>
                }
              />
            ) : (
              <>
                <label className="field">
                  <span className="field-label">Whisper 模型</span>
                  <Select
                    value={selectedModelId}
                    onChange={(_, data) => setSelectedModelId(data.value)}
                  >
                    {installed.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name} · {model.size_label}
                        {model.english_only ? ' · 英文' : ''}
                      </option>
                    ))}
                  </Select>
                  {selectedModel && (
                    <span className="field-hint">
                      {selectedModel.best_for} · {selectedModel.languages} · 精度{' '}
                      {selectedModel.accuracy.toFixed(1)} / 5
                    </span>
                  )}
                </label>

                <div className="field-row">
                  <label className="field">
                    <span className="field-label">语言</span>
                    <Select value={language} onChange={(_, data) => setLanguage(data.value)}>
                      <option value="auto">自动检测</option>
                      <option value="zh">中文</option>
                      <option value="en">英语</option>
                      <option value="ja">日语</option>
                      <option value="ko">韩语</option>
                      <option value="de">德语</option>
                      <option value="fr">法语</option>
                      <option value="es">西班牙语</option>
                      <option value="ru">俄语</option>
                    </Select>
                  </label>
                  <div className="field">
                    <span className="field-label">任务</span>
                    <div className="segmented-control">
                      <button
                        type="button"
                        className={task === 'transcribe' ? 'is-active' : ''}
                        onClick={() => setTask('transcribe')}
                      >
                        转写
                      </button>
                      <button
                        type="button"
                        className={task === 'translate' ? 'is-active' : ''}
                        onClick={() => setTask('translate')}
                      >
                        译为英文
                      </button>
                    </div>
                  </div>
                </div>

                {task === 'translate' && (
                  <div className="inline-note">
                    Whisper 的翻译任务只会把语音翻译为英文，不会翻译为中文。
                  </div>
                )}

                <details className="advanced-options">
                  <summary>
                    <span>
                      <SettingsRegular /> 高级选项
                    </span>
                    <small>设备、精度与解码参数</small>
                  </summary>
                  <div className="advanced-body">
                    <div className="field-row">
                      <label className="field">
                        <span className="field-label">推理设备</span>
                        <Select value={device} onChange={(_, data) => setDevice(data.value)}>
                          <option value="auto">自动选择</option>
                          <option value="cpu">CPU</option>
                          <option value="cuda" disabled={!system?.has_cuda}>
                            NVIDIA CUDA{system?.has_cuda ? '' : '（不可用）'}
                          </option>
                          {system?.npus.length ? (
                            <option value="npu" disabled>
                              NPU（适配中）
                            </option>
                          ) : null}
                        </Select>
                      </label>
                      <label className="field">
                        <span className="field-label">计算精度</span>
                        <Select
                          value={computeType}
                          onChange={(_, data) => setComputeType(data.value)}
                        >
                          <option value="auto">自动</option>
                          <option value="int8">int8</option>
                          <option value="int8_float16">int8_float16</option>
                          <option value="float16">float16</option>
                          <option value="float32">float32</option>
                        </Select>
                      </label>
                    </div>

                    <label className="field">
                      <span className="field-label">
                        Beam size <strong className="field-value">{beamSize}</strong>
                      </span>
                      <Slider
                        min={1}
                        max={10}
                        step={1}
                        value={beamSize}
                        onChange={(_, data) => setBeamSize(data.value)}
                      />
                      <span className="field-hint">更高值通常更准确，但会变慢。</span>
                    </label>

                    <div className="switch-row">
                      <div>
                        <strong>VAD 静音过滤</strong>
                        <span>跳过长静音，提高长音频速度</span>
                      </div>
                      <Switch
                        checked={vad}
                        onChange={(_, data) => setVad(data.checked)}
                        aria-label="VAD 静音过滤"
                      />
                    </div>
                    <div className="switch-row">
                      <div>
                        <strong>词级时间戳</strong>
                        <span>为每个词记录起止时间，结果文件更大</span>
                      </div>
                      <Switch
                        checked={wordTimestamps}
                        onChange={(_, data) => setWordTimestamps(data.checked)}
                        aria-label="词级时间戳"
                      />
                    </div>
                  </div>
                </details>
              </>
            )}
          </div>

          <Button
            appearance="primary"
            size="large"
            className="start-transcribe button-glow"
            icon={submitting ? <Spinner size="tiny" /> : <MicRegular />}
            disabled={!file || !selectedModel || submitting || isActive}
            onClick={() => void submit()}
          >
            {submitting
              ? '正在上传音频…'
              : isActive
                ? '任务正在运行'
                : '开始转写'}
          </Button>
          <span className="start-hint">
            音频与结果仅保存在本机。Whisper 推理在后台线程运行，可随时离开页面。
          </span>
        </aside>

        <div className="transcribe-output">
          {active ? (
            isActive ? (
              <div className="panel processing-panel">
                <div className="processing-head">
                  <StatusPill tone="brand">{transcriptionLabel(active.status)}</StatusPill>
                  <span>{active.filename}</span>
                </div>
                <div className="processing-main">
                  <div
                    className="progress-ring"
                    style={{
                      background: `conic-gradient(var(--accent) ${progress * 3.6}deg, var(--track) 0deg)`,
                    }}
                  >
                    <div className="progress-ring-inner">
                      <strong>{Math.round(progress)}%</strong>
                      <span>PROCESSING</span>
                    </div>
                  </div>
                  <div className="processing-copy">
                    <h2>{active.stage}</h2>
                    <p>
                      {active.model_id} · {deviceLabel(active.device ?? device)} ·{' '}
                      {active.compute_type ?? '自动精度'}
                    </p>
                    <div className="processing-stats">
                      <div>
                        <span>已运行</span>
                        <strong>{formatDuration(elapsed)}</strong>
                      </div>
                      <div>
                        <span>音频时长</span>
                        <strong>{formatDuration(active.duration ?? fileDuration)}</strong>
                      </div>
                      <div>
                        <span>语言</span>
                        <strong>{languageLabel(active.detected_language ?? language)}</strong>
                      </div>
                    </div>
                  </div>
                </div>
                <ProgressBar value={progress / 100} thickness="large" />
                <div className="stage-track">
                  {STEP_LABELS.map((label, index) => {
                    const current = stepFromRecord(active);
                    const state = index < current ? 'done' : index === current ? 'active' : 'todo';
                    return (
                      <div className={`stage-item is-${state}`} key={label}>
                        <span className="stage-dot">
                          {state === 'done' ? <CheckmarkRegular /> : index + 1}
                        </span>
                        <span>{label}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="processing-actions">
                  <Button
                    appearance="secondary"
                    icon={<StopRegular />}
                    onClick={() => void cancelActive()}
                    disabled={active.status === 'cancelling'}
                  >
                    {active.status === 'cancelling' ? '正在取消…' : '取消任务'}
                  </Button>
                  <span>任务在本地后台执行，离开页面不会中断。</span>
                </div>
              </div>
            ) : active.status === 'failed' || active.status === 'cancelled' ? (
              <div className="panel result-failure">
                <div className="failure-icon">
                  <DismissRegular />
                </div>
                <StatusPill tone={active.status === 'failed' ? 'danger' : 'neutral'}>
                  {transcriptionLabel(active.status)}
                </StatusPill>
                <h2>{active.status === 'failed' ? '这次转写没有完成' : '任务已取消'}</h2>
                <p>
                  {active.error ??
                    '音频仍在本地。检查参数后，可以重新开始一次任务。'}
                </p>
                <div className="failure-details">
                  <span>{active.filename}</span>
                  <span>{active.model_id}</span>
                  <span>{formatDate(active.created_at)}</span>
                </div>
                <div className="failure-actions">
                  {file && (
                    <Button
                      appearance="primary"
                      icon={<PlayRegular />}
                      onClick={() => void submit()}
                      disabled={submitting}
                    >
                      使用当前参数重试
                    </Button>
                  )}
                  <Button appearance="secondary" onClick={() => setActive(null)}>
                    返回工作台
                  </Button>
                </div>
              </div>
            ) : (
              <article className="panel result-panel">
                <div className="result-head">
                  <div className="result-title">
                    <div className="audio-file-icon audio-file-icon-lg">
                      <DocumentTextRegular />
                    </div>
                    <div>
                      <h2>{active.filename}</h2>
                      <span>
                        {formatDate(active.created_at)} · {languageLabel(active.detected_language)}
                        {active.language_probability != null &&
                          ` · ${Math.round(active.language_probability * 100)}%`}
                      </span>
                    </div>
                  </div>
                  <StatusPill tone={transcriptionTone(active.status)}>
                    {transcriptionLabel(active.status)}
                  </StatusPill>
                </div>

                {active.warning && <div className="inline-note warning-note">{active.warning}</div>}

                <div className="result-meta-strip">
                  <div>
                    <span>模型</span>
                    <strong>{active.model_id}</strong>
                  </div>
                  <div>
                    <span>推理</span>
                    <strong>
                      {deviceLabel(active.device)} · {active.compute_type ?? '—'}
                    </strong>
                  </div>
                  <div>
                    <span>时长</span>
                    <strong>{formatDuration(active.duration)}</strong>
                  </div>
                  <div>
                    <span>段落</span>
                    <strong>{active.segments.length}</strong>
                  </div>
                </div>

                {active.has_audio && (
                  <AudioPlayer
                    ref={audioPlayerRef}
                    src={api.url(active.audio_url)}
                    onTimeUpdate={(time) => setAudioTime(time)}
                  />
                )}

                <div className="result-toolbar">
                  <div className="view-tabs">
                    <button
                      type="button"
                      className={resultTab === 'segments' ? 'is-active' : ''}
                      onClick={() => setResultTab('segments')}
                    >
                      分段视图
                    </button>
                    <button
                      type="button"
                      className={resultTab === 'text' ? 'is-active' : ''}
                      onClick={() => setResultTab('text')}
                    >
                      全文
                    </button>
                  </div>
                  <div className="result-actions">
                    <Button
                      appearance="subtle"
                      size="small"
                      icon={<CopyRegular />}
                      onClick={() => void copyText()}
                      disabled={!active.text}
                    >
                      复制全文
                    </Button>
                    {(['srt', 'vtt', 'txt', 'json'] as const).map((format) => (
                      <a
                        className="export-chip"
                        key={format}
                        href={api.url(active.export_urls[format])}
                        download
                      >
                        {format.toUpperCase()}
                      </a>
                    ))}
                  </div>
                </div>

                {resultTab === 'segments' ? (
                  active.segments.length === 0 ? (
                    <EmptyState
                      compact
                      icon={<MicRegular />}
                      title="没有检测到可识别的语音"
                      description="音频可能只有静音，或 VAD 过滤掉了全部片段。"
                    />
                  ) : (
                    <div className="segment-list">
                      {active.segments.map((segment) => (
                        <button
                          type="button"
                          key={segment.id}
                          className={`segment-row${
                            activeSegment?.id === segment.id ? ' is-active' : ''
                          }`}
                          onClick={() => {
                            setAudioTime(segment.start);
                            audioPlayerRef.current?.seek(segment.start);
                          }}
                        >
                          <span className="segment-time">
                            {formatTimestamp(segment.start)}
                            <small>{formatTimestamp(segment.end)}</small>
                          </span>
                          <span className="segment-text">{segment.text}</span>
                          <span className="segment-play">
                            <PlayRegular />
                          </span>
                        </button>
                      ))}
                    </div>
                  )
                ) : (
                  <div className="transcript-full">
                    {active.text || '没有检测到文本。'}
                  </div>
                )}

                <div className="result-foot">
                  <span>
                    <CheckmarkRegular /> 结果保存在本机
                  </span>
                  <a
                    className="text-link"
                    href={api.url(active.export_urls.srt)}
                    download
                  >
                    <ArrowDownloadRegular /> 下载 SRT 字幕
                  </a>
                </div>
              </article>
            )
          ) : (
            <div className="panel ready-panel">
              <div className="ready-visual">
                <div className="ready-rings" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <div className="ready-orb">
                  <Waveform bars={30} active={Boolean(file)} compact />
                </div>
              </div>
              <div className="ready-copy">
                <span className="panel-kicker">READY WHEN YOU ARE</span>
                <h2>{file ? '音频已就绪' : '让声音变成可编辑的文字'}</h2>
                <p>
                  {file
                    ? '参数确认后点击「开始转写」。模型首次加载会稍慢，之后会常驻内存。'
                    : '选择左侧音频，AIBox 会自动使用你安装的 Whisper 模型。字幕时间轴、段落合并与多格式导出都已准备好。'}
                </p>
                <div className="ready-features">
                  <div>
                    <CheckmarkRegular />
                    <span>本地 Whisper 推理</span>
                  </div>
                  <div>
                    <CheckmarkRegular />
                    <span>GPU / CPU 自动选择</span>
                  </div>
                  <div>
                    <CheckmarkRegular />
                    <span>SRT / VTT / JSON 导出</span>
                  </div>
                </div>
                {installed.length === 0 && (
                  <div className="ready-callout">
                    <HardwareIcon kind="gpu" size={20} />
                    <div>
                      <strong>还差一个模型</strong>
                      <span>推荐从 Whisper Small 或 Large v3 Turbo 开始。</span>
                    </div>
                    <Button
                      appearance="primary"
                      size="small"
                      onClick={() => navigate('/models')}
                    >
                      下载模型
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="panel history-panel">
        <div className="panel-heading">
          <div>
            <span className="panel-kicker">HISTORY</span>
            <h3>转写历史</h3>
          </div>
          <StatusPill tone="neutral" dot={false}>
            本机保存
          </StatusPill>
        </div>
        {history.length === 0 ? (
          <EmptyState
            compact
            icon={<HistoryRegular />}
            title={historyLoading ? '正在读取历史…' : '暂无历史记录'}
            description="完成的转写会自动出现在这里，方便再次打开或导出字幕。"
          />
        ) : (
          <div className="history-grid">
            {history.map((item) => (
              <button
                type="button"
                className={`history-card${active?.id === item.id ? ' is-active' : ''}`}
                key={item.id}
                onClick={() => openRecord(item)}
              >
                <div className="history-top">
                  <span className="history-file">
                    <DocumentTextRegular />
                  </span>
                  <StatusPill tone={transcriptionTone(item.status)}>
                    {transcriptionLabel(item.status)}
                  </StatusPill>
                </div>
                <strong title={item.filename}>{item.filename}</strong>
                <span className="history-sub">
                  {item.model_id} · {languageLabel(item.detected_language ?? item.language)} ·{' '}
                  {formatDuration(item.duration)}
                </span>
                <span className="history-time">{formatDate(item.created_at)}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function deviceLabel(device: string | null): string {
  if (!device) return '自动';
  if (device === 'cuda') return 'NVIDIA CUDA';
  if (device === 'cpu') return 'CPU';
  if (device === 'npu') return 'NPU';
  if (device === 'demo') return '演示引擎';
  return device;
}
