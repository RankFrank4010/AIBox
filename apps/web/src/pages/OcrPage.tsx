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
  CopyRegular,
  DeleteRegular,
  DocumentTextRegular,
  FolderOpenRegular,
  SendRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { api, errorMessage } from '../api/client';
import type { OcrRecord, OcrStatus } from '../api/types';

const FALLBACK_LANGUAGES = [
  { code: 'auto', name: '自动' },
  { code: 'zh', name: '中文' },
  { code: 'en', name: '英语' },
];

export function OcrPage() {
  const [status, setStatus] = useState<OcrStatus | null>(null);
  const [history, setHistory] = useState<OcrRecord[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [provider, setProvider] = useState('auto');
  const [model, setModel] = useState('');
  const [language, setLanguage] = useState('auto');
  const [result, setResult] = useState<OcrRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [nextStatus, nextHistory] = await Promise.all([
        api.ocrStatus(),
        api.ocrHistory(),
      ]);
      setStatus(nextStatus);
      setHistory(nextHistory.records);
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

  useEffect(() => {
    if (!file) {
      setPreview('');
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const languages = status?.languages?.length ? status.languages : FALLBACK_LANGUAGES;
  const providers = status?.providers ?? [];
  const selectedProvider = providers.find((item) => item.id === provider);
  const effectiveProvider = status?.resolved_provider;

  const providerLabel = useMemo(
    () =>
      providers.find((item) => item.id === result?.provider)?.name ??
      result?.provider ??
      '',
    [providers, result],
  );

  const chooseFile = (next: File | null) => {
    setError('');
    setResult(null);
    if (!next) {
      setFile(null);
      return;
    }
    if (!next.type.startsWith('image/')) {
      setError('请选择 PNG / JPEG / WebP / BMP / TIFF 图片。');
      return;
    }
    if (next.size > 20 * 1024 * 1024) {
      setError('图片不能超过 20 MB。');
      return;
    }
    setFile(next);
  };

  const run = async () => {
    if (!file || busy) return;
    setBusy(true);
    setError('');
    setCopied(false);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('provider', provider);
      form.append('model', model.trim());
      form.append('language', language);
      const response = await api.runOcr(form);
      setResult(response.record);
      setHistory((current) => [
        response.record,
        ...current.filter((item) => item.id !== response.record.id),
      ].slice(0, 50));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError('复制失败，请手动选择识别结果。');
    }
  };

  const remove = async (record: OcrRecord) => {
    try {
      await api.deleteOcr(record.id);
      setHistory((current) => current.filter((item) => item.id !== record.id));
      if (result?.id === record.id) setResult(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <div className="page ocr-page">
      <PageHeader
        title="图片文字识别"
        description="上传截图、扫描件或照片，使用 GLM-OCR、OpenAI 兼容视觉服务或 Tesseract 提取文字。"
        actions={
          <div className="page-actions">
            <StatusPill tone={status?.resolved_provider ? 'success' : 'warning'}>
              {status?.resolved_provider ? 'OCR 服务可用' : '等待配置'}
            </StatusPill>
            <Button appearance="secondary" icon={<ArrowSyncRegular />} onClick={load}>
              刷新
            </Button>
          </div>
        }
      />

      <div className="ocr-layout">
        <section className="panel ocr-upload-panel">
          <div className="ocr-panel-head">
            <div>
              <span className="eyebrow">IMAGE</span>
              <h2>选择图片</h2>
            </div>
            <span className="ocr-file-name">{file?.name ?? '未选择文件'}</span>
          </div>

          <button
            type="button"
            className={`ocr-dropzone${preview ? ' has-preview' : ''}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              chooseFile(event.dataTransfer.files?.[0] ?? null);
            }}
          >
            {preview ? (
              <img src={preview} alt="待识别图片" />
            ) : (
              <>
                <FolderOpenRegular />
                <strong>点击选择或拖入图片</strong>
                <span>PNG / JPEG / WebP / BMP / TIFF · 最大 20 MB</span>
              </>
            )}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff"
            hidden
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />

          <div className="ocr-options">
            <label className="field">
              <span className="field-label">OCR 服务</span>
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
              <span className="field-label">语言</span>
              <Select value={language} onChange={(_, data) => setLanguage(data.value)}>
                {languages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
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

          <div className="ocr-actions">
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <SendRegular />}
              disabled={busy || !file}
              onClick={run}
            >
              {busy ? '识别中…' : '开始识别'}
            </Button>
            <span className="ocr-hint">
              {selectedProvider?.name ?? '自动选择'}
              {status && !status.resolved_provider ? ' · 请先配置服务' : ''}
            </span>
          </div>
          {error ? <div className="ocr-error">{error}</div> : null}
        </section>

        <section className="panel ocr-result-panel">
          <div className="ocr-panel-head">
            <div>
              <span className="eyebrow">TEXT</span>
              <h2>识别结果</h2>
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
            <div className="ocr-empty">
              <Spinner label="加载 OCR 服务…" />
            </div>
          ) : result ? (
            <>
              <Textarea
                className="ocr-result-text"
                value={result.text}
                readOnly
                resize="vertical"
                rows={18}
              />
              <div className="ocr-result-meta">
                <span>{providerLabel}</span>
                <span>{result.model}</span>
                <span>{result.latency_ms} ms</span>
                <span>{result.language}</span>
              </div>
            </>
          ) : (
            <div className="ocr-empty">
              <div className="ocr-empty-orb">
                <DocumentTextRegular />
              </div>
              <strong>识别结果会出现在这里</strong>
              <span>上传图片并选择服务，结果会同时保存到历史记录。</span>
            </div>
          )}
        </section>
      </div>

      <section className="panel ocr-history-panel">
        <div className="ocr-panel-head">
          <div>
            <span className="eyebrow">HISTORY</span>
            <h2>识别记录</h2>
          </div>
          <span className="ocr-file-name">{history.length} 条</span>
        </div>
        {history.length === 0 ? (
          <div className="ocr-history-empty">还没有 OCR 记录。</div>
        ) : (
          <div className="ocr-history">
            {history.map((item) => (
              <article
                className="ocr-history-item"
                key={item.id}
                onClick={() => {
                  setResult(item);
                  setLanguage(item.language);
                  setProvider(item.provider);
                  setModel(item.model);
                }}
              >
                <img src={item.image_url} alt={item.filename} />
                <div>
                  <div className="ocr-history-meta">
                    <span>{item.filename}</span>
                    <span>{item.provider}</span>
                  </div>
                  <p>{item.text}</p>
                </div>
                <Button
                  className="ocr-history-delete"
                  appearance="subtle"
                  size="small"
                  icon={<DeleteRegular />}
                  onClick={(event) => {
                    event.stopPropagation();
                    void remove(item);
                  }}
                  aria-label="删除 OCR 记录"
                />
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
