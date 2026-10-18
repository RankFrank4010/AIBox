import { Link } from 'react-router-dom';
import { Button } from '@fluentui/react-components';
import {
  ArrowRightRegular,
  ArrowSyncRegular,
  CheckmarkRegular,
  DesktopRegular,
  GaugeRegular,
  PhoneRegular,
  Speaker2Regular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { HardwareIcon } from '../components/HardwareIcon';
import { useAppData } from '../state/AppContext';
import { formatBytes } from '../utils/format';
import { kindLabel } from '../utils/status';

export function SystemPage() {
  const { system, refreshSystem } = useAppData();

  if (!system) {
    return (
      <div className="page system-page">
        <PageHeader eyebrow="SYSTEM & ACCELERATORS" title="硬件与引擎" />
        <div className="panel loading-panel">正在读取硬件信息…</div>
      </div>
    );
  }

  const { platform, cpu, engines, accelerators, npus, storage } = system;
  const engine = engines.asr;
  const runtime = system.runtime;
  const tts = system.tts;
  const modeLabels: Record<string, string> = {
    auto: '自动',
    balanced: '均衡',
    asr_focus: 'ASR 优先',
    tts_focus: 'TTS 优先',
    time_slice: '时间片',
    custom: '自定义',
  };

  const matrix = [
    {
      backend: 'CTranslate2 · CPU',
      device: `${cpu.name} · ${cpu.cores} 线程`,
      status: 'ready',
      statusLabel: '已就绪',
      asr: 'ASR 可用',
      note: 'int8 量化，适合所有平台',
    },
    {
      backend: 'CTranslate2 · CUDA',
      device: system.gpus.find((gpu) => gpu.vendor === 'NVIDIA')?.name ?? '未检测到 NVIDIA GPU',
      status: system.has_cuda ? 'ready' : system.gpus.some((gpu) => gpu.vendor === 'NVIDIA') ? 'warning' : 'muted',
      statusLabel: system.has_cuda
        ? '已就绪'
        : system.gpus.some((gpu) => gpu.vendor === 'NVIDIA')
          ? '运行时缺失'
          : '不可用',
      asr: system.has_cuda ? 'ASR 可用' : '需安装 CUDA 运行时',
      note: 'float16 / int8_float16 加速',
    },
    {
      backend: 'Metal · Apple Silicon',
      device: platform.id === 'macos' ? 'Apple 统一内存 GPU' : '仅 macOS',
      status: platform.id === 'macos' ? 'partial' : 'muted',
      statusLabel: platform.id === 'macos' ? '部分支持' : '不适用',
      asr: platform.id === 'macos' ? '当前使用 CPU 引擎' : '—',
      note: 'Metal Whisper 后端在路线图中',
    },
    {
      backend: 'NPU · OpenVINO / QNN',
      device: npus.length > 0 ? npus.map((npu) => npu.name).join(' / ') : '未检测到 NPU',
      status: npus.length > 0 ? 'warning' : 'muted',
      statusLabel: npus.length > 0 ? '适配中' : '未检测到',
      asr: '暂未启用',
      note: '设备发现与编排已就绪，ASR 加速待接入',
    },
    {
      backend: 'DirectML / ROCm',
      device:
        system.gpus.find((gpu) => ['AMD', 'Intel'].includes(gpu.vendor))?.name ?? '未检测到兼容 GPU',
      status: 'muted',
      statusLabel: '计划中',
      asr: '路线图',
      note: 'Windows / Linux 多厂商加速',
    },
  ];

  return (
    <div className="page system-page">
      <PageHeader
        eyebrow="SYSTEM & ACCELERATORS"
        title="硬件与引擎"
        description="AIBox 自动发现 CPU、GPU 与 NPU，并为 Whisper 选择可用的推理后端。这里展示真实探测结果，而不是假设的能力。"
        actions={
          <Button
            appearance="subtle"
            icon={<ArrowSyncRegular />}
            onClick={() => void refreshSystem()}
          >
            重新检测
          </Button>
        }
      />

      <section className="system-top-grid">
        <article className="panel platform-card">
          <div className="platform-head">
            <div className="platform-icon">
              {platform.id === 'windows' || platform.id === 'macos' ? (
                <DesktopRegular />
              ) : (
                <HardwareIcon kind="cpu" size={26} />
              )}
            </div>
            <div>
              <span className="panel-kicker">HOST MACHINE</span>
              <h2>{platform.label}</h2>
              <p>{platform.hostname}</p>
            </div>
            <StatusPill tone="success">在线</StatusPill>
          </div>
          <div className="platform-specs">
            <div>
              <span>架构</span>
              <strong>{platform.arch}</strong>
            </div>
            <div>
              <span>处理器</span>
              <strong>{cpu.name}</strong>
            </div>
            <div>
              <span>内存</span>
              <strong>{system.memory_gb ? `${system.memory_gb} GB` : '未知'}</strong>
            </div>
            <div>
              <span>Python</span>
              <strong>{platform.python}</strong>
            </div>
          </div>
          <div className="platform-note">{platform.desktop_note}</div>
        </article>

        <article className="panel engine-card">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">ASR ENGINE</span>
              <h3>推理引擎</h3>
            </div>
            <StatusPill tone={engine.installed ? 'success' : 'warning'}>
              {engine.installed ? '已安装' : system.server.demo ? '演示模式' : '未安装'}
            </StatusPill>
          </div>
          <div className="engine-name">
            <div className="engine-logo">fW</div>
            <div>
              <strong>faster-whisper</strong>
              <span>{engine.runtime ?? 'CTranslate2 运行时未检测到'}</span>
            </div>
          </div>
          <div className="engine-facts">
            <div>
              <span>版本</span>
              <strong>{engine.version ?? '—'}</strong>
            </div>
            <div>
              <span>CUDA 设备</span>
              <strong>{engine.cuda_devices}</strong>
            </div>
            <div>
              <span>FFmpeg</span>
              <strong>{engines.media.ready ? '已就绪' : '可选'}</strong>
            </div>
            <div>
              <span>计算类型</span>
              <strong>{engine.compute_types.join(' / ') || '—'}</strong>
            </div>
          </div>
          <div className={`engine-callout${engine.installed ? ' is-ok' : ' is-warn'}`}>
            {engine.installed ? <CheckmarkRegular /> : <WarningRegular />}
            <span>
              {engine.installed
                ? 'Whisper 模型可被加载。首次推理会初始化 CTranslate2，可能需要数秒。'
                : "未安装 faster-whisper。运行 pip install -e 'services/api[asr]' 后重启服务。"}
            </span>
          </div>
        </article>
      </section>

      <section className="runtime-grid">
        <article className="panel runtime-card">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">ELASTIC RUNTIME</span>
              <h3>弹性调度</h3>
            </div>
            <StatusPill tone="brand" dot={false}>
              <GaugeRegular /> {modeLabels[runtime?.mode ?? 'auto'] ?? runtime?.mode}
            </StatusPill>
          </div>
          <div className="runtime-summary">
            <div>
              <span>预算</span>
              <strong>
                {runtime?.budget.used_gb ?? 0} / {runtime?.budget.total_gb ?? '—'} GB
              </strong>
              <small>
                {runtime?.budget.kind === 'vram' ? '显存' : '内存'} · 预留{' '}
                {runtime?.budget.reserve_gb ?? 0} GB
              </small>
            </div>
            <div>
              <span>焦点</span>
              <strong>{runtime?.focus ? modeLabels[runtime.focus] ?? runtime.focus : '动态'}</strong>
              <small>窗口 {runtime?.demand.window_seconds ?? 300}s</small>
            </div>
            <div>
              <span>需求</span>
              <strong>
                ASR {runtime?.demand.asr ?? 0} · TTS {runtime?.demand.tts ?? 0}
              </strong>
              <small>最多常驻 {runtime?.max_loaded_models ?? 2} 个</small>
            </div>
          </div>
          <div className="runtime-budget-bar">
            <span
              style={{
                width: `${
                  runtime?.budget.total_gb
                    ? Math.min(100, (runtime.budget.used_gb / runtime.budget.total_gb) * 100)
                    : 0
                }%`,
              }}
            />
          </div>
          <div className="runtime-loaded">
            {(runtime?.loaded ?? []).length === 0 ? (
              <span className="runtime-empty">当前没有常驻模型</span>
            ) : (
              runtime.loaded.map((item) => (
                <span className={`runtime-chip runtime-${item.kind}`} key={item.kind}>
                  <strong>{item.kind.toUpperCase()}</strong>
                  {item.model_id}
                  <small>{item.estimated_gb} GB{item.busy ? ' · 推理中' : ''}</small>
                </span>
              ))
            )}
          </div>
          <div className="runtime-foot">
            <span>
              {runtime?.evictions.length
                ? `最近换出：${runtime.evictions[0].kind.toUpperCase()} / ${runtime.evictions[0].model_id}`
                : '系统会按需换入换出，避免显存/内存争用'}
            </span>
            <Link to="/settings" className="text-link">
              配置策略 <ArrowRightRegular />
            </Link>
          </div>
        </article>

        <article className="panel tts-engine-card">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">TTS ENGINE</span>
              <h3>IndexTTS</h3>
            </div>
            <StatusPill
              tone={
                tts?.status === 'ready'
                  ? 'success'
                  : tts?.status === 'demo'
                    ? 'warning'
                    : 'neutral'
              }
            >
              {tts?.status === 'ready'
                ? '已就绪'
                : tts?.status === 'demo'
                  ? '演示引擎'
                  : tts?.status === 'runtime-missing'
                    ? '运行时缺失'
                    : tts?.status === 'no-model'
                      ? '缺少模型'
                      : '检测中'}
            </StatusPill>
          </div>
          <div className="tts-engine-hero">
            <div className="engine-logo">
              <Speaker2Regular />
            </div>
            <div>
              <strong>IndexTTS · 本地声音克隆</strong>
              <span>{tts?.runtime_home ?? '尚未配置 AIBOX_INDEXTTS_HOME'}</span>
            </div>
          </div>
          <div className="tts-engine-facts">
            <div>
              <span>已安装</span>
              <strong>{tts?.installed_models.length ?? 0} 个模型</strong>
            </div>
            <div>
              <span>已加载</span>
              <strong>{tts?.loaded_model ?? '—'}</strong>
            </div>
            <div>
              <span>音色</span>
              <strong>{tts?.voice_count ?? 0} 个</strong>
            </div>
            <div>
              <span>格式</span>
              <strong>{(tts?.formats ?? []).join(' / ')}</strong>
            </div>
          </div>
          <div className="runtime-foot">
            <Link to="/tts" className="text-link">
              打开语音合成 <ArrowRightRegular />
            </Link>
            <Link to="/models?kind=tts" className="text-link">
              管理 TTS 模型 <ArrowRightRegular />
            </Link>
          </div>
        </article>
      </section>

      <section className="accelerator-section">
        <div className="section-heading">
          <div>
            <span className="panel-kicker">ACCELERATORS</span>
            <h2>计算设备</h2>
          </div>
          <span className="section-hint">已检测 {accelerators.length} 个设备</span>
        </div>
        <div className="accelerator-grid">
          {accelerators.map((item) => (
            <article className="accelerator-card" key={item.id}>
              <div className={`accelerator-icon accelerator-${item.kind}`}>
                <HardwareIcon kind={item.kind} size={26} />
              </div>
              <div className="accelerator-top">
                <span className="accelerator-kind">{kindLabel(item.kind)}</span>
                <StatusPill
                  tone={item.for_asr ? 'success' : item.status === 'ready' ? 'info' : 'neutral'}
                >
                  {item.for_asr ? 'ASR 可用' : item.status === 'ready' ? '已就绪' : '仅检测'}
                </StatusPill>
              </div>
              <h3>{item.name}</h3>
              <div className="accelerator-meta">
                <span>{item.vendor}</span>
                <span>{item.memory_gb ? `${item.memory_gb} GB` : item.backend}</span>
              </div>
              <p>{item.detail}</p>
              <div className="accelerator-backend">{item.backend}</div>
            </article>
          ))}
          {npus.length === 0 && (
            <article className="accelerator-card accelerator-card-muted">
              <div className="accelerator-icon accelerator-npu">
                <HardwareIcon kind="npu" size={26} />
              </div>
              <div className="accelerator-top">
                <span className="accelerator-kind">NPU</span>
                <StatusPill tone="neutral">未检测到</StatusPill>
              </div>
              <h3>神经网络处理器</h3>
              <div className="accelerator-meta">
                <span>可选设备</span>
              </div>
              <p>连接 Intel / AMD / Qualcomm NPU 设备后，会自动出现在这里。</p>
              <div className="accelerator-backend">OpenVINO / QNN · 适配中</div>
            </article>
          )}
        </div>
      </section>

      <section className="system-lower-grid">
        <article className="panel backend-table-card">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">BACKEND MATRIX</span>
              <h3>加速后端矩阵</h3>
            </div>
          </div>
          <div className="backend-table-wrap">
            <table className="backend-table">
              <thead>
                <tr>
                  <th>后端</th>
                  <th>设备</th>
                  <th>状态</th>
                  <th>ASR</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {matrix.map((row) => (
                  <tr key={row.backend}>
                    <td>
                      <strong>{row.backend}</strong>
                    </td>
                    <td title={row.device}>{row.device}</td>
                    <td>
                      <span className={`matrix-status is-${row.status}`}>
                        <span />
                        {row.statusLabel}
                      </span>
                    </td>
                    <td>{row.asr}</td>
                    <td>{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="panel storage-card">
          <div className="panel-heading">
            <div>
              <span className="panel-kicker">STORAGE</span>
              <h3>本地存储</h3>
            </div>
          </div>
          <div className="storage-meter">
            <div className="storage-numbers">
              <strong>{formatBytes(storage.free_bytes)}</strong>
              <span>可用 / {formatBytes(storage.total_bytes)}</span>
            </div>
            <div className="storage-bar">
              <span
                style={{
                  width:
                    storage.total_bytes && storage.free_bytes != null
                      ? `${((storage.total_bytes - storage.free_bytes) / storage.total_bytes) * 100}%`
                      : '0%',
                }}
              />
            </div>
            <div className="storage-legend">
              <span>模型 {formatBytes(storage.models_bytes)}</span>
              <span>{storage.installed_count} 个模型</span>
            </div>
          </div>
          <div className="path-list">
            <div>
              <span>数据目录</span>
              <strong title={storage.data_dir}>{storage.data_dir}</strong>
            </div>
            <div>
              <span>模型目录</span>
              <strong title={storage.models_dir}>{storage.models_dir}</strong>
            </div>
            <div>
              <span>上传缓存</span>
              <strong title={storage.uploads_dir}>{storage.uploads_dir}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="platform-section">
        <div className="section-heading">
          <div>
            <span className="panel-kicker">SURFACES</span>
            <h2>跨端运行矩阵</h2>
          </div>
          <span className="section-hint">移动端仅为规划，不包含可执行客户端</span>
        </div>
        <div className="surface-grid">
          <article className="surface-card is-current">
            <div className="surface-icon">
              <DesktopRegular />
            </div>
            <div className="surface-head">
              <h3>Windows</h3>
              <StatusPill tone="success">已支持</StatusPill>
            </div>
            <p>Fluent WebUI + 本地桌面壳（Tauri WebView2）。后端以本地服务运行。</p>
            <span className="surface-foot">WebUI · 桌面 UI</span>
          </article>
          <article className="surface-card is-current">
            <div className="surface-icon">
              <DesktopRegular />
            </div>
            <div className="surface-head">
              <h3>macOS</h3>
              <StatusPill tone="success">已支持</StatusPill>
            </div>
            <p>Fluent WebUI + 本地桌面壳（Tauri WKWebView）。Apple Silicon 使用统一内存。</p>
            <span className="surface-foot">WebUI · 桌面 UI</span>
          </article>
          <article className="surface-card">
            <div className="surface-icon">
              <HardwareIcon kind="cpu" size={24} />
            </div>
            <div className="surface-head">
              <h3>Linux / Server</h3>
              <StatusPill tone="info">仅 WebUI</StatusPill>
            </div>
            <p>浏览器访问 Fluent WebUI，可部署在服务器并通过反向代理暴露安全入口。</p>
            <span className="surface-foot">WebUI · Docker</span>
          </article>
          <article className="surface-card is-planned">
            <div className="surface-icon">
              <PhoneRegular />
            </div>
            <div className="surface-head">
              <h3>Android</h3>
              <StatusPill tone="neutral">规划中</StatusPill>
            </div>
            <p>复用 Fluent WebUI，通过原生桥接调度 NNAPI / QNN 与前台下载服务。</p>
            <span className="surface-foot">不包含执行代码</span>
          </article>
          <article className="surface-card is-planned">
            <div className="surface-icon">
              <PhoneRegular />
            </div>
            <div className="surface-head">
              <h3>iOS</h3>
              <StatusPill tone="neutral">规划中</StatusPill>
            </div>
            <p>Core ML / ANE 推理、后台任务与模型下载策略设计阶段。</p>
            <span className="surface-foot">不包含执行代码</span>
          </article>
        </div>
      </section>

      <div className="system-disclaimer">
        <WarningRegular />
        <span>
          硬件探测是“尽力而为”的结果。CUDA 就绪代表 CTranslate2 能枚举到设备；NPU
          与 Metal 的 Whisper 加速尚未接入，不会在转写时被错误地选中。
        </span>
      </div>
    </div>
  );
}
