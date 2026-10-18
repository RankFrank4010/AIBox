import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Select,
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  ArrowUploadRegular,
  DeleteRegular,
  MicRegular,
  SparkleRegular,
  Speaker2Regular,
  StopRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { AudioPlayer } from '../components/AudioPlayer';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { SeparationJob, SeparationStatus } from '../api/types';
import { formatBytes, formatRelative } from '../utils/format';

const MODES = [
  {
    id: 'instrumental',
    label: '去人声',
    note: '保留伴奏 / 背景音乐',
    icon: <Speaker2Regular />,
  },
  {
    id: 'vocals',
    label: '去背景',
    note: '保留干净人声',
    icon: <MicRegular />,
  },
  {
    id: 'stems',
    label: '全部分轨',
    note: '人声 / 鼓 / 贝斯 / 其他',
    icon: <SparkleRegular />,
  },
] as const;

function statusLabel(status: SeparationStatus | null): string {
  if (!status) return '检测中';
  if (status.demo) return '演示引擎';
  if (status.demucs_ready && status.audio_separator_ready) return 'Demucs + UVR';
  if (status.demucs_ready) return 'Demucs 就绪';
  if (status.audio_separator_ready) return 'UVR 就绪';
  return '运行时未安装';
}

function statusTone(status: SeparationStatus | null) {
  if (!status) return 'neutral' as const;
  if (status.demo) return 'warning' as const;
  if (status.demucs_ready || status.audio_separator_ready) return 'success' as const;
  return 'neutral' as const;
}

export function SeparationsPage() {
  const { system, notify } = useAppData();
  const [status, setStatus] = useState<SeparationStatus | null>(
    system?.separation ?? null,
  );
  const [jobs, setJobs] = useState<SeparationJob[]>([]);
  const [current, setCurrent] = useState<SeparationJob | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [modelId, setModelId] = useState('htdemucs');
  const [mode, setMode] = useState<(typeof MODES)[number]['id']>('instrumental');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const models = status?.models ?? [];
  const selectedModel =
    models.find((item) => item.id === modelId) ?? models[0] ?? null;
  const canGenerate =
    Boolean(file) && !busy && Boolean(status?.demo || selectedModel?.available);

  const load = async () => {
    setLoading(true);
    try {
      const [nextStatus, history] = await Promise.all([
        api.separationStatus(),
        api.separations(20),
      ]);
      setStatus(nextStatus);
      setJobs(history.items);
      if (!current && history.items.length > 0) setCurrent(history.items[0]);
    } catch (err) {
      notify('读取分离引擎失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!current || !['queued', 'running', 'cancelling'].includes(current.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void api
        .separationJob(current.id)
        .then((job) => {
          setCurrent(job);
          setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
          if (job.status === 'completed') {
            notify('分离完成', `${job.outputs.length} 个分轨已生成`, 'success');
          }
          if (job.status === 'failed') {
            notify('分离失败', job.error ?? '请检查分离运行时。', 'error');
          }
        })
        .catch(() => undefined);
    }, 900);
    return () => window.clearInterval(timer);
  }, [current?.id, current?.status, notify]);

  const chooseFile = (next: File | null) => {
    if (!next) return;
    if (next.size > 512 * 1024 * 1024) {
      notify('文件过大', '音频不能超过 512 MB。', 'error');
      return;
    }
    setFile(next);
    setCurrent(null);
  };

  const generate = async () => {
    if (!file || !canGenerate) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('model_id', selectedModel?.id ?? 'htdemucs');
      form.append('mode', mode);
      const job = await api.createSeparation(form);
      setCurrent(job);
      setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      notify('已提交分离任务', `${selectedModel?.name ?? 'Demucs'} · ${file.name}`, 'info');
    } catch (err) {
      notify('无法开始分离', errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!current) return;
    try {
      setCurrent(await api.cancelSeparation(current.id));
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const remove = async (job: SeparationJob) => {
    if (!window.confirm('删除这条分离记录和所有分轨文件？')) return;
    try {
      await api.deleteSeparation(job.id);
      setJobs((items) => items.filter((item) => item.id !== job.id));
      if (current?.id === job.id) setCurrent(null);
      notify('分离记录已删除', '', 'info');
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  return (
    <div className="page separations-page">
      <PageHeader
        eyebrow="STEM SEPARATION"
        title="人声 / 伴奏分离"
        description="上传歌曲或录音，分离人声、伴奏与乐器。默认只保留你需要的分轨，不展示复杂的频谱或模型参数。"
        actions={
          <>
            <StatusPill tone={statusTone(status)}>{statusLabel(status)}</StatusPill>
            <Button
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={() => void load()}
            >
              刷新
            </Button>
          </>
        }
      />

      <section className="separations-layout">
        <div className="panel separation-composer">
          <div className="images-section-head">
            <div>
              <span className="panel-kicker">SOURCE AUDIO</span>
              <h2>选择要分离的音频</h2>
            </div>
            <span className="images-count">WAV · MP3 · M4A · FLAC · OGG</span>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac"
            className="visually-hidden"
            onChange={(event) => {
              chooseFile(event.target.files?.[0] ?? null);
              event.target.value = '';
            }}
          />
          <button
            type="button"
            className={`separation-drop${dragging ? ' is-dragging' : ''}${file ? ' has-file' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              chooseFile(event.dataTransfer.files?.[0] ?? null);
            }}
          >
            <div className="separation-drop-icon">
              <ArrowUploadRegular />
            </div>
            {file ? (
              <>
                <strong>{file.name}</strong>
                <span>{formatBytes(file.size)} · 点击更换</span>
              </>
            ) : (
              <>
                <strong>拖入音频，或点击选择</strong>
                <span>建议使用 44.1 kHz / 16-bit WAV 或高质量 MP3</span>
              </>
            )}
          </button>

          <div className="separation-modes">
            <span className="field-label">分离目标</span>
            <div className="separation-mode-grid">
              {MODES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={mode === item.id ? 'is-active' : ''}
                  onClick={() => setMode(item.id)}
                >
                  <span className="separation-mode-icon">{item.icon}</span>
                  <strong>{item.label}</strong>
                  <small>{item.note}</small>
                </button>
              ))}
            </div>
          </div>

          <label className="field">
            <span className="field-label">分离模型</span>
            <Select value={selectedModel?.id ?? ''} onChange={(_, data) => setModelId(data.value)}>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} · {model.size_label}{model.available ? '' : ' · 未就绪'}
                </option>
              ))}
            </Select>
            <span className="field-hint">
              {selectedModel?.description ??
                'Demucs 四轨模型适合大多数歌曲；UVR / MDX 更适合卡拉 OK 伴奏与人声提取。'}
            </span>
          </label>

          <div className="separation-actions">
            <Button
              appearance="primary"
              size="large"
              className="button-glow"
              icon={busy ? <Spinner size="tiny" /> : <SparkleRegular />}
              onClick={() => void generate()}
              disabled={!canGenerate}
            >
              {busy ? '正在提交…' : '开始分离'}
            </Button>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) && (
              <Button appearance="secondary" icon={<StopRegular />} onClick={() => void cancel()}>
                取消
              </Button>
            )}
          </div>

          {!status?.demo &&
            !status?.demucs_ready &&
            !status?.audio_separator_ready && (
              <div className="inline-note warning-note">
                <WarningRegular /> 分离运行时未安装。请安装 Demucs 或 audio-separator，
                并设置 <code>AIBOX_SEPARATION_PYTHON</code>；也可以先设置{' '}
                <code>AIBOX_DEMO_SEPARATION=1</code> 验证界面。
              </div>
            )}
          <div className="separation-runtime">
            <span>Python：{status?.python ?? '—'}</span>
            <span>Demucs：{status?.demucs_ready ? '就绪' : '未安装'}</span>
            <span>UVR：{status?.audio_separator_ready ? '就绪' : '未安装'}</span>
          </div>
        </div>

        <aside className="separation-output">
          <div className="panel separation-result-panel">
            <div className="images-section-head">
              <div>
                <span className="panel-kicker">STEMS</span>
                <h2>分轨结果</h2>
              </div>
              {current && <StatusPill tone={jobTone(current.status)}>{jobLabel(current.status)}</StatusPill>}
            </div>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) ? (
              <div className="separation-progress">
                <div className="separation-progress-orb">
                  <SparkleRegular />
                </div>
                <strong>{current.stage}</strong>
                <span>{current.filename}</span>
                <div className="images-progress-track">
                  <span style={{ width: `${current.progress}%` }} />
                </div>
                <small>{Math.round(current.progress)}%</small>
              </div>
            ) : current?.status === 'failed' ? (
              <div className="images-failed">
                <WarningRegular />
                <h3>分离失败</h3>
                <p>{current.error}</p>
                <Button appearance="secondary" onClick={() => void generate()}>
                  重试
                </Button>
              </div>
            ) : current?.outputs.length ? (
              <div className="separation-result">
                <div className="separation-result-head">
                  <div>
                    <strong>{current.filename}</strong>
                    <span>
                      {current.mode === 'instrumental'
                        ? '去人声 · 保留伴奏'
                        : current.mode === 'vocals'
                          ? '去背景 · 保留人声'
                          : '全部分轨'}{' '}
                      · {current.model_id}
                    </span>
                  </div>
                  <Button
                    appearance="subtle"
                    size="small"
                    icon={<DeleteRegular />}
                    onClick={() => void remove(current)}
                  >
                    删除
                  </Button>
                </div>
                <div className="stems-grid">
                  {current.outputs.map((output) => (
                    <div className="stem-card" key={output.role}>
                      <div className="stem-head">
                        <strong>{output.label}</strong>
                        <a
                          className="stem-download"
                          href={api.url(output.url)}
                          download={output.filename}
                          aria-label={`下载 ${output.label}`}
                        >
                          <ArrowDownloadRegular />
                        </a>
                      </div>
                      <AudioPlayer src={api.url(output.url)} />
                    </div>
                  ))}
                </div>
                {current.duration && (
                  <div className="separation-duration">
                    原音频时长 {Math.round(current.duration)} 秒 · 处理后保留{' '}
                    {current.outputs.length} 个分轨
                  </div>
                )}
              </div>
            ) : (
              <div className="images-empty">
                <div className="images-empty-orb">
                  <Speaker2Regular />
                </div>
                <h3>把人声和伴奏分开</h3>
                <p>
                  上传一首歌，选择「去人声」得到伴奏，或选择「去背景」提取人声。
                  Demucs 还支持鼓、贝斯与其他乐器的全部分轨。
                </p>
                <div className="images-features">
                  <span>Demucs</span>
                  <span>UVR / MDX</span>
                  <span>WAV 分轨</span>
                  <span>本地处理</span>
                </div>
              </div>
            )}
          </div>

          <div className="panel separation-history-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">RECENT</span>
                <h3>最近分离</h3>
              </div>
              {loading && <Spinner size="tiny" />}
            </div>
            {jobs.length === 0 ? (
              <EmptyState
                icon={<MicRegular />}
                title="还没有分离记录"
                description="上传音频并开始分离后，记录会显示在这里。"
              />
            ) : (
              <div className="separation-history">
                {jobs.slice(0, 10).map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`separation-history-item${current?.id === job.id ? ' is-active' : ''}`}
                    onClick={() => setCurrent(job)}
                  >
                    <span className={`separation-history-dot status-${job.status}`} />
                    <span>
                      <strong>{job.filename}</strong>
                      <small>
                        {job.mode === 'instrumental'
                          ? '去人声'
                          : job.mode === 'vocals'
                            ? '去背景'
                            : '全部分轨'}{' '}
                        · {job.model_id} · {formatRelative(job.created_at)}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}

function jobLabel(status: string): string {
  if (status === 'completed') return '已完成';
  if (status === 'running') return '分离中';
  if (status === 'queued') return '排队中';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status;
}

function jobTone(status: string) {
  if (status === 'completed') return 'success' as const;
  if (status === 'failed') return 'danger' as const;
  if (status === 'cancelled') return 'neutral' as const;
  return 'warning' as const;
}
