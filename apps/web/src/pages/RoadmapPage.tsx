import {
  ArrowRightRegular,
  CheckmarkRegular,
  DesktopRegular,
  PhoneRegular,
  RocketRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { HardwareIcon } from '../components/HardwareIcon';

const PHASES = [
  {
    version: 'v0.1',
    title: '桌面、Web 与服务器',
    status: 'current',
    statusLabel: '当前版本',
    items: [
      'Fluent WebUI 全平台可用',
      'Windows / macOS Tauri 桌面壳',
      'Whisper + IndexTTS 模型目录与下载',
      'faster-whisper CPU / CUDA 转写',
      'OpenAI ASR / TTS、WebSocket、gRPC、MRCP',
      'ASR + TTS 多模型驻留与弹性调度',
      '社区适配器与 16 个主流模型配方',
      'SRT / VTT / TXT / JSON 与音频导出',
    ],
  },
  {
    version: 'v0.2',
    title: '加速后端与多模型族',
    status: 'next',
    statusLabel: '下一阶段',
    items: [
      'OpenVINO NPU 与 QNN 适配',
      'Apple Metal / Core ML 路线验证',
      '更多 ASR / TTS 模型族与自定义模型导入',
      '同类型多槽位模型池与预热',
      'AMD ROCm / DirectML 实验后端',
      '服务端鉴权与多用户隔离',
    ],
  },
  {
    version: 'v0.4',
    title: 'Android 与 iOS 规划',
    status: 'planned',
    statusLabel: '仅规划',
    items: [
      'Fluent WebUI + 原生容器复用',
      '移动端模型量化与内存预算',
      '前台服务 / 后台下载策略',
      'NNAPI、QNN、Core ML、ANE 调度',
      '热管理、电量与存储限制',
    ],
  },
];

export function RoadmapPage() {
  return (
    <div className="page roadmap-page">
      <PageHeader
        eyebrow="CROSS-PLATFORM ROADMAP"
        title="跨端路线"
        description="Windows、macOS 与 Linux 已经具备可运行的 Fluent WebUI；Android 与 iOS 目前只做架构规划，不包含可执行客户端。"
        actions={
          <StatusPill tone="warning">移动端 · 规划中</StatusPill>
        }
      />

      <div className="planning-banner">
        <WarningRegular />
        <div>
          <strong>本版本不执行 Android / iOS 实现</strong>
          <span>
            仓库中不会生成 Gradle、Xcode、移动端安装包或 Capacitor
            工程。这里的移动端内容仅用于确定 API 边界、模型格式与加速后端。
          </span>
        </div>
      </div>

      <section className="roadmap-architecture panel">
        <div className="panel-heading">
          <div>
            <span className="panel-kicker">ARCHITECTURE</span>
            <h3>一套 WebUI，四种运行表面</h3>
          </div>
          <span className="queue-hint">共享 Fluent 设计系统与 HTTP API</span>
        </div>
        <div className="architecture-flow">
          <div className="arch-node arch-node-web">
            <div className="arch-icon">
              <DesktopRegular />
            </div>
            <strong>Fluent WebUI</strong>
            <span>React 19 · Fluent UI v9</span>
            <small>Windows · macOS · Linux · 浏览器</small>
          </div>
          <span className="arch-link">
            <span />
            <em>HTTP / JSON</em>
            <ArrowRightRegular />
          </span>
          <div className="arch-node arch-node-api">
            <div className="arch-icon">
              <HardwareIcon kind="cpu" size={24} />
            </div>
            <strong>AIBox API</strong>
            <span>FastAPI · 本地优先</span>
            <small>设备发现 · 下载 · 任务 · 导出</small>
          </div>
          <span className="arch-link">
            <span />
            <em>Adapter</em>
            <ArrowRightRegular />
          </span>
          <div className="arch-node arch-node-runtime">
            <div className="arch-icon">
              <RocketRegular />
            </div>
            <strong>推理运行时</strong>
            <span>CTranslate2 / 未来 NPU</span>
            <small>CPU · CUDA · OpenVINO · QNN · Metal</small>
          </div>
        </div>
        <div className="arch-secondary">
          <span>模型仓库</span>
          <ArrowRightRegular />
          <span>下载 / 校验 / manifest</span>
          <ArrowRightRegular />
          <span>Whisper 权重</span>
          <ArrowRightRegular />
          <span>faster-whisper</span>
        </div>
      </section>

      <section className="roadmap-timeline">
        {PHASES.map((phase) => (
          <article className={`phase-card is-${phase.status}`} key={phase.version}>
            <div className="phase-head">
              <span className="phase-version">{phase.version}</span>
              <StatusPill
                tone={
                  phase.status === 'current'
                    ? 'success'
                    : phase.status === 'next'
                      ? 'info'
                      : 'neutral'
                }
              >
                {phase.statusLabel}
              </StatusPill>
            </div>
            <h3>{phase.title}</h3>
            <ul>
              {phase.items.map((item) => (
                <li key={item}>
                  {phase.status === 'current' ? (
                    <CheckmarkRegular />
                  ) : (
                    <span className="phase-bullet" />
                  )}
                  {item}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </section>

      <section className="mobile-plan-grid">
        <article className="panel mobile-plan-card">
          <div className="mobile-plan-head">
            <div className="mobile-plan-icon">
              <PhoneRegular />
            </div>
            <div>
              <span className="panel-kicker">ANDROID · PLANNED</span>
              <h2>Android 规划</h2>
            </div>
            <StatusPill tone="neutral">不实现</StatusPill>
          </div>
          <div className="mobile-plan-columns">
            <div>
              <h4>容器与 UI</h4>
              <p>
                Kotlin 原生壳承载同一套 Fluent WebUI，通过受控 Bridge 暴露文件选择、前台服务与设备能力。
              </p>
            </div>
            <div>
              <h4>推理</h4>
              <p>
                优先接入 whisper.cpp / ONNX Runtime；NPU 通过 NNAPI、Qualcomm QNN
                或厂商 SDK，按机型能力动态启用。
              </p>
            </div>
            <div>
              <h4>下载与存储</h4>
              <p>
                Foreground Service + WorkManager 管理大模型下载与校验，遵循 Scoped
                Storage，避免后台被系统回收。
              </p>
            </div>
            <div>
              <h4>硬约束</h4>
              <p>
                模型 75 MB–3 GB，需按内存、热与电量预算推荐 Tiny / Base；长音频需分块。
              </p>
            </div>
          </div>
        </article>

        <article className="panel mobile-plan-card">
          <div className="mobile-plan-head">
            <div className="mobile-plan-icon">
              <PhoneRegular />
            </div>
            <div>
              <span className="panel-kicker">iOS · PLANNED</span>
              <h2>iOS 规划</h2>
            </div>
            <StatusPill tone="neutral">不实现</StatusPill>
          </div>
          <div className="mobile-plan-columns">
            <div>
              <h4>容器与 UI</h4>
              <p>
                SwiftUI 原生壳 + WKWebView 承载 Fluent WebUI，保持与桌面完全一致的交互与视觉。
              </p>
            </div>
            <div>
              <h4>推理</h4>
              <p>
                Core ML / ANE 优先，评估 WhisperKit 等实现；GPU 走 Metal，CPU 作为兜底。
              </p>
            </div>
            <div>
              <h4>下载与存储</h4>
              <p>
                URLSession 后台传输仅在系统允许时继续；大模型需显式提示空间与蜂窝网络策略。
              </p>
            </div>
            <div>
              <h4>硬约束</h4>
              <p>
                App 内存上限、后台执行窗口、App Store 审核与模型许可都需在上线前解决。
              </p>
            </div>
          </div>
        </article>
      </section>

      <section className="principles-grid">
        <article className="principle-card">
          <span className="principle-index">01</span>
          <h3>共享 API，不共享进程</h3>
          <p>移动端连接同一套 AIBox API 契约，模型、任务与导出无需重新定义。</p>
        </article>
        <article className="principle-card">
          <span className="principle-index">02</span>
          <h3>能力探测必须诚实</h3>
          <p>检测到硬件不等于能运行 ASR / TTS。只有真实可用的后端才会出现在设备选择中。</p>
        </article>
        <article className="principle-card">
          <span className="principle-index">03</span>
          <h3>本地优先与可删除</h3>
          <p>音频、模型与历史默认留在设备，用户随时可以删除模型和源音频。</p>
        </article>
        <article className="principle-card">
          <span className="principle-index">04</span>
          <h3>先桌面，后移动</h3>
          <p>先把 Whisper 下载、加载、转写与导出做扎实，再评估移动端的算力与体验。</p>
        </article>
      </section>
    </div>
  );
}
