import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Input,
  Select,
  Slider,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  DeleteRegular,
  ImageRegular,
  SettingsRegular,
  SparkleRegular,
  StopRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { ImageJob, ImageStatus } from '../api/types';
import { formatRelative } from '../utils/format';

const RATIOS = [
  { id: '1:1', label: '方形', width: 1024, height: 1024 },
  { id: '4:3', label: '横向 4:3', width: 1152, height: 896 },
  { id: '3:4', label: '纵向 3:4', width: 896, height: 1152 },
  { id: '16:9', label: '宽屏 16:9', width: 1344, height: 768 },
  { id: '9:16', label: '竖屏 9:16', width: 768, height: 1344 },
] as const;

function engineLabel(status: ImageStatus | null): string {
  if (!status) return '检测中';
  if (status.demo) return '演示引擎';
  if (status.comfyui.available) return 'ComfyUI';
  if (status.diffusers.runtime_ready) return '本地 Diffusers';
  return '引擎未配置';
}

function engineTone(status: ImageStatus | null) {
  if (!status) return 'neutral' as const;
  if (status.demo) return 'warning' as const;
  if (status.comfyui.available || status.diffusers.runtime_ready) return 'success' as const;
  return 'neutral' as const;
}

export function ImagesPage() {
  const { system, models, settings, notify } = useAppData();
  const navigate = useNavigate();
  const imageModels = useMemo(
    () => (models?.catalog ?? []).filter((model) => model.kind === 'image'),
    [models],
  );
  const installedModels = useMemo(
    () => (models?.installed ?? []).filter((model) => model.kind === 'image'),
    [models],
  );
  const [status, setStatus] = useState<ImageStatus | null>(system?.image ?? null);
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [current, setCurrent] = useState<ImageJob | null>(null);
  const [prompt, setPrompt] = useState(
    '一座漂浮在云海上的未来图书馆，清晨金色光线，电影感构图，细节丰富',
  );
  const [negative, setNegative] = useState('');
  const [negativeOpen, setNegativeOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [modelId, setModelId] = useState('');
  const [provider, setProvider] = useState(settings?.image_provider || 'auto');
  const [ratio, setRatio] = useState<(typeof RATIOS)[number]['id']>('1:1');
  const [steps, setSteps] = useState(settings?.image_steps ?? 28);
  const [guidance, setGuidance] = useState(settings?.image_guidance ?? 3.5);
  const [seed, setSeed] = useState('');
  const [batch, setBatch] = useState(1);
  const [workflow, setWorkflow] = useState('');
  const [checkpoint, setCheckpoint] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const selectedRatio = RATIOS.find((item) => item.id === ratio) ?? RATIOS[0];
  const selectedModel = imageModels.find((item) => item.id === modelId) ?? imageModels[0];
  const sizeScale =
    selectedModel?.default_width && selectedModel.default_width < 768
      ? selectedModel.default_width / 1024
      : 1;
  const targetWidth = Math.round(selectedRatio.width * sizeScale);
  const targetHeight = Math.round(selectedRatio.height * sizeScale);
  const canGenerate = prompt.trim().length > 0 && !busy;
  const comfyAdvanced =
    provider === 'comfyui' || (provider === 'auto' && status?.comfyui.available);

  const load = async () => {
    setLoading(true);
    try {
      const [nextStatus, history] = await Promise.all([
        api.imageStatus(),
        api.images(24),
      ]);
      setStatus(nextStatus);
      setJobs(history.items);
      if (!current && history.items.length > 0) {
        setCurrent(history.items[0]);
      }
    } catch (err) {
      notify('读取图像引擎失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!modelId && imageModels.length > 0) {
      const preferred =
        settings?.default_image_model &&
        imageModels.some((item) => item.id === settings.default_image_model)
          ? settings.default_image_model
          : imageModels.find((item) => item.installed)?.id ?? imageModels[0].id;
      setModelId(preferred);
    }
  }, [imageModels, settings, modelId]);

  useEffect(() => {
    if (!current || !['queued', 'running', 'cancelling'].includes(current.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void api
        .imageJob(current.id)
        .then((job) => {
          setCurrent(job);
          setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
          if (job.status === 'completed') {
            notify('图像生成完成', `${job.width}×${job.height} · ${job.provider}`, 'success');
          }
          if (job.status === 'failed') {
            notify('图像生成失败', job.error ?? '请检查图像引擎配置。', 'error');
          }
        })
        .catch(() => undefined);
    }, 800);
    return () => window.clearInterval(timer);
  }, [current?.id, current?.status, notify]);

  const generate = async () => {
    if (!canGenerate) return;
    setBusy(true);
    let parsedWorkflow: Record<string, unknown> | null = null;
    if (workflow.trim()) {
      try {
        parsedWorkflow = JSON.parse(workflow) as Record<string, unknown>;
      } catch {
        notify('工作流 JSON 无效', '高级 ComfyUI 工作流必须是合法 JSON。', 'error');
        setBusy(false);
        return;
      }
    }
    try {
      const job = await api.generateImage({
        prompt: prompt.trim(),
        negative_prompt: negative.trim(),
        model: selectedModel?.id ?? null,
        provider,
        width: targetWidth,
        height: targetHeight,
        steps,
        guidance_scale: guidance,
        seed: seed.trim() ? Number(seed) : null,
        batch,
        workflow: parsedWorkflow,
        checkpoint: checkpoint.trim() || null,
      });
      setCurrent(job);
      setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      notify('已提交图像任务', `${selectedModel?.name ?? '默认模型'} · ${selectedRatio.label}`, 'info');
    } catch (err) {
      notify('无法生成图像', errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!current) return;
    try {
      setCurrent(await api.cancelImage(current.id));
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const remove = async (job: ImageJob) => {
    if (!window.confirm('删除这条图像记录和对应文件？')) return;
    try {
      await api.deleteImage(job.id);
      setJobs((items) => items.filter((item) => item.id !== job.id));
      if (current?.id === job.id) setCurrent(null);
      notify('图像记录已删除', '', 'info');
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  const downloadAll = () => {
    current?.image_urls.forEach((url, index) => {
      const anchor = document.createElement('a');
      anchor.href = api.url(url);
      anchor.download = `${current.id}-${index + 1}.png`;
      anchor.click();
    });
  };

  return (
    <div className="page images-page">
      <PageHeader
        eyebrow="IMAGE STUDIO"
        title="图像生成"
        description="输入提示词即可生成图片。默认隐藏 ComfyUI 节点图与复杂参数；需要精细控制时再打开高级设置。"
        actions={
          <>
            <StatusPill tone={engineTone(status)}>{engineLabel(status)}</StatusPill>
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

      <section className="images-layout">
        <div className="panel images-composer">
          <div className="images-section-head">
            <div>
              <span className="panel-kicker">PROMPT</span>
              <h2>描述你想要的画面</h2>
            </div>
            <span className="images-count">{prompt.length} / 4000</span>
          </div>
          <Textarea
            className="images-prompt"
            value={prompt}
            onChange={(_, data) => setPrompt(data.value.slice(0, 4000))}
            placeholder="例如：雨夜的东京街头，霓虹灯，电影感，35mm 胶片…"
            resize="vertical"
          />

          <div className="images-ratio-row">
            <span className="field-label">画面比例</span>
            <div className="ratio-chips">
              {RATIOS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={ratio === item.id ? 'is-active' : ''}
                  onClick={() => setRatio(item.id)}
                >
                  <span className={`ratio-shape ratio-${item.id.replace(':', '-')}`} />
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="images-grid-fields">
            <label className="field">
              <span className="field-label">模型</span>
              <Select
                value={selectedModel?.id ?? ''}
                onChange={(_, data) => setModelId(data.value)}
              >
                {imageModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} {model.installed ? '' : '· 未安装'}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">引擎</span>
              <Select value={provider} onChange={(_, data) => setProvider(data.value)}>
                <option value="auto">自动选择</option>
                <option value="comfyui" disabled={!status?.comfyui.available}>
                  ComfyUI{status?.comfyui.available ? '' : '（不可达）'}
                </option>
                <option value="diffusers" disabled={!status?.diffusers.runtime_ready}>
                  本地 Diffusers{status?.diffusers.runtime_ready ? '' : '（未配置）'}
                </option>
                <option value="demo" disabled={!status?.demo}>
                  演示引擎{status?.demo ? '' : '（未启用）'}
                </option>
              </Select>
            </label>
            <label className="field">
              <span className="field-label">数量</span>
              <Select
                value={String(batch)}
                onChange={(_, data) => setBatch(Number(data.value))}
              >
                {[1, 2, 3, 4].map((value) => (
                  <option key={value} value={String(value)}>
                    {value} 张
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <div className="images-actions">
            <Button
              appearance="primary"
              size="large"
              className="button-glow"
              icon={busy ? <Spinner size="tiny" /> : <SparkleRegular />}
              onClick={() => void generate()}
              disabled={!canGenerate}
            >
              {busy ? '正在提交…' : '生成图片'}
            </Button>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) && (
              <Button appearance="secondary" icon={<StopRegular />} onClick={() => void cancel()}>
                取消
              </Button>
            )}
            {installedModels.length === 0 && (
              <Button
                appearance="secondary"
                icon={<ImageRegular />}
                onClick={() => navigate('/models?kind=image')}
              >
                下载图像模型
              </Button>
            )}
          </div>

          <details
            className="images-disclosure"
            open={negativeOpen}
            onToggle={(event) =>
              setNegativeOpen((event.currentTarget as HTMLDetailsElement).open)
            }
          >
            <summary>负向提示词（可选）</summary>
            <Textarea
              value={negative}
              onChange={(_, data) => setNegative(data.value)}
              placeholder="不希望出现的元素、风格或质量问题"
              resize="vertical"
            />
          </details>

          <details
            className="images-disclosure"
            open={advancedOpen}
            onToggle={(event) =>
              setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)
            }
          >
            <summary>
              <SettingsRegular /> 高级设置
            </summary>
            <div className="images-advanced">
              <label className="field">
                <span className="field-label">
                  推理步数 <strong className="field-value">{steps}</strong>
                </span>
                <Slider
                  min={1}
                  max={60}
                  step={1}
                  value={steps}
                  onChange={(_, data) => setSteps(data.value)}
                />
              </label>
              <label className="field">
                <span className="field-label">
                  CFG / 引导强度 <strong className="field-value">{guidance.toFixed(1)}</strong>
                </span>
                <Slider
                  min={0}
                  max={12}
                  step={0.5}
                  value={guidance}
                  onChange={(_, data) => setGuidance(data.value)}
                />
              </label>
              <label className="field">
                <span className="field-label">随机种子</span>
                <Input
                  value={seed}
                  onChange={(_, data) => setSeed(data.value.replace(/[^\d]/g, ''))}
                  placeholder="留空则随机"
                />
              </label>
              {comfyAdvanced && (
                <>
                  <label className="field">
                    <span className="field-label">ComfyUI checkpoint</span>
                    <Input
                      value={checkpoint}
                      onChange={(_, data) => setCheckpoint(data.value)}
                      placeholder={selectedModel?.comfyui_checkpoint ?? '模型文件名'}
                    />
                  </label>
                  <label className="field field-full">
                    <span className="field-label">自定义 ComfyUI 工作流 JSON</span>
                    <Textarea
                      className="workflow-editor"
                      value={workflow}
                      onChange={(_, data) => setWorkflow(data.value)}
                      placeholder="通常不需要填写。模板支持 {{prompt}}、{{seed}}、{{width}} 等占位符。"
                      resize="vertical"
                    />
                    <span className="field-hint">
                      只有在你需要自定义节点图时才使用；默认会使用内置 checkpoint 工作流。
                    </span>
                  </label>
                </>
              )}
              <div className="inline-note">
                <WarningRegular /> SD 1.5 建议 512–768；SDXL 建议 1024；FLUX/Qwen-Image
                需要更高显存。默认参数已按模型隐藏，只有需要复现或微调时再改。
              </div>
            </div>
          </details>

          <div className="images-engine-note">
            <span>
              输出 {targetWidth}×{targetHeight}
            </span>
            <span>
              ComfyUI：{status?.comfyui.available ? '已连接' : '未连接'} ·{' '}
              {status?.comfyui_url ?? 'http://127.0.0.1:8188'}
            </span>
            <span>
              本地 Diffusers：{status?.diffusers.runtime_ready ? '就绪' : '未配置'} ·{' '}
              {status?.diffusers.python ?? '—'}
            </span>
          </div>
        </div>

        <aside className="images-output">
          <div className="panel images-result-panel">
            <div className="images-section-head">
              <div>
                <span className="panel-kicker">CANVAS</span>
                <h2>生成结果</h2>
              </div>
              {current && <StatusPill tone={jobTone(current.status)}>{jobLabel(current.status)}</StatusPill>}
            </div>
            {current && ['queued', 'running', 'cancelling'].includes(current.status) ? (
              <div className="images-progress">
                <div className="images-progress-orb">
                  <WaveformMini />
                </div>
                <strong>{current.stage}</strong>
                <span>
                  {current.provider} · {current.width}×{current.height} · {current.steps} steps
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
            ) : current?.image_urls.length ? (
              <div className="images-result">
                <div className="images-result-grid">
                  {current.image_urls.map((url, index) => (
                    <a
                      key={url}
                      href={api.url(url)}
                      target="_blank"
                      rel="noreferrer"
                      className={`images-result-item${current.image_urls.length === 1 ? ' is-single' : ''}`}
                    >
                      <img src={api.url(url)} alt={`生成结果 ${index + 1}`} loading="lazy" />
                    </a>
                  ))}
                </div>
                <div className="images-result-meta">
                  <span>{current.prompt}</span>
                  <strong>
                    {current.model_id} · {current.provider} · seed {current.seed ?? '—'}
                  </strong>
                </div>
                {current.warning && <div className="inline-note warning-note">{current.warning}</div>}
                <div className="images-result-actions">
                  <Button
                    appearance="secondary"
                    size="small"
                    icon={<ArrowDownloadRegular />}
                    onClick={downloadAll}
                  >
                    下载全部
                  </Button>
                  <button type="button" className="text-link" onClick={() => void remove(current)}>
                    <DeleteRegular /> 删除记录
                  </button>
                </div>
              </div>
            ) : (
              <div className="images-empty">
                <div className="images-empty-orb">
                  <ImageRegular />
                </div>
                <h3>让提示词变成画面</h3>
                <p>
                  输入描述、选择比例，然后生成。默认不显示节点图；需要 ComfyUI
                  精细控制时再打开高级设置。
                </p>
                <div className="images-features">
                  <span>SD / SDXL</span>
                  <span>FLUX</span>
                  <span>Qwen-Image</span>
                  <span>ComfyUI</span>
                </div>
              </div>
            )}
          </div>

          <div className="panel images-history-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">RECENT</span>
                <h3>最近生成</h3>
              </div>
              {loading && <Spinner size="tiny" />}
            </div>
            {jobs.length === 0 ? (
              <EmptyState
                icon={<ImageRegular />}
                title="还没有图像"
                description="生成第一张图片后会显示在这里。"
              />
            ) : (
              <div className="images-history">
                {jobs.slice(0, 12).map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`images-history-item${current?.id === job.id ? ' is-active' : ''}`}
                    onClick={() => setCurrent(job)}
                  >
                    <span className="images-history-thumb">
                      {job.preview_url ? (
                        <img src={api.url(job.preview_url)} alt="" loading="lazy" />
                      ) : (
                        <ImageRegular />
                      )}
                    </span>
                    <span className="images-history-copy">
                      <strong>{job.prompt || '无提示词'}</strong>
                      <small>
                        {job.status} · {job.width}×{job.height} · {formatRelative(job.created_at)}
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

function WaveformMini() {
  return (
    <div className="waveform compact" aria-hidden="true">
      {Array.from({ length: 18 }, (_, index) => (
        <span
          key={index}
          style={{ height: `${18 + ((index * 37) % 42)}%` }}
        />
      ))}
    </div>
  );
}
