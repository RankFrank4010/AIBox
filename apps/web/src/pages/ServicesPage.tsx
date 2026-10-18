import { useMemo, type ReactNode } from 'react';
import { Button, type ToastIntent } from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ChatRegular,
  CloudRegular,
  CodeRegular,
  CopyRegular,
  GlobeRegular,
  ImageRegular,
  KeyRegular,
  MicRegular,
  PlugConnectedRegular,
  ServerRegular,
  Speaker2Regular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill, type StatusTone } from '../components/StatusPill';
import { useAppData } from '../state/AppContext';
import type { TransportServices } from '../api/types';
import { api } from '../api/client';

function toneForStatus(status: string): StatusTone {
  if (status === 'running' || status === 'ready') return 'success';
  if (status === 'error' || status === 'engine-unavailable') return 'danger';
  if (status === 'disabled') return 'neutral';
  if (status === 'no-model' || status === 'runtime-missing') return 'warning';
  return 'warning';
}

function labelForStatus(status: string): string {
  if (status === 'running') return '运行中';
  if (status === 'ready') return '可用';
  if (status === 'error') return '启动失败';
  if (status === 'engine-unavailable') return '引擎未安装';
  if (status === 'disabled') return '未启用';
  if (status === 'runtime-missing') return '运行时缺失';
  if (status === 'no-model') return '缺少模型';
  if (status === 'demo') return '演示引擎';
  return '启动中';
}

function CodeBlock({
  label,
  code,
  notify,
}: {
  label: string;
  code: string;
  notify: (title: string, body?: string, intent?: ToastIntent) => void;
}) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      notify('已复制', label);
    } catch {
      notify('复制失败', '浏览器拒绝访问剪贴板。', 'error');
    }
  };
  return (
    <div className="code-block">
      <div className="code-head">
        <span>{label}</span>
        <button type="button" onClick={() => void copy()} aria-label={`复制 ${label}`}>
          <CopyRegular /> 复制
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function ServiceCard({
  icon,
  accent,
  title,
  subtitle,
  status,
  children,
}: {
  icon: ReactNode;
  accent: string;
  title: string;
  subtitle: string;
  status: ReactNode;
  children: ReactNode;
}) {
  return (
    <article className={`service-card service-${accent}`}>
      <div className="service-card-head">
        <div className="service-icon">{icon}</div>
        <div className="service-title">
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        {status}
      </div>
      {children}
    </article>
  );
}

export function ServicesPage() {
  const { system, notify } = useAppData();
  const services: TransportServices | null = system?.services ?? null;
  const isDesktop =
    window.location.protocol === 'tauri:' ||
    window.location.hostname === 'tauri.localhost' ||
    window.location.hostname.endsWith('.tauri.localhost');
  const httpOrigin = isDesktop
    ? (services?.openai.base_url ?? 'http://127.0.0.1:8765/v1').replace(/\/v1$/, '')
    : window.location.origin;
  const wsOrigin = httpOrigin.replace('https://', 'wss://').replace('http://', 'ws://');

  const openaiUrl = `${httpOrigin}${services?.openai.transcriptions ?? '/v1/audio/transcriptions'}`;
  const openaiModels = `${httpOrigin}${services?.openai.models ?? '/v1/models'}`;
  const websocketUrl = `${wsOrigin}${services?.websocket.path ?? '/ws/asr'}`;
  const grpcEndpoint = services?.grpc.host
    ? `${services.grpc.host}:${services.grpc.port}`
    : `127.0.0.1:${services?.grpc.port ?? 50051}`;
  const mrcpEndpoint = services?.mrcp.host
    ? `sip:aibox@${services.mrcp.host}:${services.mrcp.port}`
    : `sip:aibox@127.0.0.1:${services?.mrcp.port ?? 8060}`;
  const authRequired = Boolean(services?.openai.auth_required);
  const apiKey = authRequired ? '<YOUR_AIBOX_API_TOKEN>' : 'aibox';

  const curlCode = useMemo(
    () =>
      `curl ${openaiUrl} \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -F file=@meeting.mp3 \\\n  -F model=whisper-1 \\\n  -F language=zh \\\n  -F response_format=verbose_json`,
    [openaiUrl, apiKey],
  );
  const pythonCode = useMemo(
    () =>
      `from openai import OpenAI\n\nclient = OpenAI(\n    base_url="${httpOrigin}/v1",\n    api_key="${apiKey}",\n)\n\nwith open("meeting.mp3", "rb") as audio:\n    result = client.audio.transcriptions.create(\n        model="whisper-1",\n        file=audio,\n        response_format="verbose_json",\n    )\nprint(result.text)`,
    [httpOrigin, apiKey],
  );
  const websocketCode = useMemo(
    () =>
      `import asyncio, json, websockets\n\nasync def main():\n    async with websockets.connect("${websocketUrl}") as ws:\n        await ws.send(json.dumps({\n            "type": "start", "model": "whisper-1",\n            "format": "pcm16", "sample_rate": 16000,\n            "partial": True,\n        }))\n        print(await ws.recv())  # ready\n        # send binary PCM16 mono frames here\n        await ws.send(json.dumps({"type": "stop"}))\n        while True:\n            event = json.loads(await ws.recv())\n            print(event)\n            if event["type"] in ("final", "error"):\n                break\n\nasyncio.run(main())`,
    [websocketUrl],
  );
  const ttsCode = useMemo(
    () =>
      `curl ${httpOrigin}/v1/audio/speech \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"tts-1","voice":"alloy","input":"你好，欢迎使用 AIBox","response_format":"mp3"}' \\\n  --output speech.mp3`,
    [httpOrigin, apiKey],
  );
  const imagesCode = useMemo(
    () =>
      `curl ${httpOrigin}/v1/images/generations \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"sdxl","prompt":"云海上的未来图书馆","size":"1024x1024","n":1,"response_format":"url"}'`,
    [httpOrigin, apiKey],
  );
  const chatCode = useMemo(
    () =>
      `curl ${httpOrigin}/v1/chat/completions \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"qwen3-8b","messages":[{"role":"user","content":"你好"}]}'`,
    [httpOrigin, apiKey],
  );
  const grpcCode = useMemo(
    () =>
      `grpcurl -plaintext ${grpcEndpoint} list\ngrpcurl -plaintext ${grpcEndpoint} \\\n  describe aibox.asr.v1.AsrService\n\n# Unary: aibox.asr.v1.AsrService/Transcribe\n# Stream: aibox.asr.v1.AsrService/TranscribeStream\n# Proto: ${httpOrigin}/api/services/proto${authRequired ? '\n# Metadata: authorization: Bearer <YOUR_AIBOX_API_TOKEN>' : ''}`,
    [grpcEndpoint, httpOrigin, authRequired],
  );
  const mrcpCode = useMemo(
    () =>
      `INVITE ${mrcpEndpoint} SIP/2.0\nContent-Type: application/sdp\n\nm=application <control-port> TCP/MRCPv2 1\na=resource:speechrecog\nm=audio <rtp-port> RTP/AVP 0 8 96\na=rtpmap:0 PCMU/8000\na=rtpmap:8 PCMA/8000\na=rtpmap:96 L16/16000`,
    [mrcpEndpoint],
  );

  return (
    <div className="page services-page">
      <PageHeader
        eyebrow="EXTERNAL ACCESS"
        title="服务接入"
        description="把 AIBox 的 Whisper 能力暴露给现有业务系统。HTTP、WebSocket、gRPC 与 MRCP 共享同一套模型、队列、历史和 GPU / CPU 推理链路。"
        actions={
          <StatusPill tone={system ? 'success' : 'warning'}>
            {system ? '外部服务已编排' : '等待系统信息'}
          </StatusPill>
        }
      />

      <section className="services-summary">
        <div className="services-summary-copy">
          <div className="services-summary-icon">
            <PlugConnectedRegular />
          </div>
          <div>
            <strong>一个推理后端，四种接入方式</strong>
            <span>
              所有请求都会进入 AIBox 的任务队列，使用已安装的 Whisper 模型与自动选择的
              CPU / CUDA 设备。外部音频和字幕仍保存在本机。
            </span>
          </div>
        </div>
        <div className="services-summary-meta">
          <div>
            <span>OpenAI Base</span>
            <strong>{httpOrigin}/v1</strong>
          </div>
          <div>
            <span>鉴权</span>
            <strong>{authRequired ? 'Bearer Token' : '未启用'}</strong>
          </div>
          <div>
            <span>默认模型</span>
            <strong>{system?.settings.default_model ?? '自动'}</strong>
          </div>
        </div>
      </section>

      {!services ? (
        <div className="panel loading-panel">正在读取外部服务状态…</div>
      ) : (
        <section className="service-grid">
          <ServiceCard
            icon={<CloudRegular />}
            accent="violet"
            title="OpenAI 兼容 HTTP"
            subtitle="POST /v1/audio/transcriptions"
            status={
              <StatusPill tone={toneForStatus(services.openai.status)}>
                {labelForStatus(services.openai.status)}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>Base URL</span>
              <code>{httpOrigin}/v1</code>
            </div>
            <div className="endpoint-line">
              <span>Models</span>
              <code>{openaiModels}</code>
            </div>
            <div className="service-facts">
              <span>response_format</span>
              <strong>{services.openai.response_formats.join(' · ')}</strong>
            </div>
            <CodeBlock label="curl" code={curlCode} notify={notify} />
            <CodeBlock label="OpenAI Python SDK" code={pythonCode} notify={notify} />
            <a
              className="service-doc-link"
              href="https://platform.openai.com/docs/api-reference/audio/createTranscription"
              target="_blank"
              rel="noreferrer"
            >
              OpenAI 官方接口语义 <GlobeRegular />
            </a>
          </ServiceCard>

          <ServiceCard
            icon={<Speaker2Regular />}
            accent="mint"
            title="OpenAI TTS 兼容"
            subtitle="POST /v1/audio/speech"
            status={
              <StatusPill tone={toneForStatus(services.openai_tts?.status ?? 'starting')}>
                {labelForStatus(services.openai_tts?.status ?? 'starting')}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>Endpoint</span>
              <code>{httpOrigin}/v1/audio/speech</code>
            </div>
            <div className="service-facts">
              <span>格式</span>
              <strong>{services.openai_tts?.formats?.join(' · ') ?? 'mp3 · wav · flac · pcm'}</strong>
            </div>
            <div className="service-facts">
              <span>本地引擎</span>
              <strong>{services.openai_tts?.engine?.status ?? '检测中'}</strong>
            </div>
            <CodeBlock label="curl" code={ttsCode} notify={notify} />
            <p className="service-note">
              `model` 支持 tts-1 / tts-1-hd / gpt-4o-mini-tts 与 IndexTTS 模型 ID；
              声音克隆音色请在语音合成页上传参考音频。OpenAI TTS 与 ASR 共享 Bearer Token。
            </p>
            <Button
              as="a"
              href="/tts"
              appearance="secondary"
              size="small"
              icon={<Speaker2Regular />}
            >
              打开语音合成
            </Button>
          </ServiceCard>

          <ServiceCard
            icon={<ImageRegular />}
            accent="violet"
            title="OpenAI Images 兼容"
            subtitle="POST /v1/images/generations"
            status={
              <StatusPill tone={toneForStatus(services.openai_images?.status ?? 'starting')}>
                {labelForStatus(services.openai_images?.status ?? 'starting')}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>Endpoint</span>
              <code>{httpOrigin}/v1/images/generations</code>
            </div>
            <div className="service-facts">
              <span>尺寸</span>
              <strong>{services.openai_images?.sizes?.join(' · ') ?? '512x512 · 1024x1024'}</strong>
            </div>
            <div className="service-facts">
              <span>引擎</span>
              <strong>{services.openai_images?.engine?.demo ? '演示' : services.openai_images?.engine?.comfyui?.available ? 'ComfyUI' : 'Diffusers'}</strong>
            </div>
            <CodeBlock label="curl" code={imagesCode} notify={notify} />
            <p className="service-note">
              支持 `response_format=url|b64_json`、`n`、`size`；默认隐藏 ComfyUI
              节点图。复杂工作流可在图像生成页高级设置中使用。
            </p>
            <Button
              as="a"
              href="/images"
              appearance="secondary"
              size="small"
              icon={<ImageRegular />}
            >
              打开图像生成
            </Button>
          </ServiceCard>

          <ServiceCard
            icon={<ChatRegular />}
            accent="violet"
            title="OpenAI Chat 兼容"
            subtitle="POST /v1/chat/completions"
            status={
              <StatusPill tone={toneForStatus(services.openai.status)}>
                {labelForStatus(services.openai.status)}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>Endpoint</span>
              <code>{httpOrigin}/v1/chat/completions</code>
            </div>
            <div className="service-facts">
              <span>流式</span>
              <strong>stream=true · SSE</strong>
            </div>
            <div className="service-facts">
              <span>模型</span>
              <strong>GGUF / OpenAI 兼容</strong>
            </div>
            <CodeBlock label="curl" code={chatCode} notify={notify} />
            <p className="service-note">
              与语言模型页共享引擎；本地 GGUF 需要 llama-server，外部服务使用 AIBOX_LLM_BASE_URL。
            </p>
            <Button
              as="a"
              href="/chat"
              appearance="secondary"
              size="small"
              icon={<ChatRegular />}
            >
              打开对话
            </Button>
          </ServiceCard>

          <ServiceCard
            icon={<MicRegular />}
            accent="cyan"
            title="WebSocket 流式音频"
            subtitle="PCM16 或编码文件分块发送"
            status={
              <StatusPill tone={toneForStatus(services.websocket.status)}>
                {labelForStatus(services.websocket.status)}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>URL</span>
              <code>{websocketUrl}</code>
            </div>
            <div className="service-facts">
              <span>实时部分结果</span>
              <strong>{services.websocket.partial_supported ? '支持（PCM16 + partial: true）' : '未启用'}</strong>
            </div>
            <div className="ws-events">
              {['ready', 'received', 'partial', 'processing', 'progress', 'final', 'error'].map(
                (event) => (
                  <span key={event}>{event}</span>
                ),
              )}
            </div>
            <CodeBlock label="Python client" code={websocketCode} notify={notify} />
            <p className="service-note">
              首帧必须是 JSON <code>start</code>；PCM16 为单声道 16-bit little-endian，随后发送
              binary 帧。编码文件模式直接发送原始 WAV / MP3 字节。
            </p>
          </ServiceCard>

          <ServiceCard
            icon={<ServerRegular />}
            accent="mint"
            title="gRPC"
            subtitle="Unary + bidirectional streaming"
            status={
              <StatusPill tone={toneForStatus(services.grpc.status)}>
                {labelForStatus(services.grpc.status)}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>Address</span>
              <code>{grpcEndpoint}</code>
            </div>
            <div className="endpoint-line">
              <span>Service</span>
              <code>{services.grpc.service ?? 'aibox.asr.v1.AsrService'}</code>
            </div>
            <div className="endpoint-line">
              <span>TTS Service</span>
              <code>{services.grpc.tts_service ?? 'aibox.tts.v1.TtsService'}</code>
            </div>
            {services.grpc.error && (
              <div className="inline-note warning-note">{services.grpc.error}</div>
            )}
            <div className="service-actions">
              <Button
                as="a"
                href={api.url('/api/services/proto')}
                appearance="secondary"
                size="small"
                icon={<ArrowDownloadRegular />}
              >
                ASR proto
              </Button>
              <Button
                as="a"
                href={api.url('/api/services/proto/tts')}
                appearance="secondary"
                size="small"
                icon={<ArrowDownloadRegular />}
              >
                TTS proto
              </Button>
              {services.grpc.auth_required && (
                <StatusPill tone="warning" dot={false}>
                  <KeyRegular /> Bearer metadata
                </StatusPill>
              )}
            </div>
            <CodeBlock label="grpcurl" code={grpcCode} notify={notify} />
            <p className="service-note">
              gRPC 与 HTTP API 共享任务队列，适合服务间调用；Reflection 已开启，可直接用
              grpcurl / grpcui 调试。
            </p>
          </ServiceCard>

          <ServiceCard
            icon={<CodeRegular />}
            accent="amber"
            title="MRCPv2"
            subtitle="SIP/UDP + RTP + MRCPv2/TCP"
            status={
              <StatusPill tone={toneForStatus(services.mrcp.status)}>
                {labelForStatus(services.mrcp.status)}
              </StatusPill>
            }
          >
            <div className="endpoint-line">
              <span>SIP URI</span>
              <code>{mrcpEndpoint}</code>
            </div>
            <div className="endpoint-line">
              <span>Resource</span>
              <code>{services.mrcp.resource ?? 'speechrecog'}</code>
            </div>
            <div className="service-facts">
              <span>Codecs</span>
              <strong>{services.mrcp.codecs?.join(' · ') ?? 'PCMU · PCMA · L16'}</strong>
            </div>
            <div className="service-facts">
              <span>Control / RTP</span>
              <strong>
                {services.mrcp.control_port ?? 8061} TCP ·{' '}
                {services.mrcp.rtp_port_range
                  ? `${services.mrcp.rtp_port_range[0]}–${services.mrcp.rtp_port_range[1]}`
                  : '50000–50100'}{' '}
                UDP
              </strong>
            </div>
            <div className="service-facts">
              <span>Advertise</span>
              <strong>{services.mrcp.advertise_host ?? '127.0.0.1'}</strong>
            </div>
            {services.mrcp.error && (
              <div className="inline-note warning-note">{services.mrcp.error}</div>
            )}
            <CodeBlock label="SDP / resource" code={mrcpCode} notify={notify} />
            <p className="service-note">
              面向 IVR / 呼叫中心的最小 MRCPv2 speechrecog 实现：支持 RECOGNIZE、STOP、
              START-INPUT-TIMERS、SET/GET-PARAMS、NLSML 结果；目前为 SIP over UDP、每 dialog
              一个通道。生产环境建议在前置 SBC / 网关做鉴权与限流。
            </p>
          </ServiceCard>
        </section>
      )}

      <section className="services-security panel">
        <div className="services-security-icon">
          <KeyRegular />
        </div>
        <div>
          <h2>外部接入安全</h2>
          <p>
            本地 WebUI 使用 <code>/api</code>，不受外部 Token 影响；OpenAI、WebSocket 与 gRPC
            受 <code>AIBOX_API_TOKEN</code> 保护。MRCP 走 SIP/RTP，没有内置 Token，需要通过
            SBC、防火墙或可信内网限制来源。默认只绑定回环地址。
          </p>
        </div>
        <StatusPill tone={authRequired ? 'success' : 'warning'}>
          {authRequired ? 'Token 已配置' : 'Token 未配置'}
        </StatusPill>
      </section>

      <section className="services-footer-links">
        <a href={api.url('/docs')} target="_blank" rel="noreferrer">
          FastAPI / OpenAPI <GlobeRegular />
        </a>
        <a href={api.url('/api/services/proto')} target="_blank" rel="noreferrer">
          gRPC proto <ArrowDownloadRegular />
        </a>
        <span>
          端口：HTTP {system?.server.port ?? 8765} · gRPC {services?.grpc.port ?? 50051} ·
          MRCP SIP {services?.mrcp.port ?? 8060}/udp · 控制{' '}
          {services?.mrcp.control_port ?? 8061}/tcp · RTP{' '}
          {services?.mrcp.rtp_port_range
            ? `${services.mrcp.rtp_port_range[0]}–${services.mrcp.rtp_port_range[1]}`
            : '50000–50100'}
          /udp
        </span>
      </section>
    </div>
  );
}
