import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  Input,
  Select,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowSyncRegular,
  DeleteRegular,
  SendRegular,
  SparkleRegular,
  StopRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type { ChatMessage, LLMStatus } from '../api/types';

function statusLabel(status: LLMStatus | null): string {
  if (!status) return '检测中';
  if (status.demo) return '演示引擎';
  if (status.provider_setting === 'openai') return 'OpenAI 兼容';
  if (status.provider_setting === 'llama-cpp') return 'llama.cpp';
  if (status.external.configured) return 'OpenAI 兼容';
  if (status.llama_server) return 'llama.cpp';
  return '未配置';
}

function statusTone(status: LLMStatus | null) {
  if (!status) return 'neutral' as const;
  if (status.demo) return 'warning' as const;
  if (status.llama_server || status.external.configured) return 'success' as const;
  return 'neutral' as const;
}

const SUGGESTIONS = [
  '用三句话解释什么是 Elasticsearch',
  '帮我写一封简洁的英文商务邮件',
  '把这段需求拆成可执行的任务清单',
  '比较 Qwen 和 Llama 的本地部署差异',
];

export function ChatPage() {
  const { system, settings, notify } = useAppData();
  const [status, setStatus] = useState<LLMStatus | null>(system?.llm ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [temperature, setTemperature] = useState(settings?.llm_temperature ?? 0.7);
  const [maxTokens, setMaxTokens] = useState(settings?.llm_max_tokens ?? 1024);
  const [systemPrompt, setSystemPrompt] = useState(settings?.llm_system_prompt ?? '');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const modelOptions = useMemo(() => {
    const options: Array<{ id: string; label: string }> = [];
    for (const item of status?.models ?? []) {
      options.push({ id: item.id, label: `${item.name} · 本地` });
    }
    for (const id of status?.external.models ?? []) {
      if (!options.some((item) => item.id === id)) {
        options.push({ id, label: `${id} · 外部` });
      }
    }
    if (status?.demo && !options.length) {
      options.push({
        id: status.recommended_model || 'qwen3-8b',
        label: `${status.recommended_model || 'qwen3-8b'} · 演示`,
      });
    }
    return options;
  }, [status]);

  const load = async () => {
    setLoading(true);
    try {
      const next = await api.llmStatus();
      setStatus(next);
      setModel((current) =>
        current ||
        next.installed_models[0] ||
        next.external.models[0] ||
        next.recommended_model,
      );
    } catch (err) {
      notify('读取语言模型失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, busy]);

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  };

  const clear = () => {
    stop();
    setMessages([]);
  };

  const run = async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    if (!model) {
      notify('请选择模型', '先在模型库下载 GGUF，或配置外部 OpenAI 兼容服务。', 'error');
      return;
    }
    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: 'user', content },
    ];
    setMessages([...nextMessages, { role: 'assistant', content: '' }]);
    setInput('');
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await fetch(api.url('/api/llm/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model,
          messages: nextMessages,
          stream: true,
          temperature,
          max_tokens: maxTokens,
          system_prompt: systemPrompt,
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let answer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() ?? '';
        for (const event of events) {
          const line = event
            .split('\n')
            .find((item) => item.startsWith('data:'));
          if (!line) continue;
          const data = line.slice(5).trim();
          if (!data || data === '[DONE]') continue;
          const chunk = JSON.parse(data) as {
            error?: { message?: string };
            choices?: Array<{ delta?: { content?: string } }>;
          };
          if (chunk.error?.message) throw new Error(chunk.error.message);
          const delta = chunk.choices?.[0]?.delta?.content ?? '';
          if (!delta) continue;
          answer += delta;
          setMessages((items) => {
            const copy = [...items];
            copy[copy.length - 1] = { role: 'assistant', content: answer };
            return copy;
          });
        }
      }
      if (!answer) {
        setMessages((items) => {
          const copy = [...items];
          copy[copy.length - 1] = {
            role: 'assistant',
            content: '模型没有返回内容。',
          };
          return copy;
        });
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') {
        setMessages((items) => {
          const copy = [...items];
          const last = copy[copy.length - 1];
          if (last?.role === 'assistant' && !last.content) {
            copy[copy.length - 1] = { role: 'assistant', content: '已停止生成。' };
          }
          return copy;
        });
      } else {
        notify('对话失败', errorMessage(err), 'error');
        setMessages((items) => {
          const copy = [...items];
          copy[copy.length - 1] = {
            role: 'assistant',
            content: `请求失败：${errorMessage(err)}`,
          };
          return copy;
        });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  };

  const unload = async () => {
    try {
      await api.llmUnload();
      notify('模型已卸载', '下次对话会重新加载。', 'info');
      await load();
    } catch (err) {
      notify('卸载失败', errorMessage(err), 'error');
    }
  };

  return (
    <div className="page chat-page">
      <PageHeader
        eyebrow="LANGUAGE MODELS"
        title="语言模型"
        description="本地 GGUF 或任意 OpenAI 兼容服务。默认只保留一个输入框；系统提示、温度和长度放在高级设置。"
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

      <section className="chat-layout">
        <div className="panel chat-side">
          <div className="images-section-head">
            <div>
              <span className="panel-kicker">RUNTIME</span>
              <h2>模型与参数</h2>
            </div>
            {loading && <Spinner size="tiny" />}
          </div>

          <label className="field">
            <span className="field-label">模型</span>
            <Select value={model} onChange={(_, data) => setModel(data.value)}>
              {modelOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </Select>
            <span className="field-hint">
              {status?.loaded_model
                ? `已加载：${status.loaded_model}`
                : '本地模型首次对话会自动加载 llama-server。'}
            </span>
          </label>

          <div className="chat-runtime">
            <div>
              <span>Provider</span>
              <strong>{statusLabel(status)}</strong>
            </div>
            <div>
              <span>上下文</span>
              <strong>{status?.context ? `${Math.round(status.context / 1024)}K` : '—'}</strong>
            </div>
            <div>
              <span>本地模型</span>
              <strong>{status?.installed_models.length ?? 0}</strong>
            </div>
          </div>

          {!status?.demo && !status?.llama_server && !status?.external.configured && (
            <div className="inline-note warning-note">
              <WarningRegular /> 还没有可用的语言模型。请在模型库下载 GGUF，
              安装 llama-server，或设置 <code>AIBOX_LLM_BASE_URL</code>。
            </div>
          )}

          <details
            className="images-disclosure"
            open={advancedOpen}
            onToggle={(event) =>
              setAdvancedOpen((event.currentTarget as HTMLDetailsElement).open)
            }
          >
            <summary>高级设置</summary>
            <div className="chat-advanced">
              <label className="field">
                <span className="field-label">系统提示</span>
                <Textarea
                  value={systemPrompt}
                  onChange={(_, data) => setSystemPrompt(data.value)}
                  resize="vertical"
                  placeholder="例如：你是简洁、准确的中文助手。"
                />
              </label>
              <div className="chat-advanced-row">
                <label className="field">
                  <span className="field-label">温度 · {temperature.toFixed(1)}</span>
                  <Input
                    type="number"
                    value={String(temperature)}
                    onChange={(_, data) =>
                      setTemperature(Math.max(0, Math.min(2, Number(data.value) || 0)))
                    }
                  />
                </label>
                <label className="field">
                  <span className="field-label">最大 Token</span>
                  <Input
                    type="number"
                    value={String(maxTokens)}
                    onChange={(_, data) =>
                      setMaxTokens(Math.max(1, Math.min(32768, Number(data.value) || 1)))
                    }
                  />
                </label>
              </div>
            </div>
          </details>

          <div className="chat-side-actions">
            <Button appearance="secondary" icon={<DeleteRegular />} onClick={clear}>
              新对话
            </Button>
            <Button appearance="subtle" onClick={() => void unload()} disabled={!status?.loaded_model}>
              卸载模型
            </Button>
          </div>

          <div className="chat-engine-note">
            {status?.llama_server && <span>llama-server：{status.llama_server}</span>}
            {status?.external.configured && <span>外部：{status.external.base_url}</span>}
            {status?.demo && <span>演示模式：AIBOX_DEMO_LLM=1</span>}
          </div>
        </div>

        <div className="panel chat-main">
          <div className="chat-thread">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty-orb">
                  <SparkleRegular />
                </div>
                <h2>开始一段本地对话</h2>
                <p>
                  模型与上下文留在本机。选择一个已安装模型，或连接 Ollama / LM Studio / vLLM。
                </p>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((item) => (
                    <button key={item} type="button" onClick={() => void run(item)}>
                      {item}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="chat-messages">
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={`chat-message chat-message-${message.role}`}
                  >
                    <span className="chat-role">
                      {message.role === 'user' ? '你' : message.role === 'system' ? '系统' : 'AIBox'}
                    </span>
                    <div className="chat-bubble">
                      {message.content || (busy && index === messages.length - 1 ? '…' : '')}
                    </div>
                  </div>
                ))}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="chat-composer">
            <Textarea
              className="chat-input"
              value={input}
              onChange={(_, data) => setInput(data.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void run(input);
                }
              }}
              placeholder="输入消息，Enter 发送，Shift+Enter 换行…"
              resize="none"
              disabled={busy}
            />
            <div className="chat-composer-actions">
              <span>{input.length} 字符</span>
              {busy ? (
                <Button appearance="secondary" icon={<StopRegular />} onClick={stop}>
                  停止
                </Button>
              ) : (
                <Button
                  appearance="primary"
                  className="button-glow"
                  icon={<SendRegular />}
                  disabled={!input.trim() || !model}
                  onClick={() => void run(input)}
                >
                  发送
                </Button>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
