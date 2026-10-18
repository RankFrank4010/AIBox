import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  Input,
  Select,
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  ArrowUploadRegular,
  BeakerRegular,
  DeleteRegular,
  StopRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type {
  TrainingDataset,
  TrainingJob,
  TrainingStatus,
} from '../api/types';
import { formatBytes, formatRelative } from '../utils/format';

function statusLabel(status: TrainingStatus | null): string {
  if (!status) return '检测中';
  if (status.demo) return '演示训练';
  if (status.command) return '外部训练命令';
  return '未配置运行器';
}

function statusTone(status: TrainingStatus | null) {
  if (!status) return 'neutral' as const;
  if (status.demo) return 'warning' as const;
  if (status.command) return 'success' as const;
  return 'neutral' as const;
}

function jobTone(status: string) {
  if (status === 'completed') return 'success' as const;
  if (status === 'failed') return 'danger' as const;
  if (status === 'cancelled') return 'neutral' as const;
  return 'warning' as const;
}

function jobLabel(status: string) {
  if (status === 'completed') return '已完成';
  if (status === 'running') return '训练中';
  if (status === 'queued') return '排队中';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status;
}

export function TrainingPage() {
  const { system, settings, notify } = useAppData();
  const [status, setStatus] = useState<TrainingStatus | null>(system?.training ?? null);
  const [jobs, setJobs] = useState<TrainingJob[]>(system?.training?.jobs ?? []);
  const [selected, setSelected] = useState<TrainingJob | null>(null);
  const [logs, setLogs] = useState('');
  const [name, setName] = useState('my-finetune');
  const [baseModel, setBaseModel] = useState(
    system?.training?.models?.[0]?.hf_id ?? 'Qwen/Qwen3-8B',
  );
  const [customModel, setCustomModel] = useState('');
  const [method, setMethod] = useState(settings?.training_method ?? 'qlora');
  const [datasetId, setDatasetId] = useState('');
  const [device, setDevice] = useState('auto');
  const [parallel, setParallel] = useState('single');
  const [epochs, setEpochs] = useState(3);
  const [batchSize, setBatchSize] = useState(1);
  const [gradAccum, setGradAccum] = useState(8);
  const [learningRate, setLearningRate] = useState('0.0002');
  const [maxSeq, setMaxSeq] = useState(2048);
  const [loraR, setLoraR] = useState(16);
  const [loraAlpha, setLoraAlpha] = useState(32);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLPreElement>(null);

  const datasets = status?.datasets ?? [];
  const models = status?.models ?? [];
  const methods = status?.methods ?? [];
  const parallelism = status?.parallelism ?? [];
  const selectedDataset = datasets.find((item) => item.id === datasetId) ?? null;
  const effectiveBaseModel = baseModel === 'custom' ? customModel.trim() : baseModel;
  const canCreate =
    Boolean(datasetId && effectiveBaseModel && name.trim()) && !busy;

  const load = async () => {
    setLoading(true);
    try {
      const next = await api.trainingStatus();
      setStatus(next);
      setJobs(next.jobs);
      if (!datasetId && next.datasets.length) setDatasetId(next.datasets[0].id);
      if (!next.methods.some((item) => item.id === method)) {
        setMethod(next.methods[0]?.id ?? 'qlora');
      }
      if (!selected && next.jobs.length) setSelected(next.jobs[0]);
    } catch (err) {
      notify('读取训练任务失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selected || !['queued', 'running', 'cancelling'].includes(selected.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void Promise.all([
        api.trainingJob(selected.id),
        api.trainingLogs(selected.id),
      ])
        .then(([job, log]) => {
          setSelected(job);
          setLogs(log.text);
          setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
          if (job.status === 'completed') {
            notify('训练完成', `${job.name} · ${job.artifacts.length} 个产物`, 'success');
            void load();
          }
          if (job.status === 'failed') {
            notify('训练失败', job.error ?? '请检查训练运行器。', 'error');
          }
        })
        .catch(() => undefined);
    }, 1100);
    return () => window.clearInterval(timer);
  }, [selected?.id, selected?.status, notify]);

  useEffect(() => {
    if (selected?.status === 'completed' || selected?.status === 'failed') {
      void api.trainingLogs(selected.id).then((log) => setLogs(log.text));
    }
    if (selected?.status === 'running') {
      void api.trainingLogs(selected.id).then((log) => setLogs(log.text));
    }
  }, [selected?.id, selected?.status]);

  const uploadDataset = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('name', file.name.replace(/\.[^.]+$/, ''));
      const dataset = await api.uploadTrainingDataset(form);
      notify('数据集已上传', `${dataset.name} · ${dataset.rows} 条`, 'success');
      await load();
      setDatasetId(dataset.id);
    } catch (err) {
      notify('数据集校验失败', errorMessage(err), 'error');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const removeDataset = async (dataset: TrainingDataset) => {
    if (!window.confirm(`删除数据集「${dataset.name}」？`)) return;
    try {
      await api.deleteTrainingDataset(dataset.id);
      setStatus((current) =>
        current
          ? { ...current, datasets: current.datasets.filter((item) => item.id !== dataset.id) }
          : current,
      );
      if (datasetId === dataset.id) setDatasetId('');
      notify('数据集已删除', '', 'info');
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  const create = async () => {
    if (!canCreate) return;
    setBusy(true);
    try {
      const job = await api.createTrainingJob({
        name: name.trim(),
        base_model: effectiveBaseModel,
        method,
        dataset_id: datasetId,
        device,
        parallel_strategy: parallel,
        epochs,
        batch_size: batchSize,
        grad_accum: gradAccum,
        learning_rate: Number(learningRate) || 0.0002,
        max_seq: maxSeq,
        lora_r: loraR,
        lora_alpha: loraAlpha,
      });
      setSelected(job);
      setJobs((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      setLogs('');
      notify('训练任务已创建', `${job.name} · ${method}`, 'info');
    } catch (err) {
      notify('无法创建训练任务', errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!selected) return;
    try {
      setSelected(await api.cancelTrainingJob(selected.id));
    } catch (err) {
      notify('取消失败', errorMessage(err), 'error');
    }
  };

  const removeJob = async (job: TrainingJob) => {
    if (!window.confirm(`删除训练「${job.name}」及其产物？`)) return;
    try {
      await api.deleteTrainingJob(job.id);
      setJobs((items) => items.filter((item) => item.id !== job.id));
      if (selected?.id === job.id) {
        setSelected(null);
        setLogs('');
      }
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  const selectedModel = useMemo(
    () => models.find((item) => item.hf_id === effectiveBaseModel) ?? models[0],
    [models, effectiveBaseModel],
  );

  return (
    <div className="page training-page">
      <PageHeader
        eyebrow="MODEL LAB"
        title="模型微调"
        description="管理微调数据集、LoRA / QLoRA 训练任务与产物。基础模型与训练运行时由你选择，默认界面不暴露脚本细节。"
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

      <section className="training-layout">
        <div className="panel training-config">
          <div className="images-section-head">
            <div>
              <span className="panel-kicker">NEW RUN</span>
              <h2>新建训练</h2>
            </div>
            <span className="images-count">{methods.length} 种方法</span>
          </div>

          <div className="training-fields">
            <label className="field">
              <span className="field-label">任务名称</span>
              <Input value={name} onChange={(_, data) => setName(data.value)} />
            </label>
            <label className="field">
              <span className="field-label">基础模型</span>
              <Select value={baseModel} onChange={(_, data) => setBaseModel(data.value)}>
                {models.map((model) => (
                  <option key={model.id} value={model.hf_id}>
                    {model.name} · {model.parameters} · QLoRA {model.qlora_gb} GB+
                  </option>
                ))}
                <option value="custom">自定义 HF repo（在下方填写）</option>
              </Select>
            </label>
            {baseModel === 'custom' && (
              <label className="field">
                <span className="field-label">Hugging Face repo</span>
                <Input
                  value={customModel}
                  placeholder="org/model-name"
                  onChange={(_, data) => setCustomModel(data.value)}
                />
              </label>
            )}
            <label className="field">
              <span className="field-label">训练方法</span>
              <Select value={method} onChange={(_, data) => setMethod(data.value)}>
                {methods.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.note}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">数据集</span>
              <Select value={datasetId} onChange={(_, data) => setDatasetId(data.value)}>
                <option value="">选择数据集</option>
                {datasets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.rows} 条 · {item.format}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">设备</span>
              <Select value={device} onChange={(_, data) => setDevice(data.value)}>
                <option value="auto">自动</option>
                {(system?.devices.devices ?? [])
                  .filter((item) => item.available)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id} · {item.name}
                    </option>
                  ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">训练并行</span>
              <Select value={parallel} onChange={(_, data) => setParallel(data.value)}>
                {parallelism.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <div className="training-dataset-row">
            <input
              ref={fileRef}
              className="visually-hidden"
              type="file"
              accept=".jsonl,.json,.csv"
              onChange={(event) => void uploadDataset(event.target.files?.[0] ?? null)}
            />
            <Button
              appearance="secondary"
              icon={uploading ? <Spinner size="tiny" /> : <ArrowUploadRegular />}
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
            >
              上传数据集
            </Button>
            <span className="field-hint">
              {selectedDataset
                ? `${selectedDataset.rows} 条 · ${formatBytes(selectedDataset.size_bytes)}`
                : 'JSONL / JSON / CSV；支持 messages、text 或 prompt/completion'}
            </span>
          </div>

          {datasets.length > 0 && (
            <div className="training-datasets">
              {datasets.slice(0, 6).map((item) => (
                <div key={item.id} className="training-dataset">
                  <span>
                    <strong>{item.name}</strong>
                    <small>{item.rows} 条 · {item.format}</small>
                  </span>
                  <button
                    type="button"
                    aria-label={`删除 ${item.name}`}
                    onClick={() => void removeDataset(item)}
                  >
                    <DeleteRegular />
                  </button>
                </div>
              ))}
            </div>
          )}

          <details
            className="images-disclosure"
            open={advanced}
            onToggle={(event) =>
              setAdvanced((event.currentTarget as HTMLDetailsElement).open)
            }
          >
            <summary>高级训练参数</summary>
            <div className="training-advanced">
              <label className="field">
                <span className="field-label">Epochs</span>
                <Input
                  type="number"
                  value={String(epochs)}
                  onChange={(_, data) => setEpochs(Math.max(1, Number(data.value) || 1))}
                />
              </label>
              <label className="field">
                <span className="field-label">Batch size</span>
                <Input
                  type="number"
                  value={String(batchSize)}
                  onChange={(_, data) => setBatchSize(Math.max(1, Number(data.value) || 1))}
                />
              </label>
              <label className="field">
                <span className="field-label">梯度累积</span>
                <Input
                  type="number"
                  value={String(gradAccum)}
                  onChange={(_, data) => setGradAccum(Math.max(1, Number(data.value) || 1))}
                />
              </label>
              <label className="field">
                <span className="field-label">学习率</span>
                <Input
                  value={learningRate}
                  onChange={(_, data) => setLearningRate(data.value)}
                />
              </label>
              <label className="field">
                <span className="field-label">最大序列长度</span>
                <Input
                  type="number"
                  value={String(maxSeq)}
                  onChange={(_, data) => setMaxSeq(Math.max(128, Number(data.value) || 128))}
                />
              </label>
              <label className="field">
                <span className="field-label">LoRA r</span>
                <Input
                  type="number"
                  value={String(loraR)}
                  onChange={(_, data) => setLoraR(Math.max(1, Number(data.value) || 1))}
                />
              </label>
              <label className="field">
                <span className="field-label">LoRA alpha</span>
                <Input
                  type="number"
                  value={String(loraAlpha)}
                  onChange={(_, data) => setLoraAlpha(Math.max(1, Number(data.value) || 1))}
                />
              </label>
            </div>
          </details>

          <div className="training-actions">
            <Button
              appearance="primary"
              size="large"
              className="button-glow"
              icon={busy ? <Spinner size="tiny" /> : <BeakerRegular />}
              disabled={!canCreate}
              onClick={() => void create()}
            >
              {busy ? '正在提交…' : '开始训练'}
            </Button>
            <span className="field-hint">
              {selectedModel
                ? `${selectedModel.name} · QLoRA 约 ${selectedModel.qlora_gb} GB`
                : '自定义模型'}
            </span>
          </div>

          {!status?.demo && !status?.command && (
            <div className="inline-note warning-note">
              <WarningRegular /> 训练运行器未配置。设置{' '}
              <code>AIBOX_TRAIN_COMMAND</code>，或设置{' '}
              <code>AIBOX_DEMO_TRAINING=1</code> 验证流程。
            </div>
          )}
        </div>

        <aside className="training-output">
          <div className="panel training-result-panel">
            <div className="images-section-head">
              <div>
                <span className="panel-kicker">RUN STATUS</span>
                <h2>训练任务</h2>
              </div>
              {selected && (
                <StatusPill tone={jobTone(selected.status)}>
                  {jobLabel(selected.status)}
                </StatusPill>
              )}
            </div>

            {selected && ['queued', 'running', 'cancelling'].includes(selected.status) ? (
              <div className="training-progress">
                <div className="training-progress-orb">
                  <BeakerRegular />
                </div>
                <strong>{selected.stage}</strong>
                <span>{selected.name}</span>
                <div className="images-progress-track">
                  <span style={{ width: `${selected.progress}%` }} />
                </div>
                <small>{Math.round(selected.progress)}%</small>
                <Button appearance="secondary" icon={<StopRegular />} onClick={() => void cancel()}>
                  取消训练
                </Button>
              </div>
            ) : selected?.status === 'failed' ? (
              <div className="images-failed">
                <WarningRegular />
                <h3>训练失败</h3>
                <p>{selected.error}</p>
                <Button appearance="secondary" onClick={() => void removeJob(selected)}>
                  删除记录
                </Button>
              </div>
            ) : selected ? (
              <div className="training-detail">
                <div className="training-detail-head">
                  <div>
                    <strong>{selected.name}</strong>
                    <span>
                      {selected.base_model} · {selected.method} · {selected.device} ·{' '}
                      {selected.parallel_strategy}
                    </span>
                  </div>
                  <Button
                    appearance="subtle"
                    size="small"
                    icon={<DeleteRegular />}
                    onClick={() => void removeJob(selected)}
                  >
                    删除
                  </Button>
                </div>
                <div className="training-meta">
                  <div>
                    <span>数据集</span>
                    <strong>
                      {datasets.find((item) => item.id === selected.dataset_id)?.name ??
                        selected.dataset_id}
                    </strong>
                  </div>
                  <div>
                    <span>Epochs</span>
                    <strong>{String(selected.config.epochs ?? '—')}</strong>
                  </div>
                  <div>
                    <span>产物</span>
                    <strong>{selected.artifacts.length}</strong>
                  </div>
                </div>
                {selected.artifacts.length > 0 && (
                  <div className="training-artifacts">
                    {selected.artifacts.map((item) => (
                      <a
                        key={item.path}
                        className="export-chip"
                        href={api.url(item.url)}
                        download={item.name}
                      >
                        <ArrowDownloadRegular /> {item.name}
                        <small>{formatBytes(item.bytes)}</small>
                      </a>
                    ))}
                  </div>
                )}
                <div className="training-log-head">
                  <span>训练日志</span>
                  <span>{selected.log_url ? '实时' : '—'}</span>
                </div>
                <pre className="training-log" ref={logRef}>
                  {logs || '暂无日志。'}
                </pre>
              </div>
            ) : (
              <div className="images-empty">
                <div className="images-empty-orb">
                  <BeakerRegular />
                </div>
                <h3>管理你的第一条微调</h3>
                <p>
                  上传数据集，选择基础模型与 QLoRA / LoRA 方法，创建训练任务。
                  日志、进度与产物会在这里集中展示。
                </p>
                <div className="images-features">
                  <span>QLoRA</span>
                  <span>LoRA</span>
                  <span>DDP / FSDP</span>
                  <span>产物管理</span>
                </div>
              </div>
            )}
          </div>

          <div className="panel training-history-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">RUNS</span>
                <h3>训练记录</h3>
              </div>
              {loading && <Spinner size="tiny" />}
            </div>
            {jobs.length === 0 ? (
              <EmptyState
                icon={<BeakerRegular />}
                title="还没有训练任务"
                description="上传数据集并创建一个微调任务。"
              />
            ) : (
              <div className="training-history">
                {jobs.slice(0, 10).map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`training-history-item${selected?.id === job.id ? ' is-active' : ''}`}
                    onClick={() => {
                      setSelected(job);
                      setLogs('');
                    }}
                  >
                    <span className={`training-history-dot status-${job.status}`} />
                    <span>
                      <strong>{job.name}</strong>
                      <small>
                        {job.method} · {job.base_model} · {formatRelative(job.created_at)}
                      </small>
                    </span>
                    <span className="training-history-progress">
                      {Math.round(job.progress)}%
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
