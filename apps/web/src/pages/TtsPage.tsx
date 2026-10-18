import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Select,
  Slider,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowUploadRegular,
  DeleteRegular,
  MicRegular,
  SparkleRegular,
  Speaker2Regular,
  StopRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { AudioPlayer } from '../components/AudioPlayer';
import { Waveform } from '../components/Waveform';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { VoiceProfile } from '../api/types';
import { formatBytes } from '../utils/format';

const LANGUAGES = [
  ['auto', '自动判断'],
  ['zh', '中文'],
  ['en', '英语'],
  ['ja', '日语'],
  ['es', '西班牙语'],
  ['ar', '阿拉伯语'],
] as const;

const FORMATS = ['wav', 'mp3', 'opus', 'aac', 'flac', 'pcm'] as const;

function statusText(status: string | undefined): string {
  if (status === 'ready') return '引擎就绪';
  if (status === 'demo') return '演示引擎';
  if (status === 'external') return '外部 TTS';
  if (status === 'no-model') return '缺少模型';
  if (status === 'runtime-missing') return '运行时未安装';
  if (status === 'error') return '引擎异常';
  return '检测中';
}

function statusTone(status: string | undefined) {
  if (status === 'ready') return 'success' as const;
  if (status === 'demo') return 'warning' as const;
  if (status === 'external') return 'info' as const;
  if (status === 'runtime-missing' || status === 'no-model') return 'neutral' as const;
  return 'info' as const;
}

export function TtsPage() {
  const { system, models, settings, notify, refreshModels, refreshSystem } = useAppData();
  const navigate = useNavigate();
  const installed = useMemo(
    () => (models?.installed ?? []).filter((model) => model.kind === 'tts'),
    [models],
  );
  const ttsStatus = system?.tts;
  const nativeTtsInstalled = installed.some((model) => model.engine === 'indextts');
  const externalTtsInstalled = installed.some((model) => model.external === true);
  const displayStatus =
    externalTtsInstalled && !nativeTtsInstalled && ttsStatus?.status === 'runtime-missing'
      ? 'external'
      : ttsStatus?.status;
  const [modelId, setModelId] = useState('');
  const [voiceId, setVoiceId] = useState(settings?.tts_default_voice || 'default-en');
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [text, setText] = useState(
    '你好，欢迎使用 AIBox。这段声音由本地的 IndexTTS 模型合成，不需要把文本上传到云端。',
  );
  const [language, setLanguage] = useState('auto');
  const [speed, setSpeed] = useState(1);
  const [format, setFormat] = useState<(typeof FORMATS)[number]>('wav');
  const [generating, setGenerating] = useState(false);
  const [audioUrl, setAudioUrl] = useState('');
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [lastText, setLastText] = useState('');
  const [uploading, setUploading] = useState(false);
  const voiceInputRef = useRef<HTMLInputElement>(null);

  const activeModel = useMemo(
    () => installed.find((model) => model.id === modelId) ?? installed[0] ?? null,
    [installed, modelId],
  );
  const activeVoice = voices.find((voice) => voice.id === voiceId) ?? voices[0] ?? null;
  const canGenerate =
    text.trim().length > 0 &&
    (installed.length > 0 || ttsStatus?.demo === true) &&
    !generating;

  useEffect(() => {
    if (!modelId && installed.length > 0) {
      const preferred =
        settings?.default_tts_model &&
        installed.some((model) => model.id === settings.default_tts_model)
          ? settings.default_tts_model
          : installed[0].id;
      setModelId(preferred);
    }
  }, [installed, settings, modelId]);

  useEffect(() => {
    void api
      .ttsVoices()
      .then((data) => {
        setVoices(data.voices);
        setVoiceId((current) =>
          data.voices.some((voice) => voice.id === current)
            ? current
            : data.voices[0]?.id ?? '',
        );
      })
      .catch(() => undefined);
  }, []);

  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    },
    [audioUrl],
  );

  const generate = async () => {
    if (!canGenerate) return;
    setGenerating(true);
    setWarning(null);
    try {
      const result = await api.ttsSynthesize({
        text: text.trim(),
        model: activeModel?.id ?? 'indextts-2.5',
        voice: voiceId,
        language,
        speed,
        response_format: format,
      });
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      const url = URL.createObjectURL(result.blob);
      setAudioUrl(url);
      setAudioBlob(result.blob);
      setWarning(result.warning === 'demo-engine' ? '演示引擎输出为提示音，请配置 IndexTTS 运行时与模型。' : null);
      setLastText(text.trim());
      notify('语音合成完成', `${format.toUpperCase()} · ${formatBytes(result.blob.size)}`, 'success');
    } catch (err) {
      notify('合成失败', errorMessage(err), 'error');
    } finally {
      setGenerating(false);
    }
  };

  const uploadVoice = async (file: File) => {
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('name', file.name.replace(/\.[^.]+$/, ''));
      form.append('language', language === 'auto' ? 'auto' : language);
      const profile = await api.createTtsVoice(form);
      const list = await api.ttsVoices();
      setVoices(list.voices);
      setVoiceId(profile.id);
      notify('参考音色已保存', `${profile.name} 可用于后续声音克隆。`, 'success');
    } catch (err) {
      notify('上传参考音频失败', errorMessage(err), 'error');
    } finally {
      setUploading(false);
      if (voiceInputRef.current) voiceInputRef.current.value = '';
    }
  };

  const deleteVoice = async (voice: VoiceProfile) => {
    if (voice.source === 'builtin') return;
    try {
      await api.deleteTtsVoice(voice.id);
      const list = await api.ttsVoices();
      setVoices(list.voices);
      if (voiceId === voice.id) setVoiceId(list.voices[0]?.id ?? '');
      notify('音色已删除', voice.name, 'info');
    } catch (err) {
      notify('删除失败', errorMessage(err), 'error');
    }
  };

  const refreshTts = async () => {
    await Promise.allSettled([refreshModels(), refreshSystem()]);
  };

  return (
    <div className="page tts-page">
      <PageHeader
        eyebrow="TEXT TO SPEECH"
        title="语音合成"
        description="用本地 IndexTTS 克隆音色、朗读文本并导出音频。合成请求不会离开本机。"
        actions={
          <>
            <StatusPill tone={statusTone(displayStatus)}>
              {statusText(displayStatus)}
            </StatusPill>
            <Button
              appearance="subtle"
              icon={<Speaker2Regular />}
              onClick={() => void refreshTts()}
            >
              刷新
            </Button>
          </>
        }
      />

      <section className="tts-layout">
        <div className="tts-composer panel">
          <div className="tts-section-head">
            <div>
              <span className="panel-kicker">SCRIPT</span>
              <h2>输入文本</h2>
            </div>
            <span className="tts-count">{text.length} / 8000</span>
          </div>
          <Textarea
            className="tts-textarea"
            value={text}
            onChange={(_, data) => setText(data.value.slice(0, 8000))}
            resize="vertical"
            placeholder="输入要合成的文本…"
          />

          <div className="tts-controls">
            <label className="field">
              <span className="field-label">合成模型</span>
              <Select
                value={activeModel?.id ?? ''}
                onChange={(_, data) => setModelId(data.value)}
                disabled={installed.length === 0}
              >
                {installed.length === 0 ? (
                  <option value="">{ttsStatus?.demo ? '演示引擎（无需模型）' : '未安装 IndexTTS'}</option>
                ) : (
                  installed.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name} · {model.size_label}
                    </option>
                  ))
                )}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">参考音色</span>
              <Select value={voiceId} onChange={(_, data) => setVoiceId(data.value)}>
                {voices.map((voice) => (
                  <option key={voice.id} value={voice.id}>
                    {voice.name} {voice.source === 'builtin' ? '· 内置' : '· 自定义'}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">语言</span>
              <Select value={language} onChange={(_, data) => setLanguage(data.value)}>
                {LANGUAGES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">输出格式</span>
              <Select
                value={format}
                onChange={(_, data) => setFormat(data.value as (typeof FORMATS)[number])}
              >
                {FORMATS.map((item) => (
                  <option key={item} value={item}>
                    {item.toUpperCase()}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <label className="field tts-speed">
            <span className="field-label">
              语速 <strong className="field-value">{speed.toFixed(2)}×</strong>
            </span>
            <Slider
              min={0.5}
              max={2}
              step={0.05}
              value={speed}
              onChange={(_, data) => setSpeed(data.value)}
            />
            <span className="field-hint">0.5× 更慢，2.0× 更快。IndexTTS 2.5 原生支持语速。</span>
          </label>

          <div className="tts-voice-tools">
            <input
              ref={voiceInputRef}
              type="file"
              accept=".wav,.mp3,.m4a,.flac,.ogg,.opus"
              className="visually-hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadVoice(file);
              }}
            />
            <Button
              appearance="secondary"
              icon={uploading ? <Spinner size="tiny" /> : <ArrowUploadRegular />}
              onClick={() => voiceInputRef.current?.click()}
              disabled={uploading}
            >
              上传参考音色
            </Button>
            {activeVoice && (
              <span className="voice-meta">
                {activeVoice.name} · {activeVoice.language} ·{' '}
                {activeVoice.source === 'builtin' ? '内置参考' : '自定义参考'}
              </span>
            )}
          </div>

          <div className="tts-actions">
            <Button
              appearance="primary"
              size="large"
              className="button-glow"
              icon={generating ? <Spinner size="tiny" /> : <SparkleRegular />}
              onClick={() => void generate()}
              disabled={!canGenerate}
            >
              {generating ? '正在合成…' : '生成语音'}
            </Button>
            {installed.length === 0 && !ttsStatus?.demo && (
              <Button appearance="secondary" onClick={() => navigate('/models?kind=tts')}>
                去模型库下载 IndexTTS
              </Button>
            )}
          </div>

          {installed.length === 0 && !ttsStatus?.demo && (
            <div className="inline-note warning-note">
              IndexTTS 运行时与模型尚未安装。可先执行 <code>scripts/setup-indextts.ps1</code>，
              再到模型库下载 IndexTTS 2.5。若只想验证界面，可设置 <code>AIBOX_DEMO_TTS=1</code>。
            </div>
          )}
          {installed.length > 0 && ttsStatus?.status === 'runtime-missing' && nativeTtsInstalled && (
            <div className="inline-note warning-note">
              已安装 IndexTTS 模型，但 IndexTTS 运行时未就绪。请设置 <code>AIBOX_INDEXTTS_HOME</code> 与{' '}
              <code>AIBOX_INDEXTTS_PYTHON</code>，或运行 setup 脚本。
            </div>
          )}
        </div>

        <aside className="tts-output">
          <div className="panel tts-result-panel">
            <div className="tts-section-head">
              <div>
                <span className="panel-kicker">OUTPUT</span>
                <h2>合成结果</h2>
              </div>
              {audioBlob && <StatusPill tone="success">已生成</StatusPill>}
            </div>
            {generating ? (
              <div className="tts-generating">
                <div className="tts-gen-orb">
                  <Waveform bars={24} active compact />
                </div>
                <strong>IndexTTS 正在合成</strong>
                <span>{activeModel?.name ?? '演示引擎'} · {format.toUpperCase()}</span>
              </div>
            ) : audioUrl ? (
              <div className="tts-result">
                <div className="tts-result-top">
                  <div className="tts-result-icon">
                    <Speaker2Regular />
                  </div>
                  <div>
                    <strong>{activeVoice?.name ?? '默认音色'}</strong>
                    <span>
                      {activeModel?.name ?? '演示引擎'} · {format.toUpperCase()} ·{' '}
                      {audioBlob ? formatBytes(audioBlob.size) : '—'}
                    </span>
                  </div>
                  <span className="tts-result-spark">
                    <SparkleRegular />
                  </span>
                </div>
                <AudioPlayer src={audioUrl} />
                <div className="tts-result-text">{lastText}</div>
                {warning && <div className="inline-note warning-note">{warning}</div>}
                <div className="tts-result-actions">
                  <a
                    className="export-chip"
                    href={audioUrl}
                    download={`aibox-tts.${format === 'pcm' ? 'pcm' : format}`}
                  >
                    <ArrowDownloadRegular /> 下载 {format.toUpperCase()}
                  </a>
                  <button
                    type="button"
                    className="text-link"
                    onClick={() => {
                      setAudioUrl('');
                      setAudioBlob(null);
                    }}
                  >
                    <StopRegular /> 清除结果
                  </button>
                </div>
              </div>
            ) : (
              <div className="tts-empty">
                <div className="tts-empty-orb">
                  <Waveform bars={22} active compact />
                </div>
                <h3>让文字拥有声音</h3>
                <p>
                  输入文本，选择参考音色与 IndexTTS 模型，然后点击生成。首次加载模型可能需要数十秒。
                </p>
                <div className="tts-empty-features">
                  <span>本地声音克隆</span>
                  <span>OpenAI TTS 兼容</span>
                  <span>WAV / MP3 / FLAC</span>
                </div>
              </div>
            )}
          </div>

          <div className="panel tts-info-panel">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">RUNTIME</span>
                <h3>IndexTTS 运行时</h3>
              </div>
              <StatusPill tone={statusTone(displayStatus)}>
                {statusText(displayStatus)}
              </StatusPill>
            </div>
            <div className="tts-runtime-facts">
              <div>
                <span>引擎</span>
                <strong>{ttsStatus?.engine ?? 'indextts'}</strong>
              </div>
              <div>
                <span>已加载模型</span>
                <strong>{ttsStatus?.loaded_model ?? '—'}</strong>
              </div>
              <div>
                <span>可用模型</span>
                <strong>{installed.length || ttsStatus?.installed_models.length || 0} 个</strong>
              </div>
              <div>
                <span>音色</span>
                <strong>{voices.length} 个</strong>
              </div>
            </div>
            <div className="tts-info-note">
              <Speaker2Regular />
              <span>
                IndexTTS 通过独立 Python worker 加载，避免与 ASR 的 CTranslate2 依赖冲突。
                弹性调度会在显存/内存不足时按策略换入换出。
              </span>
            </div>
          </div>

          <div className="panel tts-custom-voices">
            <div className="panel-heading">
              <div>
                <span className="panel-kicker">VOICES</span>
                <h3>我的音色</h3>
              </div>
              <Button
                appearance="subtle"
                size="small"
                icon={<ArrowUploadRegular />}
                onClick={() => voiceInputRef.current?.click()}
              >
                添加
              </Button>
            </div>
            <div className="voice-list">
              {voices.map((voice) => (
                <button
                  type="button"
                  key={voice.id}
                  className={`voice-row${voice.id === voiceId ? ' is-active' : ''}`}
                  onClick={() => setVoiceId(voice.id)}
                >
                  <span className="voice-dot">
                    <MicRegular />
                  </span>
                  <span className="voice-name">
                    <strong>{voice.name}</strong>
                    <small>{voice.source === 'builtin' ? '内置参考音' : voice.language}</small>
                  </span>
                  {voice.source !== 'builtin' && (
                    <span
                      className="voice-delete"
                      role="button"
                      tabIndex={0}
                      onClick={(event) => {
                        event.stopPropagation();
                        void deleteVoice(voice);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.stopPropagation();
                          void deleteVoice(voice);
                        }
                      }}
                      aria-label={`删除 ${voice.name}`}
                    >
                      <DeleteRegular />
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}
