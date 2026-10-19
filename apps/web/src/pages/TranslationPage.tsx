import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Input,
  Select,
  Spinner,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowSyncRegular,
  CopyRegular,
  DeleteRegular,
  LocalLanguageRegular,
  SendRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { api, errorMessage } from '../api/client';
import type {
  TranslationRecord,
  TranslationStatus,
} from '../api/types';

const SOURCE_FALLBACK = [
  { code: 'auto', name: '自动检测' },
  { code: 'en', name: '英语' },
  { code: 'zh', name: '中文' },
];

const TARGET_FALLBACK = [
  { code: 'zh', name: '中文' },
  { code: 'en', name: '英语' },
];

export function TranslationPage() {
  const [status, setStatus] = useState<TranslationStatus | null>(null);
  const [history, setHistory] = useState<TranslationRecord[]>([]);
  const [text, setText] = useState('');
  const [source, setSource] = useState('auto');
  const [target, setTarget] = useState('zh');
  const [provider, setProvider] = useState('auto');
  const [model, setModel] = useState('');
  const [result, setResult] = useState<TranslationRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [nextStatus, nextHistory] = await Promise.all([
        api.translationStatus(),
        api.translations(),
      ]);
      setStatus(nextStatus);
      setHistory(nextHistory.translations);
      setProvider((current) =>
        current === 'auto' && nextStatus.default_provider !== 'auto'
          ? nextStatus.default_provider
          : current,
      );
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const languages = status?.languages ?? [];
  const sourceLanguages = languages.length ? languages : SOURCE_FALLBACK;
  const targetLanguages = (languages.length ? languages : TARGET_FALLBACK).filter(
    (item) => item.code !== 'auto',
  );
  const providers = status?.providers ?? [];
  const selectedProvider = providers.find((item) => item.id === provider);
  const effectiveProvider = status?.resolved_provider;
  const charCount = text.length;

  const selectedProviderName = useMemo(
    () => selectedProvider?.name ?? (provider === 'auto' ? '自动选择' : provider),
    [provider, selectedProvider],
  );

  const run = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError('');
    setCopied(false);
    try {
      const response = await api.translate({
        text,
        source,
        target,
        provider,
        model: model.trim() || undefined,
      });
      setResult(response.translation);
      setHistory((current) => [
        response.translation,
        ...current.filter((item) => item.id !== response.translation.id),
      ].slice(0, 50));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const swap = () => {
    if (source === 'auto') return;
    setSource(target);
    setTarget(source);
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.translated);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError('复制失败，请手动选择译文。');
    }
  };

  const remove = async (record: TranslationRecord) => {
    try {
      await api.deleteTranslation(record.id);
      setHistory((current) => current.filter((item) => item.id !== record.id));
      if (result?.id === record.id) setResult(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="page translation-page">
      <PageHeader
        title="文本翻译"
        description="连接 LibreTranslate / Argos、Index-Translate 与腾讯混元 Hy-MT2，保留本地工作流和翻译历史。"
        actions={
          <div className="page-actions">
            <StatusPill tone={status?.resolved_provider ? 'success' : 'warning'}>
              {status?.resolved_provider ? '翻译服务可用' : '等待配置'}
            </StatusPill>
            <Button appearance="secondary" icon={<ArrowSyncRegular />} onClick={load}>
              刷新
            </Button>
          </div>
        }
      />

      <div className="translation-layout">
        <section className="panel translation-input-panel">
          <div className="translation-panel-head">
            <div>
              <span className="eyebrow">SOURCE</span>
              <h2>原文</h2>
            </div>
            <span className="translation-char-count">{charCount} / 20000</span>
          </div>

          <div className="translation-language-row">
            <label className="field">
              <span className="field-label">源语言</span>
              <Select value={source} onChange={(_, data) => setSource(data.value)}>
                {sourceLanguages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </label>
            <Button
              className="translation-swap"
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={swap}
              aria-label="交换语言"
            />
            <label className="field">
              <span className="field-label">目标语言</span>
              <Select value={target} onChange={(_, data) => setTarget(data.value)}>
                {targetLanguages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </label>
          </div>

          <Textarea
            className="translation-textarea"
            value={text}
            onChange={(_, data) => setText(data.value)}
            placeholder="粘贴或输入需要翻译的文本…"
            resize="vertical"
            rows={12}
          />

          <div className="translation-provider-grid">
            <label className="field">
              <span className="field-label">翻译服务</span>
              <Select
                value={provider}
                onChange={(_, data) => {
                  setProvider(data.value);
                  setModel('');
                }}
              >
                <option value="auto">
                  自动选择{effectiveProvider ? `（${effectiveProvider}）` : ''}
                </option>
                {providers.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.available}>
                    {item.name}{item.available ? '' : ' · 未配置'}
                  </option>
                ))}
              </Select>
            </label>
            <label className="field">
              <span className="field-label">模型（可选）</span>
              <Input
                value={model}
                onChange={(_, data) => setModel(data.value)}
                placeholder={selectedProvider?.model ?? '使用服务默认模型'}
              />
            </label>
          </div>

          <div className="translation-actions">
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <SendRegular />}
              disabled={busy || !text.trim()}
              onClick={run}
            >
              {busy ? '翻译中…' : '开始翻译'}
            </Button>
            <span className="translation-provider-note">
              {selectedProviderName}
              {selectedProvider && !selectedProvider.available ? ' · 尚未配置' : ''}
            </span>
          </div>
          {error ? <div className="translation-error">{error}</div> : null}
          {status && !status.resolved_provider ? (
            <div className="inline-note">
              还没有可用翻译服务。请在设置中填写 LibreTranslate 地址、Index-Translate /
              混元接口，或启用演示翻译。
            </div>
          ) : null}
        </section>

        <section className="panel translation-output-panel">
          <div className="translation-panel-head">
            <div>
              <span className="eyebrow">TARGET</span>
              <h2>译文</h2>
            </div>
            {result ? (
              <Button
                appearance="subtle"
                size="small"
                icon={<CopyRegular />}
                onClick={copy}
              >
                {copied ? '已复制' : '复制'}
              </Button>
            ) : null}
          </div>

          {loading ? (
            <div className="translation-empty">
              <Spinner label="加载翻译服务…" />
            </div>
          ) : result ? (
            <>
              <div className="translation-result-text">{result.translated}</div>
              <div className="translation-result-meta">
                <span>
                  {providers.find((item) => item.id === result.provider)?.name ??
                    result.provider_name ??
                    result.provider}
                </span>
                <span>{result.model}</span>
                <span>{result.latency_ms} ms</span>
                {result.detected_language ? (
                  <span>检测：{result.detected_language}</span>
                ) : null}
              </div>
            </>
          ) : (
            <div className="translation-empty">
              <div className="translation-empty-orb">
                <LocalLanguageRegular />
              </div>
              <strong>译文会出现在这里</strong>
              <span>选择服务与语言后开始翻译，结果会保存到历史记录。</span>
            </div>
          )}
        </section>
      </div>

      <section className="panel translation-history-panel">
        <div className="translation-panel-head">
          <div>
            <span className="eyebrow">HISTORY</span>
            <h2>翻译记录</h2>
          </div>
          <span className="translation-char-count">{history.length} 条</span>
        </div>
        {history.length === 0 ? (
          <div className="translation-history-empty">还没有翻译记录。</div>
        ) : (
          <div className="translation-history">
            {history.map((item) => (
              <article
                className="translation-history-item"
                key={item.id}
                onClick={() => {
                  setResult(item);
                  setText(item.text);
                  setSource(item.source);
                  setTarget(item.target);
                  setProvider(item.provider);
                  setModel(item.model);
                }}
              >
                <div className="translation-history-line">
                  <span>{item.source}</span>
                  <span>→</span>
                  <span>{item.target}</span>
                  <span className="translation-history-provider">{item.provider}</span>
                </div>
                <p>{item.text}</p>
                <p className="translation-history-translated">{item.translated}</p>
                <Button
                  className="translation-history-delete"
                  appearance="subtle"
                  size="small"
                  icon={<DeleteRegular />}
                  onClick={(event) => {
                    event.stopPropagation();
                    void remove(item);
                  }}
                  aria-label="删除翻译记录"
                />
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
