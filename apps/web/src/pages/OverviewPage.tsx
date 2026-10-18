import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, ProgressBar } from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowRightRegular,
  ArrowSyncRegular,
  CheckmarkRegular,
  DocumentTextRegular,
  MicRegular,
  SparkleRegular,
  Speaker2Regular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { HardwareIcon } from '../components/HardwareIcon';
import { AudioOrb } from '../components/Waveform';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { TranscriptionRecord } from '../api/types';
import {
  formatBytes,
  formatDuration,
  formatRelative,
  languageLabel,
} from '../utils/format';
import { transcriptionLabel, transcriptionTone } from '../utils/status';

export function OverviewPage() {
  const { system, models, loading, refreshModels, refreshSystem, notify } = useAppData();
  const navigate = useNavigate();
  const [history, setHistory] = useState<TranscriptionRecord[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [busyModel, setBusyModel] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const data = await api.transcriptions(8);
      setHistory(data.items);
    } catch {
      // The connection banner already explains backend failures.
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    const timer = window.setInterval(() => void loadHistory(), 8_000);
    return () => window.clearInterval(timer);
  }, [loadHistory]);

  const recommendedId = system?.models.recommended_id ?? 'small';
  const recommendedModel = useMemo(
    () => models?.catalog.find((model) => model.id === recommendedId) ?? null,
    [models, recommendedId],
  );
  const recommendedDownload = models?.downloads.find(
    (task) =>
      task.model_id === recommendedId &&
      ['queued', 'downloading', 'cancelling'].includes(task.status),
  );
  const primaryGpu = system?.accelerators.find((item) => item.kind === 'gpu');
  const cpu = system?.accelerators.find((item) => item.kind === 'cpu');
  const npu = system?.accelerators.find((item) => item.kind === 'npu');
  const installedCount = system?.models.installed_count ?? 0;
  const engineReady = Boolean(system?.engines.asr.installed || system?.server.demo);
  const freeStorage = system?.storage.free_bytes;

  const startRecommendedDownload = async () => {
    if (!recommendedModel || busyModel) return;
    setBusyModel(recommendedModel.id);
    try {
      await api.startDownload(recommendedModel.id);
      notify('已加入下载队列', `${recommendedModel.name} 正在从 Hugging Face 下载。`, 'info');
      await refreshModels();
    } catch (err) {
      notify('无法开始下载', errorMessage(err), 'error');
    } finally {
      setBusyModel(null);
    }
  };

  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 6) return '夜深了';
    if (hour < 12) return '早上好';
    if (hour < 18) return '下午好';
    return '晚上好';
  }, []);

  return (
    <div className="page overview-page">
      <PageHeader
        eyebrow="LOCAL AI WORKSPACE"
        title={
          <>
            {greeting}，让每一段声音，
            <span className="gradient-text">在本地成为文字。</span>
          </>
        }
        description="AIBox 在你的设备上运行 Whisper 与 IndexTTS。下载一次模型，即可离线完成转写、字幕、声音克隆与语音合成，音频不会离开本机。"
        actions={
          <>
            <Button
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={() => void Promise.all([refreshSystem(), refreshModels()])}
            >
              刷新状态
            </Button>
            <Button
              appearance="subtle"
              icon={<Speaker2Regular />}
              onClick={() => navigate('/tts')}
            >
              语音合成
            </Button>
            <Button
              appearance="primary"
              icon={<MicRegular />}
              className="button-glow"
              onClick={() => navigate('/transcribe')}
            >
              开始转写
            </Button>
          </>
        }
      />

      <section className="overview-hero-grid">
        <article className="hero-card">
          <div className="hero-content">
            <div className="hero-badges">
              <StatusPill tone={engineReady ? 'success' : 'warning'}>
                {engineReady ? 'ASR 引擎就绪' : 'ASR 引擎待安装'}
              </StatusPill>
              <StatusPill tone="brand" dot={false}>
                {system?.engines.asr.runtime ?? 'CTranslate2'}
              </StatusPill>
              <StatusPill tone="neutral" dot={false}>
                100% 本地
              </StatusPill>
            </div>
            <h2 className="hero-title">
              声音进来，
              <br />
              <span>字幕出去。</span>
            </h2>
            <p className="hero-copy">
              从 Whisper Tiny 到 Large v3 Turbo，为你的显卡、NPU 与 CPU
              自动匹配最合适的模型。下载、加载、转写，一个工作台完成。
            </p>
            <div className="hero-actions">
              <Button
                appearance="primary"
                size="large"
                icon={<MicRegular />}
                className="button-glow"
                onClick={() => navigate('/transcribe')}
              >
                打开转写工作台
              </Button>
              <Button
                appearance="secondary"
                size="large"
                icon={<ArrowDownloadRegular />}
                onClick={() => navigate('/models')}
              >
                浏览模型库
              </Button>
            </div>
            <div className="hero-footnote">
              <span>
                <CheckmarkRegular /> GPU / NPU / CPU 自动检测
              </span>
              <span>
                <CheckmarkRegular /> SRT · VTT · TXT · JSON
              </span>
            </div>
          </div>
          <div className="hero-visual">
            <AudioOrb active={engineReady} />
          </div>
          <div className="hero-noise" aria-hidden="true" />
        </article>

        <aside className="hardware-snapshot panel">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">COMPUTE</span>
              <h3>本机算力</h3>
            </div>
            <StatusPill tone={system?.has_cuda ? 'success' : 'info'} dot>
              {system?.has_cuda ? 'CUDA 就绪' : 'CPU 模式'}
            </StatusPill>
          </div>

          <div className="device-stack">
            <div className="device-row">
              <div className="device-symbol device-gpu">
                <HardwareIcon kind="gpu" size={22} />
              </div>
              <div className="device-row-body">
                <span>图形处理器</span>
                <strong>{primaryGpu?.name ?? '未检测到独立 GPU'}</strong>
                <small>
                  {primaryGpu
                    ? `${primaryGpu.vendor} · ${primaryGpu.memory_gb ? `${primaryGpu.memory_gb} GB 显存` : primaryGpu.backend}`
                    : '将使用 CPU 进行推理'}
                </small>
              </div>
              <span className={`device-state ${primaryGpu?.for_asr ? 'is-ready' : ''}`}>
                {primaryGpu?.for_asr ? '可用' : primaryGpu ? '已识别' : '—'}
              </span>
            </div>

            <div className="device-row">
              <div className="device-symbol device-cpu">
                <HardwareIcon kind="cpu" size={22} />
              </div>
              <div className="device-row-body">
                <span>处理器</span>
                <strong>{cpu?.name ?? '正在读取 CPU 信息'}</strong>
                <small>
                  {system?.cpu.cores ?? '—'} 线程 ·{' '}
                  {system?.memory_gb ? `${system.memory_gb} GB 内存` : '内存未知'}
                </small>
              </div>
              <span className="device-state is-ready">可用</span>
            </div>

            <div className="device-row">
              <div className="device-symbol device-npu">
                <HardwareIcon kind="npu" size={22} />
              </div>
              <div className="device-row-body">
                <span>神经网络处理器</span>
                <strong>{npu?.name ?? '未检测到 NPU'}</strong>
                <small>{npu ? npu.detail : '当前设备将以 CPU / GPU 运行 ASR'}</small>
              </div>
              <span className={`device-state ${npu ? 'is-detected' : ''}`}>
                {npu ? '适配中' : '—'}
              </span>
            </div>
          </div>

          <div className="snapshot-footer">
            <div>
              <span>平台</span>
              <strong>{system?.platform.label ?? '检测中'}</strong>
            </div>
            <div>
              <span>可用存储</span>
              <strong>{freeStorage ? formatBytes(freeStorage) : '—'}</strong>
            </div>
            <button type="button" onClick={() => navigate('/system')} className="text-link">
              详情 <ArrowRightRegular />
            </button>
          </div>
        </aside>
      </section>

      <section className="stat-grid">
        <button type="button" className="stat-card" onClick={() => navigate('/models')}>
          <div className="stat-icon stat-icon-violet">
            <SparkleRegular />
          </div>
          <div>
            <span className="stat-label">已安装模型</span>
            <strong className="stat-value">
              {loading ? '—' : installedCount}
              <small> / {models?.catalog.length ?? 7}</small>
            </strong>
            <span className="stat-note">
              {installedCount > 0 ? '可随时切换与删除' : '前往模型库下载第一个模型'}
            </span>
          </div>
        </button>
        <button type="button" className="stat-card" onClick={() => navigate('/system')}>
          <div className="stat-icon stat-icon-cyan">
            <HardwareIcon kind={primaryGpu ? 'gpu' : 'cpu'} size={22} />
          </div>
          <div>
            <span className="stat-label">推理后端</span>
            <strong className="stat-value stat-value-text">
              {system?.has_cuda ? 'CUDA' : 'CPU'}
              <small>{system?.has_cuda ? ' / float16' : ' / int8'}</small>
            </strong>
            <span className="stat-note">
              {system?.engines.asr.version
                ? `faster-whisper ${system.engines.asr.version}`
                : '引擎尚未安装'}
            </span>
          </div>
        </button>
        <button type="button" className="stat-card" onClick={() => navigate('/transcribe')}>
          <div className="stat-icon stat-icon-mint">
            <DocumentTextRegular />
          </div>
          <div>
            <span className="stat-label">最近转写</span>
            <strong className="stat-value">
              {historyLoading ? '—' : history.length}
              <small> 条</small>
            </strong>
            <span className="stat-note">
              {history[0]?.status === 'completed'
                ? `最近完成于 ${formatRelative(history[0].created_at)}`
                : '所有记录保存在本机'}
            </span>
          </div>
        </button>
        <button type="button" className="stat-card" onClick={() => navigate('/system')}>
          <div className="stat-icon stat-icon-amber">
            <HardwareIcon kind="npu" size={22} />
          </div>
          <div>
            <span className="stat-label">加速能力</span>
            <strong className="stat-value stat-value-text">
              {system?.has_cuda ? 'GPU' : 'CPU'}
              <small>{npu ? ' + NPU' : ''}</small>
            </strong>
            <span className="stat-note">
              {npu ? 'NPU 驱动已识别 · ASR 适配中' : 'Whisper 将使用 CPU / CUDA'}
            </span>
          </div>
        </button>
      </section>

      <section className="overview-bottom-grid">
        <article className="panel recent-panel">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">RECENT</span>
              <h3>最近转写</h3>
            </div>
            <button type="button" className="text-link" onClick={() => navigate('/transcribe')}>
              打开工作台 <ArrowRightRegular />
            </button>
          </div>

          {history.length === 0 ? (
            <EmptyState
              compact
              icon={<MicRegular />}
              title={historyLoading ? '正在读取记录…' : '还没有转写记录'}
              description="选择一个已安装的 Whisper 模型，拖入音频即可开始。"
              action={
                <Button
                  appearance="primary"
                  icon={<MicRegular />}
                  onClick={() => navigate('/transcribe')}
                >
                  开始第一次转写
                </Button>
              }
            />
          ) : (
            <div className="recent-list">
              {history.slice(0, 5).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="recent-row"
                  onClick={() => navigate(`/transcribe?job=${item.id}`)}
                >
                  <span className="recent-file-icon">
                    <DocumentTextRegular />
                  </span>
                  <span className="recent-main">
                    <strong title={item.filename}>{item.filename}</strong>
                    <span>
                      {item.model_id} · {languageLabel(item.detected_language ?? item.language)} ·{' '}
                      {formatDuration(item.duration)}
                    </span>
                  </span>
                  <span className="recent-meta">
                    <StatusPill tone={transcriptionTone(item.status)}>
                      {transcriptionLabel(item.status)}
                    </StatusPill>
                    <small>{formatRelative(item.created_at)}</small>
                  </span>
                  <ArrowRightRegular className="recent-arrow" />
                </button>
              ))}
            </div>
          )}
        </article>

        <div className="overview-side">
          <article className="panel recommend-panel">
            <div className="recommend-top">
              <span className="panel-kicker">RECOMMENDED</span>
              <StatusPill tone="brand" dot={false}>
                为你推荐
              </StatusPill>
            </div>
            <div className="recommend-model-head">
              <div className="model-glyph">
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
              <div>
                <h3>{recommendedModel?.name ?? 'Whisper Small'}</h3>
                <p>{recommendedModel?.best_for ?? 'CPU 高质量转写'}</p>
              </div>
            </div>
            <p className="recommend-description">
              {recommendedModel?.description ?? '正在根据硬件生成推荐。'}
            </p>
            <div className="recommend-meta">
              <span>
                <small>体积</small>
                <strong>{recommendedModel?.size_label ?? '484 MB'}</strong>
              </span>
              <span>
                <small>语言</small>
                <strong>{recommendedModel?.languages ?? '99 种'}</strong>
              </span>
              <span>
                <small>内存</small>
                <strong>{recommendedModel?.memory_gb ?? 3} GB</strong>
              </span>
            </div>
            {recommendedDownload ? (
              <div className="recommend-downloading">
                <div>
                  <span>正在下载 {recommendedModel?.name}</span>
                  <strong>{Math.round(recommendedDownload.progress)}%</strong>
                </div>
                <ProgressBar value={recommendedDownload.progress / 100} thickness="medium" />
                <button type="button" className="text-link" onClick={() => navigate('/models')}>
                  查看下载队列 <ArrowRightRegular />
                </button>
              </div>
            ) : recommendedModel?.installed ? (
              <Button
                appearance="primary"
                icon={<MicRegular />}
                onClick={() => navigate('/transcribe')}
                className="recommend-action"
              >
                使用此模型转写
              </Button>
            ) : (
              <Button
                appearance="primary"
                icon={<ArrowDownloadRegular />}
                onClick={() => void startRecommendedDownload()}
                disabled={!recommendedModel || busyModel !== null}
                className="recommend-action"
              >
                {busyModel ? '正在创建下载…' : '下载推荐模型'}
              </Button>
            )}
            <span className="recommend-reason">{system?.recommendation.reason}</span>
          </article>

          <article className="privacy-card">
            <div className="privacy-icon">
              <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
                <path d="M12 2.7 4.6 5.5v5.4c0 4.6 3.1 8.9 7.4 10.4 4.3-1.5 7.4-5.8 7.4-10.4V5.5L12 2.7Z" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="m8.7 11.8 2.2 2.2 4.4-4.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <div>
              <strong>音频不离开设备</strong>
              <p>模型下载完成后，转写全程在本地完成。没有云端上传，没有隐藏额度。</p>
            </div>
          </article>
        </div>
      </section>
    </div>
  );
}
