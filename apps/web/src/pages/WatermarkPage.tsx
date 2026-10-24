import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Select,
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  DeleteRegular,
  EraserRegular,
  ImageRegular,
  VideoRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { api, errorMessage } from '../api/client';
import type { WatermarkRecord, WatermarkRegion, WatermarkStatus } from '../api/types';

type Kind = 'image' | 'video';

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function WatermarkPage() {
  const [status, setStatus] = useState<WatermarkStatus | null>(null);
  const [history, setHistory] = useState<WatermarkRecord[]>([]);
  const [kind, setKind] = useState<Kind>('image');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [regions, setRegions] = useState<WatermarkRegion[]>([]);
  const [drawing, setDrawing] = useState<WatermarkRegion | null>(null);
  const [provider, setProvider] = useState('auto');
  const [result, setResult] = useState<WatermarkRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);

  const load = async () => {
    try {
      const [next, records] = await Promise.all([
        api.watermarkStatus(),
        api.watermarkHistory(),
      ]);
      setStatus(next);
      setHistory(records.records);
    } catch (reason) {
      setError(errorMessage(reason));
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

  const chooseFile = (next: File | null) => {
    setError('');
    setResult(null);
    setRegions([]);
    if (!next) {
      setFile(null);
      return;
    }
    const image = next.type.startsWith('image/');
    const video = next.type.startsWith('video/');
    if ((kind === 'image' && !image) || (kind === 'video' && !video)) {
      setError(kind === 'image' ? '请选择图片文件。' : '请选择视频文件。');
      return;
    }
    setFile(next);
  };

  const point = (event: React.PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const startDraw = (event: React.PointerEvent<HTMLDivElement>) => {
    if (busy) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const p = point(event);
    setDrawing({ x: p.x, y: p.y, w: 0, h: 0 });
  };

  const moveDraw = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drawing) return;
    const p = point(event);
    setDrawing({
      x: Math.min(drawing.x, p.x),
      y: Math.min(drawing.y, p.y),
      w: Math.abs(p.x - drawing.x),
      h: Math.abs(p.y - drawing.y),
    });
  };

  const endDraw = () => {
    if (!drawing) return;
    if (drawing.w > 0.01 && drawing.h > 0.01) {
      setRegions((current) => [...current, drawing].slice(0, 16));
    }
    setDrawing(null);
  };

  const run = async () => {
    if (!file || busy) return;
    if (regions.length === 0) {
      setError('请先在图片或视频上框选水印区域。');
      return;
    }
    setBusy(true);
    setProgress(0);
    setError('');
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('provider', provider);
      form.append('regions', JSON.stringify(regions));
      if (kind === 'image') {
        const record = await api.runWatermarkImage(form);
        setResult(record);
        setProgress(1);
      } else {
        const created = await api.runWatermarkVideo(form);
        let current = created;
        const deadline = Date.now() + 10 * 60 * 1000;
        while (current.status !== 'completed' && current.status !== 'failed') {
          if (Date.now() > deadline) throw new Error('视频处理超时。');
          await sleep(1200);
          current = await api.watermarkRecord(created.id);
          setResult(current);
          setProgress(Math.round((current.progress || 0) * 100));
        }
        if (current.status === 'failed') {
          throw new Error(current.error || '视频去水印失败。');
        }
        setResult(current);
      }
      await load();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (record: WatermarkRecord) => {
    try {
      await api.deleteWatermark(record.id);
      setHistory((current) => current.filter((item) => item.id !== record.id));
      if (result?.id === record.id) setResult(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  const resultUrl = result?.output_url ?? '';

  return (
    <div className="page watermark-page">
      <PageHeader
        title="AI 去水印"
        description="框选图片或视频中的水印区域，使用 IOPaint / LaMa 或本地修复引擎重建背景。"
        actions={
          <div className="page-actions">
            <StatusPill tone={status?.ffmpeg ? 'success' : 'warning'}>
              {status?.ffmpeg ? '视频引擎就绪' : '缺少 ffmpeg'}
            </StatusPill>
            <Button appearance="secondary" icon={<ArrowSyncRegular />} onClick={load}>
              刷新
            </Button>
          </div>
        }
      />

      <div className="watermark-tabs">
        <button
          className={kind === 'image' ? 'active' : ''}
          onClick={() => {
            setKind('image');
            setFile(null);
            setRegions([]);
            setResult(null);
          }}
        >
          <ImageRegular /> 图片去水印
        </button>
        <button
          className={kind === 'video' ? 'active' : ''}
          onClick={() => {
            setKind('video');
            setFile(null);
            setRegions([]);
            setResult(null);
          }}
        >
          <VideoRegular /> 视频去水印
        </button>
      </div>

      <div className="watermark-layout">
        <section className="panel watermark-editor">
          <div className="watermark-toolbar">
            <Button
              appearance="secondary"
              icon={<ImageRegular />}
              onClick={() => inputRef.current?.click()}
            >
              选择{kind === 'image' ? '图片' : '视频'}
            </Button>
            <Button
              appearance="subtle"
              disabled={!regions.length}
              onClick={() => setRegions([])}
            >
              清除框选
            </Button>
            <span className="watermark-file">{file?.name ?? '未选择文件'}</span>
          </div>
          <input
            ref={inputRef}
            type="file"
            hidden
            accept={kind === 'image' ? 'image/png,image/jpeg,image/webp,image/bmp' : 'video/mp4,video/webm,video/quicktime,video/x-matroska'}
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />

          <div className="watermark-stage-wrap">
            {preview ? (
              <div
                className="watermark-stage"
                ref={stageRef}
                onPointerDown={startDraw}
                onPointerMove={moveDraw}
                onPointerUp={endDraw}
                onPointerCancel={endDraw}
              >
                {kind === 'image' ? (
                  <img src={preview} alt="去水印输入" draggable={false} />
                ) : (
                  <video src={preview} controls playsInline />
                )}
                <div className="watermark-overlay">
                  {regions.map((region, index) => (
                    <span
                      key={`${region.x}-${region.y}-${index}`}
                      style={{
                        left: `${region.x * 100}%`,
                        top: `${region.y * 100}%`,
                        width: `${region.w * 100}%`,
                        height: `${region.h * 100}%`,
                      }}
                    />
                  ))}
                  {drawing ? (
                    <span
                      className="active"
                      style={{
                        left: `${drawing.x * 100}%`,
                        top: `${drawing.y * 100}%`,
                        width: `${drawing.w * 100}%`,
                        height: `${drawing.h * 100}%`,
                      }}
                    />
                  ) : null}
                </div>
              </div>
            ) : (
              <button className="watermark-empty" onClick={() => inputRef.current?.click()}>
                <EraserRegular />
                <strong>拖入或选择{kind === 'image' ? '图片' : '视频'}</strong>
                <span>在预览上拖动框选水印区域</span>
              </button>
            )}
          </div>

          <div className="watermark-options">
            <label className="field">
              <span className="field-label">修复服务</span>
              <Select value={provider} onChange={(_, data) => setProvider(data.value)}>
                {(status?.providers ?? []).map((item) => (
                  <option value={item.id} key={item.id} disabled={!item.available}>
                    {item.name}{item.available ? '' : ' · 未连接'}
                  </option>
                ))}
              </Select>
            </label>
            <div className="watermark-hint">
              已框选 {regions.length} 个区域。视频会逐帧修复并保留原音轨。
            </div>
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : <EraserRegular />}
              disabled={busy || !file || regions.length === 0}
              onClick={run}
            >
              {busy ? `处理中 ${progress}%` : '开始去水印'}
            </Button>
          </div>
          {error ? <div className="watermark-error">{error}</div> : null}
        </section>

        <section className="panel watermark-result">
          <div className="watermark-result-head">
            <div>
              <span className="eyebrow">RESULT</span>
              <h2>修复结果</h2>
            </div>
            {result?.output_url ? (
              <a
                className="watermark-download"
                href={result.output_url}
                download
              >
                <ArrowDownloadRegular /> 下载
              </a>
            ) : null}
          </div>
          {busy && kind === 'video' ? (
            <div className="watermark-progress">
              <div style={{ width: `${progress}%` }} />
              <span>{progress}%</span>
            </div>
          ) : null}
          {resultUrl ? (
            kind === 'image' ? (
              <img className="watermark-output" src={resultUrl} alt="去水印结果" />
            ) : (
              <video className="watermark-output" src={resultUrl} controls />
            )
          ) : (
            <div className="watermark-empty result">
              <EraserRegular />
              <strong>结果会出现在这里</strong>
              <span>框选区域后开始处理。</span>
            </div>
          )}
          <div className="watermark-meta">
            {result ? (
              <>
                <span>{result.provider}</span>
                <span>{result.status}</span>
                <span>{result.created_at}</span>
              </>
            ) : null}
          </div>
        </section>
      </div>

      <section className="panel watermark-history">
        <div className="watermark-result-head">
          <div>
            <span className="eyebrow">HISTORY</span>
            <h2>去水印记录</h2>
          </div>
          <span className="watermark-file">{history.length} 条</span>
        </div>
        {history.length === 0 ? (
          <div className="watermark-empty small">还没有去水印记录。</div>
        ) : (
          <div className="watermark-history-list">
            {history.map((item) => (
              <div
                className="watermark-history-item"
                key={item.id}
                onClick={() => {
                  setKind(item.kind);
                  setResult(item);
                }}
              >
                {item.kind === 'image' ? <ImageRegular /> : <VideoRegular />}
                <span>{item.filename}</span>
                <span>{item.provider}</span>
                <span className={`watermark-status is-${item.status}`}>{item.status}</span>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<DeleteRegular />}
                  onClick={(event) => {
                    event.stopPropagation();
                    void remove(item);
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
