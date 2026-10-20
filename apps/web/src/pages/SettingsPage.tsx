import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Input,
  Select,
  Slider,
  Switch,
} from '@fluentui/react-components';
import {
  AddRegular,
  ArrowRightRegular,
  BeakerRegular,
  ChatRegular,
  CheckmarkRegular,
  DeleteRegular,
  DocumentTextRegular,
  FolderOpenRegular,
  GaugeRegular,
  ImageRegular,
  InfoRegular,
  LocalLanguageRegular,
  PersonRegular,
  SaveRegular,
  SettingsRegular,
  Speaker2Regular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { useAppData } from '../state/AppContext';
import { useThemeMode } from '../state/ThemeContext';
import type { AppSettings, AuthStatus, AuthUser, VoiceProfile } from '../api/types';
import { api, errorMessage } from '../api/client';
import { formatBytes } from '../utils/format';

export function SettingsPage() {
  const { system, models, settings, updateSettings, notify } = useAppData();
  const { mode, setMode } = useThemeMode();
  const [draft, setDraft] = useState<AppSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [newUser, setNewUser] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('viewer');
  const initialized = useRef(false);

  useEffect(() => {
    if (settings && !initialized.current) {
      initialized.current = true;
      setDraft({ ...settings, theme: mode });
    }
  }, [settings, mode]);

  useEffect(() => {
    void api.ttsVoices().then((data) => setVoices(data.voices)).catch(() => undefined);
    void api.authStatus().then(setAuth).catch(() => undefined);
  }, []);

  const loadUsers = async () => {
    try {
      const data = await api.authUsers();
      setUsers(data.users);
    } catch {
      setUsers([]);
    }
  };

  useEffect(() => {
    if (auth?.enabled && auth.user?.role === 'admin') void loadUsers();
  }, [auth]);

  const installed = (models?.installed ?? []).filter((model) => model.kind === 'asr');
  const installedTts = (models?.installed ?? []).filter((model) => model.kind === 'tts');
  const installedImages = (models?.installed ?? []).filter((model) => model.kind === 'image');
  const installedLlm = (models?.installed ?? []).filter((model) => model.kind === 'llm');
  const computeDevices = system?.devices?.devices ?? [];
  const priorityWindows = draft?.compute_priority_windows ?? [];
  const priorityEffective = system?.runtime?.compute_priority?.effective ?? 'balanced';
  const priorityDays = ['日', '一', '二', '三', '四', '五', '六'];
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
                  <option value="vllm">vLLM</option>
                  <option value="sglang">SGLang</option>
                  <option value="mlx">MLX / MLX-LM</option>
                  <option value="tensorrt-llm">TensorRT-LLM</option>
                  <option value="lmstudio">LM Studio</option>
                  <option value="ollama">Ollama</option>
                  <option value="openai">其他 OpenAI 兼容服务</option>
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
                <h2>多设备与并行推理</h2>
                <p>选择参与推理的计算设备，并为 ASR / TTS / 图像 / LLM 指定设备与并行策略。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">并行策略</span>
                <Select
                  value={draft.parallel_strategy}
                  onChange={(_, data) => patch({ parallel_strategy: data.value })}
                >
                  <option value="auto">自动</option>
                  <option value="single">单设备</option>
                  <option value="data">数据并行</option>
                  <option value="tensor">张量并行（LLM row split）</option>
                  <option value="pipeline">流水并行（LLM layer split）</option>
                  <option value="hybrid">混合（LLM row + 数据并行）</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">并发任务数</span>
                <Select
                  value={String(draft.parallel_workers)}
                  onChange={(_, data) => patch({ parallel_workers: Number(data.value) })}
                >
                  {[1, 2, 3, 4, 6, 8].map((value) => (
                    <option key={value} value={String(value)}>
                      {value} 个
                    </option>
                  ))}
                </Select>
              </label>
              <div className="field field-full">
                <span className="field-label">设备池</span>
                <div className="device-picker">
                  {computeDevices.map((device) => {
                    const selected = draft.parallel_devices.includes(device.id);
                    return (
                      <button
                        key={device.id}
                        type="button"
                        className={`device-chip${selected ? ' is-active' : ''}`}
                        disabled={!device.available}
                        onClick={() =>
                          patch({
                            parallel_devices: selected
                              ? draft.parallel_devices.filter((item) => item !== device.id)
                              : [...draft.parallel_devices, device.id],
                          })
                        }
                      >
                        <strong>{device.id}</strong>
                        <small>
                          {device.name} · {device.backend}
                          {device.memory_gb ? ` · ${device.memory_gb} GB` : ''}
                        </small>
                      </button>
                    );
                  })}
                </div>
                <span className="field-hint">
                  不选表示自动使用全部可用加速设备；CPU 始终可用。
                </span>
              </div>
              {(['asr', 'tts', 'image', 'llm'] as const).map((engine) => (
                <label className="field" key={engine}>
                  <span className="field-label">
                    {engine === 'asr'
                      ? 'ASR 设备'
                      : engine === 'tts'
                        ? 'TTS 设备'
                        : engine === 'image'
                          ? '图像设备'
                          : 'LLM 设备'}
                  </span>
                  <Select
                    value={draft[`${engine}_device`]}
                    onChange={(_, data) => patch({ [`${engine}_device`]: data.value })}
                  >
                    <option value="auto">自动分配</option>
                    {computeDevices
                      .filter((device) => device.available)
                      .map((device) => (
                        <option key={device.id} value={device.id}>
                          {device.id} · {device.name}
                        </option>
                      ))}
                  </Select>
                </label>
              ))}
            </div>
            <div className="inline-note">
              数据并行会按设备分配 ASR / API 任务；张量与流水并行走 llama.cpp 的多 GPU
              切分。单卡设备会忽略多卡策略；切换策略后建议重新加载模型或重启服务。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <BeakerRegular />
              </div>
              <div>
                <h2>计算优先级与时段</h2>
                <p>默认优先 ASR / TTS / 图像等普通服务；可设置特殊时段优先大模型，或自动按需求调节。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">优先级模式</span>
                <Select
                  value={draft.compute_priority_mode}
                  onChange={(_, data) => patch({ compute_priority_mode: data.value })}
                >
                  <option value="services_first">普通服务优先（推荐）</option>
                  <option value="llm_first">大模型优先</option>
                  <option value="scheduled">按时间段规则</option>
                  <option value="auto">自动平衡</option>
                </Select>
                <span className="field-hint">
                  当前生效：{priorityEffective === 'llm' ? '大模型优先' : priorityEffective === 'services' ? '普通服务优先' : '平衡'}
                </span>
              </label>
              <div className="field">
                <span className="field-label">LLM 特殊时段</span>
                <span className="field-hint">
                  {priorityWindows.length
                    ? `${priorityWindows.length} 条规则；时段内大模型优先`
                    : '未设置，特殊时段不会自动切换'}
                </span>
              </div>
            </div>
            <div className="priority-windows">
              {priorityWindows.map((window, index) => (
                <div className="priority-window" key={`${window.start}-${window.end}-${index}`}>
                  <div className="priority-time">
                    <Input
                      type="time"
                      value={window.start}
                      onChange={(_, data) => {
                        const next = priorityWindows.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, start: data.value } : item,
                        );
                        patch({ compute_priority_windows: next });
                      }}
                    />
                    <span>至</span>
                    <Input
                      type="time"
                      value={window.end}
                      onChange={(_, data) => {
                        const next = priorityWindows.map((item, itemIndex) =>
                          itemIndex === index ? { ...item, end: data.value } : item,
                        );
                        patch({ compute_priority_windows: next });
                      }}
                    />
                  </div>
                  <div className="priority-days">
                    {priorityDays.map((label, day) => (
                      <button
                        key={label}
                        type="button"
                        className={window.days.includes(day) ? 'is-active' : ''}
                        onClick={() => {
                          const days = window.days.includes(day)
                            ? window.days.filter((item) => item !== day)
                            : [...window.days, day];
                          const next = priorityWindows.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, days } : item,
                          );
                          patch({ compute_priority_windows: next });
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <Button
                    appearance="subtle"
                    size="small"
                    icon={<DeleteRegular />}
                    onClick={() =>
                      patch({
                        compute_priority_windows: priorityWindows.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      })
                    }
                  >
                    删除
                  </Button>
                </div>
              ))}
            </div>
            <Button
              appearance="secondary"
              size="small"
              icon={<AddRegular />}
              onClick={() =>
                patch({
                  compute_priority_windows: [
                    ...priorityWindows,
                    { start: '22:00', end: '08:00', days: [0, 1, 2, 3, 4, 5, 6] },
                  ],
                })
              }
            >
              添加时段
            </Button>
            <div className="inline-note">
              普通服务优先时，新 LLM 请求会在 ASR / TTS / 图像任务到来时暂缓；已运行的 LLM
              生成不会强制中断。大模型优先时段内，普通服务会尽量让出显存。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <LocalLanguageRegular />
              </div>
              <div>
                <h2>翻译服务</h2>
                <p>配置 LibreTranslate / Argos、Index-Translate、腾讯混元 Hy-MT2 或 OpenAI 兼容翻译网关。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认翻译服务</span>
                <Select
                  value={draft.translation_provider}
                  onChange={(_, data) => patch({ translation_provider: data.value })}
                >
                  <option value="auto">自动选择可用服务</option>
                  <option value="libre">LibreTranslate / Argos HTTP</option>
                  <option value="argos">Argos Translate CLI</option>
                  <option value="index">Index-Translate</option>
                  <option value="hunyuan">腾讯混元 Hy-MT2</option>
                  <option value="openai">OpenAI 兼容翻译网关</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">LibreTranslate 地址</span>
                <Input
                  value={draft.libre_url}
                  onChange={(_, data) => patch({ libre_url: data.value })}
                  placeholder="http://127.0.0.1:5000"
                />
              </label>
              <label className="field">
                <span className="field-label">LibreTranslate API Key</span>
                <Input
                  type="password"
                  value={draft.libre_api_key}
                  onChange={(_, data) => patch({ libre_api_key: data.value })}
                  placeholder="可选"
                />
              </label>
              <label className="field">
                <span className="field-label">Index-Translate 地址</span>
                <Input
                  value={draft.index_url}
                  onChange={(_, data) => patch({ index_url: data.value })}
                  placeholder="https://.../v1"
                />
              </label>
              <label className="field">
                <span className="field-label">Index-Translate Key</span>
                <Input
                  type="password"
                  value={draft.index_api_key}
                  onChange={(_, data) => patch({ index_api_key: data.value })}
                  placeholder="可选"
                />
              </label>
              <label className="field">
                <span className="field-label">Index-Translate 模型</span>
                <Input
                  value={draft.index_model}
                  onChange={(_, data) => patch({ index_model: data.value })}
                  placeholder="Index-Translate"
                />
              </label>
              <label className="field">
                <span className="field-label">混元 Hy-MT2 地址</span>
                <Input
                  value={draft.hunyuan_url}
                  onChange={(_, data) => patch({ hunyuan_url: data.value })}
                  placeholder="https://.../v1"
                />
              </label>
              <label className="field">
                <span className="field-label">混元 API Key</span>
                <Input
                  type="password"
                  value={draft.hunyuan_api_key}
                  onChange={(_, data) => patch({ hunyuan_api_key: data.value })}
                  placeholder="可选"
                />
              </label>
              <label className="field">
                <span className="field-label">混元模型</span>
                <Input
                  value={draft.hunyuan_model}
                  onChange={(_, data) => patch({ hunyuan_model: data.value })}
                  placeholder="hunyuan-mt2"
                />
              </label>
              <label className="field">
                <span className="field-label">Argos 命令</span>
                <Input
                  value={draft.argos_command}
                  onChange={(_, data) => patch({ argos_command: data.value })}
                  placeholder="argos-translate"
                />
              </label>
            </div>
            <div className="inline-note">
              LibreTranslate 与 Argos 走本地 / 局域网服务；Index-Translate、混元与 OpenAI
              兼容网关使用 /v1/chat/completions。API Key 仅保存在本机设置中。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <DocumentTextRegular />
              </div>
              <div>
                <h2>OCR 服务</h2>
                <p>配置 GLM-OCR、OpenAI 兼容视觉服务或本机 Tesseract。</p>
              </div>
            </div>
            <div className="settings-grid">
              <label className="field">
                <span className="field-label">默认 OCR 服务</span>
                <Select
                  value={draft.ocr_provider}
                  onChange={(_, data) => patch({ ocr_provider: data.value })}
                >
                  <option value="auto">自动选择可用服务</option>
                  <option value="glm">GLM-OCR</option>
                  <option value="openai">OpenAI 兼容视觉</option>
                  <option value="tesseract">Tesseract</option>
                </Select>
              </label>
              <label className="field">
                <span className="field-label">GLM Base URL</span>
                <Input
                  value={draft.glm_base_url}
                  onChange={(_, data) => patch({ glm_base_url: data.value })}
                  placeholder="https://open.bigmodel.cn/api/paas/v4"
                />
              </label>
              <label className="field">
                <span className="field-label">GLM API Key</span>
                <Input
                  type="password"
                  value={draft.glm_api_key}
                  onChange={(_, data) => patch({ glm_api_key: data.value })}
                  placeholder="可选"
                />
              </label>
              <label className="field">
                <span className="field-label">GLM OCR 模型</span>
                <Input
                  value={draft.glm_ocr_model}
                  onChange={(_, data) => patch({ glm_ocr_model: data.value })}
                  placeholder="glm-ocr"
                />
              </label>
              <label className="field">
                <span className="field-label">OpenAI 视觉地址</span>
                <Input
                  value={draft.ocr_openai_url}
                  onChange={(_, data) => patch({ ocr_openai_url: data.value })}
                  placeholder="https://.../v1"
                />
              </label>
              <label className="field">
                <span className="field-label">OpenAI 视觉 Key</span>
                <Input
                  type="password"
                  value={draft.ocr_openai_api_key}
                  onChange={(_, data) => patch({ ocr_openai_api_key: data.value })}
                  placeholder="可选"
                />
              </label>
              <label className="field">
                <span className="field-label">OpenAI 视觉模型</span>
                <Input
                  value={draft.ocr_openai_model}
                  onChange={(_, data) => patch({ ocr_openai_model: data.value })}
                  placeholder="gpt-4o-mini"
                />
              </label>
              <label className="field">
                <span className="field-label">Tesseract 命令</span>
                <Input
                  value={draft.tesseract_command}
                  onChange={(_, data) => patch({ tesseract_command: data.value })}
                  placeholder="tesseract"
                />
              </label>
            </div>
            <div className="inline-note">
              GLM-OCR 与 OpenAI 视觉服务使用图片 base64 的 /chat/completions 请求；
              Tesseract 支持本机语言包。API Key 仅保存在本机设置中。
            </div>
          </section>

          <section className="panel settings-card">
            <div className="settings-card-head">
              <div className="settings-icon">
                <PersonRegular />
              </div>
              <div>
                <h2>账户与权限</h2>
                <p>内置轻量账户系统，支持 admin / operator / viewer 三级权限。</p>
              </div>
            </div>
            {!auth?.enabled ? (
              <div className="inline-note">
                账户系统当前未启用。设置 `AIBOX_AUTH_ENABLED=1` 后重启，首次打开 WebUI
                会引导创建管理员；外置登录使用 `AIBOX_AUTH_MODE=external` 和身份头。
              </div>
            ) : auth.user?.role !== 'admin' ? (
              <div className="inline-note">仅管理员可以管理账户。</div>
            ) : (
              <>
                <div className="auth-users">
                  {users.map((item) => (
                    <div className="auth-user-row" key={item.id}>
                      <div>
                        <strong>{item.username}</strong>
                        <span>{item.active ? '启用' : '停用'}</span>
                      </div>
                      <Select
                        value={item.role}
                        onChange={(_, data) => {
                          void api
                            .authUpdateUser(item.id, { role: data.value })
                            .then(loadUsers)
                            .catch((reason) => notify(errorMessage(reason), 'error'));
                        }}
                      >
                        <option value="viewer">viewer</option>
                        <option value="operator">operator</option>
                        <option value="admin">admin</option>
                      </Select>
                      <Button
                        appearance="subtle"
                        size="small"
                        onClick={() => {
                          void api
                            .authUpdateUser(item.id, { active: !item.active })
                            .then(loadUsers)
                            .catch((reason) => notify(errorMessage(reason), 'error'));
                        }}
                      >
                        {item.active ? '停用' : '启用'}
                      </Button>
                      <Button
                        appearance="subtle"
                        size="small"
                        icon={<DeleteRegular />}
                        onClick={() => {
                          void api
                            .authDeleteUser(item.id)
                            .then(loadUsers)
                            .catch((reason) => notify(errorMessage(reason), 'error'));
                        }}
                      />
                    </div>
                  ))}
                </div>
                <div className="auth-user-create">
                  <Input
                    value={newUser}
                    onChange={(_, data) => setNewUser(data.value)}
                    placeholder="用户名"
                  />
                  <Input
                    type="password"
                    value={newPassword}
                    onChange={(_, data) => setNewPassword(data.value)}
                    placeholder="密码（至少 8 位）"
                  />
                  <Select value={newRole} onChange={(_, data) => setNewRole(data.value)}>
                    <option value="viewer">viewer</option>
                    <option value="operator">operator</option>
                    <option value="admin">admin</option>
                  </Select>
                  <Button
                    appearance="primary"
                    icon={<AddRegular />}
                    disabled={!newUser || newPassword.length < 8}
                    onClick={() => {
                      void api
                        .authCreateUser(newUser, newPassword, newRole)
                        .then(() => {
                          setNewUser('');
                          setNewPassword('');
                          return loadUsers();
                        })
                        .catch((reason) => notify(errorMessage(reason), 'error'));
                    }}
                  >
                    添加
                  </Button>
                </div>
              </>
            )}
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
