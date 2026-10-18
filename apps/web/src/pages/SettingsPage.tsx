import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Select,
  Slider,
  Switch,
} from '@fluentui/react-components';
import {
  ArrowRightRegular,
  ChatRegular,
  CheckmarkRegular,
  FolderOpenRegular,
  GaugeRegular,
  ImageRegular,
  InfoRegular,
  SaveRegular,
  SettingsRegular,
  Speaker2Regular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { useAppData } from '../state/AppContext';
import { useThemeMode } from '../state/ThemeContext';
import type { AppSettings, VoiceProfile } from '../api/types';
import { api, errorMessage } from '../api/client';
import { formatBytes } from '../utils/format';

export function SettingsPage() {
  const { system, models, settings, updateSettings, notify } = useAppData();
  const { mode, setMode } = useThemeMode();
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const initialized = useRef(false);

  useEffect(() => {
    if (settings && !initialized.current) {
      initialized.current = true;
      setDraft({ ...settings, theme: mode });
    }
  }, [settings, mode]);

  useEffect(() => {
    void api.ttsVoices().then((data) => setVoices(data.voices)).catch(() => undefined);
  }, []);

  const installed = (models?.installed ?? []).filter((model) => model.kind === 'asr');
  const installedTts = (models?.installed ?? []).filter((model) => model.kind === 'tts');
  const installedImages = (models?.installed ?? []).filter((model) => model.kind === 'image');
  const installedLlm = (models?.installed ?? []).filter((model) => model.kind === 'llm');
  const dirty = useMemo(
    () => Boolean(draft && settings && JSON.stringify(draft) !== JSON.stringify(settings)),
    [draft, settings],
  );

  const patch = (values: Partial<AppSettings>) => {
    setDraft((current) => (current ? { ...current, ...values } : current));
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await updateSettings(draft);
      setMode(draft.theme);
    } catch (err) {
      notify('保存设置失败', errorMessage(err), 'error');
    } finally {
      setSaving(false);
    }
  };

  if (!draft) {
    return (
      <div className="page settings-page">
        <PageHeader eyebrow="PREFERENCES" title="设置" />
        <div className="panel loading-panel">正在读取设置…</div>
      </div>
    );
  }

  return (
    <div className="page settings-page">
      <PageHeader
        eyebrow="PREFERENCES"
        title="设置"
        description="配置默认转写参数、外观与本机存储。所有选项只保存在这台设备上。"
        actions={
          <Button
            appearance="primary"
            icon={<SaveRegular />}
            onClick={() => void save()}
            disabled={!dirty || saving}
            className="button-glow"
          >
            {saving ? '正在保存…' : dirty ? '保存更改' : '已保存'}
          </Button>
        }
      />

      <div className="settings-layout">
        <div className="settings-main">
          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <SettingsRegular />
              </div>
              <div>
                <h2>默认转写参数</h2>
                <p>新任务会自动带上这些设置，可在转写页随时覆盖。</p>
              </div>
            </div>

            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认模型</span>
                <Select
                  value={draft.default_model ?? ''}
                  onChange={(_, data) =>
                    patch({ default_model: data.value ? data.value : null })
                  }
                >
                  <option value="">自动选择（推荐）</option>
                  {installed.map((model) => (
                    <option value={model.id} key={model.id}>
                      {model.name} · {model.size_label}
                    </option>
                  ))}
                </Select>
                <span className="field-hint">
                  {installed.length > 0
                    ? '只列出已安装模型。'
                    : '还没有已安装模型，先去模型库下载。'}
                </span>
              </label>

              <label className="field">
                <span className="field-label">默认语言</span>
                <Select
                  value={draft.language}
                  onChange={(_, data) => patch({ language: data.value })}
                >
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
                <span className="field-label">默认任务</span>
                <div className="segmented-control">
                  <button
                    type="button"
                    className={draft.task === 'transcribe' ? 'is-active' : ''}
                    onClick={() => patch({ task: 'transcribe' })}
                  >
                    转写原文
                  </button>
                  <button
                    type="button"
                    className={draft.task === 'translate' ? 'is-active' : ''}
                    onClick={() => patch({ task: 'translate' })}
                  >
                    译为英文
                  </button>
                </div>
              </div>

              <label className="field">
                <span className="field-label">默认推理设备</span>
                <Select
                  value={draft.device}
                  onChange={(_, data) =>
                    patch({ device: data.value as AppSettings['device'] })
                  }
                >
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
                  value={draft.compute_type}
                  onChange={(_, data) => patch({ compute_type: data.value })}
                >
                  <option value="auto">自动（推荐）</option>
                  <option value="int8">int8</option>
                  <option value="int8_float16">int8_float16</option>
                  <option value="float16">float16</option>
                  <option value="float32">float32</option>
                </Select>
              </label>

              <label className="field">
                <span className="field-label">最大并发任务</span>
                <Select
                  value={String(draft.max_concurrent_jobs)}
                  onChange={(_, data) =>
                    patch({ max_concurrent_jobs: Number(data.value) })
                  }
                >
                  <option value="1">1 个任务（推荐）</option>
                  <option value="2">2 个任务</option>
                  <option value="3">3 个任务</option>
                </Select>
                <span className="field-hint">重启本地服务后生效，避免显存争用。</span>
              </label>
            </div>

            <label className="field field-slider">
              <span className="field-label">
                Beam size <strong className="field-value">{draft.beam_size}</strong>
              </span>
              <Slider
                min={1}
                max={10}
                step={1}
                value={draft.beam_size}
                onChange={(_, data) => patch({ beam_size: data.value })}
              />
              <span className="field-hint">
                较高的 Beam size 通常提升准确率，但会增加解码时间。
              </span>
            </label>

            <div className="settings-switch-list">
              <div className="switch-row">
                <div>
                  <strong>VAD 静音过滤</strong>
                  <span>跳过静音片段，加快长音频转写</span>
                </div>
                <Switch
                  checked={draft.vad_filter}
                  onChange={(_, data) => patch({ vad_filter: data.checked })}
                />
              </div>
              <div className="switch-row">
                <div>
                  <strong>词级时间戳</strong>
                  <span>生成更细粒度的 JSON 数据</span>
                </div>
                <Switch
                  checked={draft.word_timestamps}
                  onChange={(_, data) => patch({ word_timestamps: data.checked })}
                />
              </div>
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <Speaker2Regular />
              </div>
              <div>
                <h2>语音合成默认值</h2>
                <p>配置 IndexTTS 的默认模型与参考音色。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认 TTS 模型</span>
                <Select
                  value={draft.default_tts_model ?? ''}
                  onChange={(_, data) =>
                    patch({ default_tts_model: data.value || null })
                  }
                >
                  <option value="">自动选择（推荐）</option>
                  {installedTts.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} · {model.size_label}
                    </option>
                  ))}
                </Select>
                <span className="field-hint">
                  {installedTts.length > 0
                    ? 'IndexTTS 模型通过独立 worker 加载。'
                    : '尚未安装 IndexTTS 模型。'}
                </span>
              </label>
              <label className="field">
                <span className="field-label">默认参考音色</span>
                <Select
                  value={draft.tts_default_voice}
                  onChange={(_, data) => patch({ tts_default_voice: data.value })}
                >
                  {voices.length === 0 && (
                    <option value={draft.tts_default_voice}>
                      {draft.tts_default_voice}
                    </option>
                  )}
                  {voices.map((voice) => (
                    <option key={voice.id} value={voice.id}>
                      {voice.name} · {voice.source === 'builtin' ? '内置' : '自定义'}
                    </option>
                  ))}
                </Select>
              </label>
            </div>
            <div className="inline-note">
              OpenAI TTS 的 alloy / nova 等音色名会映射到内置参考音；需要专属音色时，请在语音合成页上传参考音频。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <ImageRegular />
              </div>
              <div>
                <h2>图像生成默认值</h2>
                <p>选择默认图像模型与引擎；复杂节点图默认隐藏。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认图像模型</span>
                <Select
                  value={draft.default_image_model ?? ''}
                  onChange={(_, data) =>
                    patch({ default_image_model: data.value || null })
                  }
                >
                  <option value="">自动选择（推荐）</option>
                  {installedImages.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} · {model.size_label}
                    </option>
                  ))}
                </Select>
                <span className="field-hint">
                  {installedImages.length > 0
                    ? '图像模型通过 Diffusers 或 ComfyUI 运行。'
                    : '尚未安装图像模型；也可直接使用 ComfyUI 管理的权重。'}
                </span>
              </label>
              <label className="field">
                <span className="field-label">默认引擎</span>
                <Select
                  value={draft.image_provider}
                  onChange={(_, data) => patch({ image_provider: data.value })}
                >
                  <option value="auto">自动选择</option>
                  <option value="comfyui">ComfyUI</option>
                  <option value="diffusers">本地 Diffusers</option>
                  <option value="demo">演示引擎</option>
                </Select>
              </label>
            </div>
            <div className="inline-note">
              默认表单只暴露提示词、比例、模型和数量；步数、种子与 ComfyUI 工作流放在图像生成页的“高级设置”中。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <ChatRegular />
              </div>
              <div>
                <h2>语言模型默认值</h2>
                <p>选择默认 GGUF 模型、推理引擎和对话偏好；外部 OpenAI 兼容服务在环境变量中配置。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认语言模型</span>
                <Select
                  value={draft.default_llm_model ?? ''}
                  onChange={(_, data) => patch({ default_llm_model: data.value || null })}
                >
                  <option value="">自动选择（推荐）</option>
                  {installedLlm.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} · {model.size_label}
                    </option>
                  ))}
                </Select>
                <span className="field-hint">
                  {installedLlm.length > 0
                    ? '本地 GGUF 通过 llama-server 加载。'
                    : '尚未安装语言模型，可在模型库下载 Qwen / Llama GGUF。'}
                </span>
              </label>
              <label className="field">
                <span className="field-label">默认引擎</span>
                <Select
                  value={draft.llm_provider}
                  onChange={(_, data) => patch({ llm_provider: data.value })}
                >
                  <option value="auto">自动选择</option>
                  <option value="llama-cpp">本地 llama.cpp</option>
                  <option value="openai">OpenAI 兼容服务</option>
                  <option value="demo">演示引擎</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">默认温度</span>
                <Select
                  value={String(draft.llm_temperature)}
                  onChange={(_, data) =>
                    patch({ llm_temperature: Number(data.value) })
                  }
                >
                  <option value="0">0.0 精确</option>
                  <option value="0.3">0.3 稳重</option>
                  <option value="0.7">0.7 平衡</option>
                  <option value="1">1.0 创意</option>
                </Select>
              </label>
            </div>
            <div className="inline-note">
              系统提示词与最大 Token 在语言模型页的“高级设置”中调整；设置会作为新对话的默认值。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <GaugeRegular />
              </div>
              <div>
                <h2>弹性调度</h2>
                <p>决定 ASR 与 TTS 模型如何同时驻留、何时换入换出。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">弹性模式</span>
                <Select
                  value={draft.elastic_mode}
                  onChange={(_, data) => patch({ elastic_mode: data.value })}
                >
                  <option value="auto">自动 · 根据近期需求</option>
                  <option value="balanced">均衡 · ASR + TTS 常驻</option>
                  <option value="asr_focus">ASR 优先</option>
                  <option value="tts_focus">TTS 优先</option>
                  <option value="time_slice">时间片 · 集中处理单一类型</option>
                  <option value="custom">自定义 · 固定策略</option>
                </Select>
                <span className="field-hint">
                  自动模式会在 ASR / TTS 之间根据请求热度调整优先级。
                </span>
              </label>
              <label className="field">
                <span className="field-label">最多常驻模型</span>
                <Select
                  value={String(draft.elastic_max_loaded_models)}
                  onChange={(_, data) =>
                    patch({ elastic_max_loaded_models: Number(data.value) })
                  }
                >
                  <option value="1">1 个（最省显存）</option>
                  <option value="2">2 个（ASR + TTS）</option>
                  <option value="3">3 个（ASR + TTS + 图像）</option>
                  <option value="4">4 个（ASR + TTS + 图像 + 语言）</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">固定驻留类型</span>
                <Select
                  value={
                    draft.elastic_pinned_kinds.length >= 2
                      ? 'both'
                      : draft.elastic_pinned_kinds[0] ?? ''
                  }
                  onChange={(_, data) => {
                    if (data.value === 'both') {
                      patch({ elastic_pinned_kinds: ['asr', 'tts'] });
                    } else if (data.value) {
                      patch({ elastic_pinned_kinds: [data.value] });
                    } else {
                      patch({ elastic_pinned_kinds: [] });
                    }
                  }}
                >
                  <option value="">不固定</option>
                  <option value="asr">固定 ASR</option>
                  <option value="tts">固定 TTS</option>
                  <option value="both">两者都固定</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">
                  空闲卸载 <strong className="field-value">{Math.round(draft.elastic_idle_ttl_seconds / 60)} 分钟</strong>
                </span>
                <Slider
                  min={0}
                  max={3600}
                  step={30}
                  value={draft.elastic_idle_ttl_seconds}
                  onChange={(_, data) => patch({ elastic_idle_ttl_seconds: data.value })}
                />
                <span className="field-hint">0 表示不按空闲时间卸载。</span>
              </label>
              <label className="field">
                <span className="field-label">
                  时间片切换 <strong className="field-value">{Math.round(draft.elastic_switch_interval_seconds / 60)} 分钟</strong>
                </span>
                <Slider
                  min={30}
                  max={3600}
                  step={30}
                  value={draft.elastic_switch_interval_seconds}
                  onChange={(_, data) => patch({ elastic_switch_interval_seconds: data.value })}
                />
                <span className="field-hint">用于“时间片”模式的焦点切换窗口。</span>
              </label>
              <label className="field">
                <span className="field-label">
                  显存预留 <strong className="field-value">{draft.elastic_gpu_reserve_gb.toFixed(1)} GB</strong>
                </span>
                <Slider
                  min={0}
                  max={8}
                  step={0.5}
                  value={draft.elastic_gpu_reserve_gb}
                  onChange={(_, data) => patch({ elastic_gpu_reserve_gb: data.value })}
                />
              </label>
              <label className="field">
                <span className="field-label">
                  内存预留 <strong className="field-value">{draft.elastic_ram_reserve_gb.toFixed(1)} GB</strong>
                </span>
                <Slider
                  min={0}
                  max={16}
                  step={0.5}
                  value={draft.elastic_ram_reserve_gb}
                  onChange={(_, data) => patch({ elastic_ram_reserve_gb: data.value })}
                />
              </label>
            </div>
            <div className="inline-note">
              自动：按近期请求热度分配优先级；均衡：两类各保留一个模型；ASR/TTS 优先：保护指定类型；
              时间片：每隔一段时间集中服务热度最高的类型；自定义：严格按固定类型与上限执行。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <FolderOpenRegular />
              </div>
              <div>
                <h2>存储与隐私</h2>
                <p>控制音频缓存与本地数据目录。</p>
              </div>
            </div>
            <div className="settings-switch-list">
              <div className="switch-row">
                <div>
                  <strong>保留源音频</strong>
                  <span>关闭后，转写完成会删除上传的音频文件，字幕与文本保留</span>
                </div>
                <Switch
                  checked={draft.keep_audio}
                  onChange={(_, data) => patch({ keep_audio: data.checked })}
                />
              </div>
            </div>
            <div className="path-list settings-paths">
              <div>
                <span>数据目录</span>
                <strong title={system?.storage.data_dir}>{system?.storage.data_dir ?? '—'}</strong>
              </div>
              <div>
                <span>模型目录</span>
                <strong title={system?.storage.models_dir}>{system?.storage.models_dir ?? '—'}</strong>
              </div>
              <div>
                <span>TTS 模型目录</span>
                <strong title={system?.storage.tts_models_dir}>
                  {system?.storage.tts_models_dir ?? '—'}
                </strong>
              </div>
              <div>
                <span>可用空间</span>
                <strong>{formatBytes(system?.storage.free_bytes ?? null)}</strong>
              </div>
            </div>
            <div className="inline-note">
              音频只会上传到本机的 AIBox 服务，并保存在上述目录中。删除转写历史时会同时移除对应音频。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <SettingsRegular />
              </div>
              <div>
                <h2>界面外观</h2>
                <p>Fluent 设计系统，深色与浅色主题都保留完整对比度。</p>
              </div>
            </div>
            <div className="theme-grid">
              {(
                [
                  { id: 'dark', title: '深色', note: '适合夜间与影音工作' },
                  { id: 'light', title: '浅色', note: '适合明亮办公环境' },
                  { id: 'system', title: '跟随系统', note: '自动切换' },
                ] as const
              ).map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`theme-card${mode === item.id ? ' is-active' : ''}`}
                  onClick={() => {
                    setMode(item.id);
                    patch({ theme: item.id });
                  }}
                >
                  <span className={`theme-preview theme-${item.id}`}>
                    <span />
                    <span />
                    <span />
                  </span>
                  <span className="theme-card-copy">
                    <strong>
                      {item.title}
                      {mode === item.id && <CheckmarkRegular />}
                    </strong>
                    <small>{item.note}</small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        </div>

        <aside className="settings-side">
          <section className="panel about-card">
            <div className="about-brand">
              <img src="/aibox-mark.svg" alt="" />
              <div>
                <strong>AIBox</strong>
                <span>Local AI Studio</span>
              </div>
            </div>
            <p>
              跨平台本地 AI 模型工作台。当前版本聚焦 Whisper ASR
              与模型管理，桌面端复用同一套 Fluent WebUI。
            </p>
            <div className="about-facts">
              <div>
                <span>版本</span>
                <strong>v0.1.0</strong>
              </div>
              <div>
                <span>ASR 引擎</span>
                <strong>{system?.engines.asr.name ?? 'faster-whisper'}</strong>
              </div>
              <div>
                <span>运行平台</span>
                <strong>{system?.platform.label ?? '—'}</strong>
              </div>
              <div>
                <span>许可证</span>
                <strong>MIT</strong>
              </div>
            </div>
            <div className="about-actions">
              <a href="/docs" target="_blank" rel="noreferrer" className="text-link">
                <InfoRegular /> API 文档
              </a>
              <Link to="/roadmap" className="text-link">
                跨端路线 <ArrowRightRegular />
              </Link>
            </div>
          </section>

          <section className="panel settings-status">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">STATUS</span>
                <h3>当前能力</h3>
              </div>
            </div>
            <div className="status-list">
              <div>
                <span>Whisper 模型</span>
                <StatusPill tone={installed.length > 0 ? 'success' : 'warning'}>
                  {installed.length > 0 ? `${installed.length} 个可用` : '未安装'}
                </StatusPill>
              </div>
              <div>
                <span>ASR 引擎</span>
                <StatusPill tone={system?.engines.asr.installed ? 'success' : 'warning'}>
                  {system?.engines.asr.installed ? '已就绪' : '未安装'}
                </StatusPill>
              </div>
              <div>
                <span>CUDA</span>
                <StatusPill tone={system?.has_cuda ? 'success' : 'neutral'}>
                  {system?.has_cuda ? '可用' : 'CPU 模式'}
                </StatusPill>
              </div>
              <div>
                <span>NPU</span>
                <StatusPill tone="warning">
                  {system?.npus.length ? '适配中' : '未检测到'}
                </StatusPill>
              </div>
            </div>
            <p className="settings-status-note">
              配置保存后立即应用。推理设备与并发数在下一个任务或服务重启后完全生效。
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
