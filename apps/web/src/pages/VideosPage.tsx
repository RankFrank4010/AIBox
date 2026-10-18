import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Input,
  Select,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  DeleteRegular,
  SparkleRegular,
  StopRegular,
  VideoRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { VideoJob, VideoStatus } from '../api/types';
import { formatRelative } from '../utils/format';

const ASPECTS = [
  { id: '16:9', label: '16:9 横屏' },
  { id: '9:16', label: '9:16 竖屏' },
  { id: '1:1', label: '1:1 方形' },
  { id: '4:5', label: '4:5 竖版' },
] as const;

function statusLabel(status: VideoStatus | null): string {
  if (!status) return '检测中';
  if (status.demo) return '演示引擎';
  if (status.minimax.configured) return 'MiniMax 已配置';
  if (status.comfyui.available) return 'ComfyUI';
  return '未配置';
}

function statusTone(status: VideoStatus | null) {
  if (!status) return 'neutral' as const;
  if (status.demo) return 'warning' as const;
  if (status.minimax.configured || status.comfyui.available) return 'success' as const;
  return 'neutral' as const;
}

export function VideosPage() {
  const { system, notify } = useAppData();
  const [status, setStatus] = useState<VideoStatus | null>(system?.video ?? null);
  const [jobs, setJobs] = useState<VideoJob[]>([]);
  const [current, setCurrent] = useState<VideoJob | null>(null);
  const [prompt, setPrompt] = useState(
    '雨夜的东京街头，霓虹灯倒映在湿润的路面上，镜头缓慢向前推进，电影感，35mm 胶片',
  );
  const [modelId, setModelId] = useState('minimax-h3');
  const [duration, setDuration] = useState(6);
  const [resolution, setResolution] = useState('1080P');
  const [aspect, setAspect] = useState<(typeof ASPECTS)[number]['id']>('16:9');
  const [seed, setSeed] = useState('');
  const [workflow, setWorkflow] = useState('');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const models = status?.models ?? [];
  const selectedModel =
    models.find((item) => item.id === modelId) ?? models[0] ?? null;
  const canGenerate =
    prompt.trim().length > 0 &&
    !busy &&
    Boolean(status?.demo || selectedModel?.available);

  const load = async () => {
    setLoading(true);
    try {
      const [nextStatus, history] = await Promise.all([
        api.videoStatus(),
        api.videos(16),
      ]);
      setStatus(nextStatus);
      setJobs(history.items);
      if (!current && history.items.length) setCurrent(history.items[0]);
    } catch (err) {
      notify('读取视频引擎失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selectedModel) return;
    if (!selectedModel.durations.includes(duration)) {
      setDuration(selectedModel.durations[0]);
    }
    if (!selectedModel.resolutions.includes(resolution)) {
      setResolution(selectedModel.resolutions[selectedModel.resolutions.length - 1]);
    }
  }, [selectedModel, duration, resolution]);

  useEffect(() => {
    if (!current || !['queued', 'running', 'cancelling'].includes(current.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void api
        .videoJob(current.id)
        .then((job) => {
          setCurrent(job);
          setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
          if (job.status === 'completed') {
            notify('视频生成完成', `${job.width}×${job.height} · ${job.duration}s`, 'success');
          }
          if (job.status === 'failed') {
            notify('视频生成失败', job.error ?? '请检查视频引擎配置。', 'error');
          }
        })
        .catch(() => undefined);
    }, 1200);
    return () => window.clearInterval(timer);
  }, [current?.id, current?.status, notify]);

  const generate = async () => {
    if (!canGenerate) return;
    let parsedWorkflow: Record<string, unknown> | null = null;
    if (workflow.trim()) {
      try {
        parsedWorkflow = JSON.parse(workflow) as Record<string, unknown>;
      } catch {
        notify('工作流 JSON 无效', '高级 ComfyUI 工作流必须是合法 JSON。', 'error');
        return;
      }
    }
    setBusy(true);
    try {
      const job = await api.createVideo({
        prompt: prompt.trim(),
        model: selectedModel?.id ?? 'minimax-h3',
        duration,
        resolution,
        aspect,
        seed: seed.trim() ? Number(seed) : null,
        workflow: parsedWorkflow,
      });
      setCurrent(job);
      setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      notify('已提交视频任务', `${selectedModel?.name ?? 'MiniMax H3'} · ${duration}s`, 'info');
    } catch (err) {
      notify('无法生成视频', errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!current) return;
    try {
      setCurrent(await api.cancelVideo(current.id));
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const remove = async (job: VideoJob) => {
    if (!window.confirm('删除这条视频记录和对应文件？')) return;
    try {
      await api.deleteVideo(job.id);
      setJobs((items) => items.filter((item) => item.id !== job.id));
      if (current?.id === job.id) setCurrent(null);
      notify('视频记录已删除', '', 'info');
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  const comfyModel = selectedModel?.provider === 'comfyui';
  const durationOptions = useMemo(
    () => selectedModel?.durations ?? [6],
    [selectedModel],
  );
  const resolutionOptions = useMemo(
    () => selectedModel?.resolutions ?? ['1080P'],
    [selectedModel],
  );

  return (
    <div className="page videos-page">
      <PageHeader
        eyebrow="VIDEO STUDIO"
        title="视频生成"
        description="用文本生成短视频。MiniMax H3 支持 2K / 15 秒与原生立体声；默认界面不要求理解 ComfyUI 节点图。"
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

      <section className="videos-layout">
        <div className="panel video-composer">
          <div className="images-section-head">
            <div>
              <span className="panel-kicker">SHOT PROMPT</span>
              <h2>描述这一条镜头</h2>
            </div>
            <span className="images-count">{prompt.length} / 4000</span>
          </div>
          <Textarea
            className="videos-prompt"
            value={prompt}
            onChange={(_, data) => setPrompt(data.value.slice(0, 4000))}
            placeholder="例如：镜头穿过雨后的霓虹街道，最后停在一杯咖啡上，电影感…"
            resize="vertical"
          />

          <div className="videos-grid-fields">
            <label className="field">
              <span className="field-label">模型</span>
              <Select value={selectedModel?.id ?? ''} onChange={(_, data) => setModelId(data.value)}>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}{model.available ? '' : ' · 未配置'}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">时长</span>
              <Select value={String(duration)} onChange={(_, data) => setDuration(Number(data.value))}>
                {durationOptions.map((item) => (
                  <option key={item} value={String(item)}>
                    {item} 秒
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">分辨率</span>
              <Select value={resolution} onChange={(_, data) => setResolution(data.value)}>
                {resolutionOptions.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <div className="videos-aspect-row">
            <span className="field-label">画幅</span>
            <div className="ratio-chips">
              {ASPECTS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={aspect === item.id ? 'is-active' : ''}
                  onClick={() => setAspect(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="videos-actions">
            <Button
              appearance="primary"
              size="large"
              className="button-glow"
              icon={busy ? <Spinner size="tiny" /> : <SparkleRegular />}
              onClick={() => void generate()}
              disabled={!canGenerate}
            >
              {busy ? '正在提交…' : '生成视频'}
            </Button>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) && (
              <Button appearance="secondary" icon={<StopRegular />} onClick={() => void cancel()}>
                取消
              </Button>
            )}
          </div>

          <details
            className="images-disclosure"
            open={advancedOpen}
            onToggle={(event) =>
              setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)
            }
          >
            <summary>高级设置</summary>
            <div className="videos-advanced">
              <label className="field">
                <span className="field-label">随机种子</span>
                <Input
                  value={seed}
                  onChange={(_, data) => setSeed(data.value.replace(/[^\d]/g, ''))}
                  placeholder="留空则随机"
                />
              </label>
              {comfyModel && (
                <label className="field field-full">
                  <span className="field-label">ComfyUI 视频 workflow JSON</span>
                  <Textarea
                    className="workflow-editor"
                    value={workflow}
                    onChange={(_, data) => setWorkflow(data.value)}
                    placeholder="需要 SaveVideo / VHS_VideoCombine 节点；支持 {{prompt}}、{{seed}}、{{width}}、{{height}}、{{frames}}、{{fps}} 占位符。"
                    resize="vertical"
                  />
                </label>
              )}
              <div className="inline-note">
                <WarningRegular /> MiniMax H3 使用云端 API，需要设置{' '}
                <code>MINIMAX_API_KEY</code>；ComfyUI 视频需要本地工作流。
                默认界面只显示提示词、时长、分辨率与画幅。
              </div>
            </div>
          </details>

          <div className="videos-engine-note">
            <span>MiniMax：{status?.minimax.configured ? '已配置' : '未配置'} · {status?.minimax.base_url}</span>
            <span>ComfyUI：{status?.comfyui.available ? '已连接' : '未连接'} · {status?.comfyui_url}</span>
          </div>
        </div>

        <aside className="videos-output">
          <div className="panel videos-result-panel">
            <div className="images-section-head">
              <div>
                <span className="panel-kicker">PLAYBACK</span>
                <h2>视频结果</h2>
              </div>
              {current && <StatusPill tone={jobTone(current.status)}>{jobLabel(current.status)}</StatusPill>}
            </div>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) ? (
              <div className="videos-progress">
                <div className="videos-progress-orb">
                  <VideoRegular />
                </div>
                <strong>{current.stage}</strong>
                <span>
                  {current.provider} · {current.duration}s · {current.width}×{current.height}
                </span>
                <div className="images-progress-track">
                  <span style={{ width: `${current.progress}%` }} />
                </div>
                <small>{Math.round(current.progress)}%</small>
              </div>
            ) : current?.status === 'failed' ? (
              <div className="images-failed">
                <WarningRegular />
                <h3>生成失败</h3>
                <p>{current.error}</p>
                <Button appearance="secondary" onClick={() => void generate()}>
                  重试
                </Button>
              </div>
            ) : current?.video_url ? (
              <div className="videos-result">
                <video
                  className="video-player"
                  controls
                  playsInline
                  poster={current.poster_url ? api.url(current.poster_url) : undefined}
                  src={api.url(current.video_url)}
                />
                <div className="videos-result-meta">
                  <span>{current.prompt}</span>
                  <strong>
                    {current.model_id} · {current.provider} · {current.duration}s · {current.resolution}
                  </strong>
                </div>
                {current.warning && <div className="inline-note warning-note">{current.warning}</div>}
                <div className="videos-result-actions">
                  <a
                    className="export-chip"
                    href={api.url(current.video_url)}
                    download={`${current.id}.mp4`}
                  >
                    <ArrowDownloadRegular /> 下载 MP4
                  </a>
                  <button type="button" className="text-link" onClick={() => void remove(current)}>
                    <DeleteRegular /> 删除记录
                  </button>
                </div>
              </div>
            ) : (
              <div className="images-empty">
                <div className="images-empty-orb">
                  <VideoRegular />
                </div>
                <h3>让文字变成镜头</h3>
                <p>
                  输入镜头描述，选择模型、时长与画幅。MiniMax H3 支持原生音频；
                  本地 ComfyUI 工作流只在高级设置中出现。
                </p>
                <div className="images-features">
                  <span>MiniMax H3</span>
                  <span>Hailuo 02</span>
                  <span>ComfyUI</span>
                  <span>MP4</span>
                </div>
              </div>
            )}
          </div>

          <div className="panel videos-history-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">RECENT</span>
                <h3>最近视频</h3>
              </div>
              {loading && <Spinner size="tiny" />}
            </div>
            {jobs.length === 0 ? (
              <EmptyState
                icon={<VideoRegular />}
                title="还没有视频"
                description="生成第一条视频后会显示在这里。"
              />
            ) : (
              <div className="videos-history">
                {jobs.slice(0, 8).map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`videos-history-item${current?.id === job.id ? ' is-active' : ''}`}
                    onClick={() => setCurrent(job)}
                  >
                    <span className="videos-history-thumb">
                      {job.poster_url ? (
                        <img src={api.url(job.poster_url)} alt="" loading="lazy" />
                      ) : (
                        <VideoRegular />
                      )}
                    </span>
                    <span>
                      <strong>{job.prompt || '无提示词'}</strong>
                      <small>
                        {job.status} · {job.duration}s · {formatRelative(job.created_at)}
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
  if (status === 'running') return '生成中';
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
