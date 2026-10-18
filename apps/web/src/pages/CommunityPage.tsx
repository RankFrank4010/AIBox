import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Input,
  Spinner,
  Switch,
  Textarea,
} from '@fluentui/react-components';
import {
  ArrowDownloadRegular,
  ArrowSyncRegular,
  CheckmarkRegular,
  CodeRegular,
  CopyRegular,
  DeleteRegular,
  DocumentTextRegular,
  MicRegular,
  PeopleCommunityRegular,
  SearchRegular,
  Speaker2Regular,
  WarningRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { EmptyState } from '../components/EmptyState';
import { useAppData } from '../state/AppContext';
import { api, errorMessage } from '../api/client';
import type {
  CommunityAdapter,
  CommunityPayload,
  CommunityTemplate,
} from '../api/types';

type KindFilter = 'all' | 'asr' | 'tts';

const KIND_LABEL: Record<string, string> = { asr: '语音识别', tts: '语音合成' };
const STATUS_LABEL: Record<string, string> = {
  ready: '已就绪',
  disabled: '已停用',
  'needs-command-gate': '需要命令开关',
  'needs-remote-gate': '需要远程开关',
  invalid: '配置无效',
};

function statusTone(status: string) {
  if (status === 'ready') return 'success' as const;
  if (status === 'disabled') return 'neutral' as const;
  if (status === 'invalid') return 'danger' as const;
  return 'warning' as const;
}

export function CommunityPage() {
  const { system, notify, refreshModels, refreshSystem } = useAppData();
  const [payload, setPayload] = useState<CommunityPayload | null>(
    system?.community ?? null,
  );
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState<KindFilter>('all');
  const [search, setSearch] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [manifest, setManifest] = useState('');
  const [importing, setImporting] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async (showSpinner = true) => {
    if (showSpinner) setLoading(true);
    try {
      setPayload(await api.community());
    } catch (err) {
      notify('读取社区适配失败', errorMessage(err), 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const templates = useMemo(
    () =>
      (payload?.templates ?? []).filter((item) => {
        if (kind !== 'all' && item.kind !== kind) return false;
        if (!search.trim()) return true;
        const hay = `${item.name} ${item.description} ${item.tags.join(' ')} ${item.source}`;
        return hay.toLowerCase().includes(search.trim().toLowerCase());
      }),
    [payload, kind, search],
  );
  const adapters = useMemo(
    () =>
      (payload?.adapters ?? []).filter((item) => {
        if (kind !== 'all' && item.kind !== kind) return false;
        if (!search.trim()) return true;
        const hay = `${item.name} ${item.description} ${item.id} ${item.adapter_type}`;
        return hay.toLowerCase().includes(search.trim().toLowerCase());
      }),
    [payload, kind, search],
  );

  const openImport = (text = '') => {
    setManifest(text);
    setImportOpen(true);
  };

  const useTemplate = async (template: CommunityTemplate) => {
    try {
      const data = await api.communityTemplate(template.id);
      openImport(JSON.stringify(data, null, 2));
      notify(
        '已载入模板',
        '请按本机实际路径/服务地址修改 adapter，然后导入。模板默认停用。',
        'info',
      );
    } catch (err) {
      notify('读取模板失败', errorMessage(err), 'error');
    }
  };

  const submitImport = async () => {
    if (!manifest.trim()) return;
    setImporting(true);
    try {
      const adapter = await api.importCommunityAdapter(manifest);
      setImportOpen(false);
      await Promise.all([load(false), refreshModels(), refreshSystem()]);
      notify(
        '适配器已导入',
        `${adapter.name} 默认停用；确认配置后打开开关即可出现在模型库。`,
        'success',
      );
    } catch (err) {
      notify('导入适配器失败', errorMessage(err), 'error');
    } finally {
      setImporting(false);
    }
  };

  const toggle = async (adapter: CommunityAdapter, enabled: boolean) => {
    setToggling(adapter.id);
    try {
      const next = await api.toggleCommunityAdapter(adapter.id, enabled);
      await Promise.all([load(false), refreshModels(), refreshSystem()]);
      if (enabled && next.status !== 'ready') {
        notify('适配器仍未就绪', next.error ?? STATUS_LABEL[next.status] ?? next.status, 'warning');
      } else {
        notify(
          enabled ? '适配器已启用' : '适配器已停用',
          enabled ? `${next.name} 已加入模型库。` : `${next.name} 已从模型库移除。`,
          'info',
        );
      }
    } catch (err) {
      notify('更新适配器失败', errorMessage(err), 'error');
    } finally {
      setToggling(null);
    }
  };

  const remove = async (adapter: CommunityAdapter) => {
    if (!window.confirm(`删除适配器「${adapter.name}」？这不会删除外部模型文件或服务。`)) {
      return;
    }
    try {
      await api.deleteCommunityAdapter(adapter.id);
      await Promise.all([load(false), refreshModels(), refreshSystem()]);
      notify('适配器已删除', adapter.name, 'info');
    } catch (err) {
      notify('删除适配器失败', errorMessage(err), 'error');
    }
  };

  const summary = payload?.summary;
  const security = payload?.security;

  return (
    <div className="page community-page">
      <PageHeader
        eyebrow="COMMUNITY ADAPTERS"
        title="社区适配"
        description="用声明式适配器把 FunASR、Moonshine、Piper、Kokoro、CosyVoice、F5-TTS 等模型接入 AIBox，不需要修改 AIBox 源码。"
        actions={
          <>
            <Button
              appearance="subtle"
              icon={<ArrowSyncRegular />}
              onClick={() => void load()}
            >
              刷新
            </Button>
            <Button
              appearance="primary"
              icon={<ArrowDownloadRegular />}
              onClick={() => openImport()}
            >
              导入适配器
            </Button>
          </>
        }
      />

      <section className="community-summary">
        <div className="panel community-stat">
          <span>内置配方</span>
          <strong>{summary?.templates ?? 0}</strong>
          <small>覆盖主流 ASR / TTS</small>
        </div>
        <div className="panel community-stat">
          <span>已导入适配器</span>
          <strong>{summary?.adapters ?? 0}</strong>
          <small>{summary?.enabled ?? 0} 个已启用</small>
        </div>
        <div className="panel community-stat">
          <span>已就绪</span>
          <strong>{summary?.ready ?? 0}</strong>
          <small>可直接服务请求</small>
        </div>
        <div className="panel community-stat security-stat">
          <span>安全开关</span>
          <strong>{security?.allow_commands ? '命令已放行' : '命令默认禁用'}</strong>
          <small>
            {security?.allow_remote ? '允许远程 HTTP' : '仅本机 / 局域网 HTTP'}
          </small>
        </div>
      </section>

      <section className="panel community-security">
        <div className="security-icon">
          <WarningRegular />
        </div>
        <div>
          <strong>社区适配器是可执行扩展，请只启用可信来源。</strong>
          <p>
            命令适配器会启动本机进程，默认需要 <code>AIBOX_ALLOW_ADAPTER_COMMANDS=1</code>；
            远程 HTTP 适配器需要 <code>AIBOX_ALLOW_REMOTE_ADAPTERS=1</code>。
            导入的适配器默认停用，启用后其模型会出现在模型库。适配器目录：{' '}
            <code>{security?.adapters_dir ?? '数据目录 / adapters'}</code>
          </p>
        </div>
      </section>

      <section className="community-toolbar">
        <div className="segmented-control">
          {(
            [
              ['all', '全部'],
              ['asr', 'ASR'],
              ['tts', 'TTS'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={kind === id ? 'is-active' : ''}
              onClick={() => setKind(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="community-search">
          <SearchRegular />
          <Input
            value={search}
            onChange={(_, data) => setSearch(data.value)}
            placeholder="搜索模型、来源或适配器 ID"
          />
        </div>
      </section>

      <section className="community-section">
        <div className="section-heading">
          <div>
            <span className="panel-kicker">BUILT-IN RECIPES</span>
            <h2>内置配方模板</h2>
          </div>
          <span className="section-count">{templates.length} 个</span>
        </div>
        {templates.length === 0 ? (
          <EmptyState
            icon={<SearchRegular />}
            title="没有匹配的内置配方"
            description="清除搜索或切换到全部类型。"
          />
        ) : (
          <div className="recipe-grid">
            {templates.map((template) => (
              <RecipeCard
                key={template.id}
                template={template}
                onUse={() => void useTemplate(template)}
              />
            ))}
          </div>
        )}
      </section>

      <section className="community-section">
        <div className="section-heading">
          <div>
            <span className="panel-kicker">INSTALLED ADAPTERS</span>
            <h2>我的适配器</h2>
          </div>
          <span className="section-count">{adapters.length} 个</span>
        </div>
        {loading ? (
          <div className="community-loading">
            <Spinner size="small" /> 正在读取适配器…
          </div>
        ) : adapters.length === 0 ? (
          <div className="panel community-empty">
            <PeopleCommunityRegular />
            <h3>还没有导入适配器</h3>
            <p>
              从上方选择一个内置配方，修改路径或服务地址后导入；也可以直接粘贴社区提供的 JSON / YAML manifest。
            </p>
            <Button appearance="secondary" onClick={() => openImport()}>
              导入第一个适配器
            </Button>
          </div>
        ) : (
          <div className="adapter-grid">
            {adapters.map((adapter) => (
              <AdapterCard
                key={adapter.id}
                adapter={adapter}
                busy={toggling === adapter.id}
                onToggle={(enabled) => void toggle(adapter, enabled)}
                onDelete={() => void remove(adapter)}
              />
            ))}
          </div>
        )}
      </section>

      {payload?.errors.length ? (
        <section className="panel community-errors">
          <strong>适配器加载提示</strong>
          {payload.errors.map((error, index) => (
            <div key={`${error.file}-${index}`}>
              <code>{error.file}</code> {error.error}
            </div>
          ))}
        </section>
      ) : null}

      <Dialog open={importOpen} onOpenChange={(_, data) => setImportOpen(data.open)}>
        <DialogSurface className="community-dialog">
          <DialogBody>
            <DialogTitle>导入社区适配器</DialogTitle>
            <DialogContent>
              <p className="dialog-copy">
                支持 JSON 或 YAML manifest。命令适配器必须显式启用安全开关；导入后默认停用。
                可从 <span className="mono-hint">docs/community.md</span> 查看 schema。
              </p>
              <input
                ref={fileRef}
                type="file"
                accept=".json,.yaml,.yml,application/json,text/yaml"
                className="visually-hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  void file.text().then((text) => setManifest(text));
                  event.target.value = '';
                }}
              />
              <div className="dialog-toolbar">
                <Button
                  appearance="secondary"
                  size="small"
                  icon={<DocumentTextRegular />}
                  onClick={() => fileRef.current?.click()}
                >
                  从文件读取
                </Button>
                <Button
                  appearance="subtle"
                  size="small"
                  icon={<CopyRegular />}
                  onClick={() => void navigator.clipboard?.writeText(manifest)}
                  disabled={!manifest}
                >
                  复制
                </Button>
              </div>
              <Textarea
                className="manifest-editor"
                value={manifest}
                onChange={(_, data) => setManifest(data.value)}
                placeholder={'{\n  "id": "my-model",\n  "name": "My Model",\n  "kind": "tts",\n  "adapter": {\n    "type": "openai-http",\n    "base_url": "http://127.0.0.1:8000/v1",\n    "model": "my-model"\n  }\n}'}
                resize="vertical"
              />
            </DialogContent>
            <DialogActions>
              <DialogTrigger disableButtonEnhancement>
                <Button appearance="secondary">取消</Button>
              </DialogTrigger>
              <Button
                appearance="primary"
                onClick={() => void submitImport()}
                disabled={!manifest.trim() || importing}
                icon={importing ? <Spinner size="tiny" /> : <CheckmarkRegular />}
              >
                {importing ? '正在导入…' : '导入（默认停用）'}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}

function RecipeCard({
  template,
  onUse,
}: {
  template: CommunityTemplate;
  onUse: () => void;
}) {
  const adapterType = String(template.adapter_example.type ?? 'template');
  return (
    <article className="panel recipe-card">
      <div className="recipe-head">
        <div className={`recipe-icon recipe-${template.kind}`}>
          {template.kind === 'asr' ? <MicRegular /> : <Speaker2Regular />}
        </div>
        <div className="recipe-title">
          <strong>{template.name}</strong>
          <span>
            {KIND_LABEL[template.kind]} · {template.source}
          </span>
        </div>
        <StatusPill tone="neutral" dot={false}>
          模板
        </StatusPill>
      </div>
      <p className="recipe-description">{template.description}</p>
      <div className="recipe-meta">
        <span>{template.languages}</span>
        <span>{template.parameters}</span>
        <span>{template.memory_gb ? `${template.memory_gb} GB` : '外部服务'}</span>
        <span>{adapterType}</span>
      </div>
      {template.tags.length > 0 && (
        <div className="recipe-tags">
          {template.tags.slice(0, 4).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      )}
      <div className="recipe-foot">
        <span className="recipe-license">{template.license}</span>
        <div className="recipe-actions">
          {template.homepage && (
            <a href={template.homepage} target="_blank" rel="noreferrer" className="text-link">
              上游项目
            </a>
          )}
          <Button
            size="small"
            appearance="secondary"
            icon={<CodeRegular />}
            onClick={onUse}
          >
            使用模板
          </Button>
        </div>
      </div>
    </article>
  );
}

function AdapterCard({
  adapter,
  busy,
  onToggle,
  onDelete,
}: {
  adapter: CommunityAdapter;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const command = adapter.adapter_type === 'command';
  return (
    <article className={`panel adapter-card${adapter.enabled ? ' is-enabled' : ''}`}>
      <div className="adapter-head">
        <div className={`recipe-icon recipe-${adapter.kind}`}>
          {adapter.kind === 'asr' ? <MicRegular /> : <Speaker2Regular />}
        </div>
        <div className="adapter-title">
          <strong>{adapter.name}</strong>
          <span>
            {KIND_LABEL[adapter.kind]} · {adapter.id}
          </span>
        </div>
        <StatusPill tone={statusTone(adapter.status)}>
          {STATUS_LABEL[adapter.status] ?? adapter.status}
        </StatusPill>
      </div>
      <div className="adapter-facts">
        <div>
          <span>适配类型</span>
          <strong>{command ? '本地命令' : 'OpenAI HTTP'}</strong>
        </div>
        <div>
          <span>模型 ID</span>
          <strong>{adapter.model.id}</strong>
        </div>
        <div>
          <span>语言</span>
          <strong>{adapter.model.languages}</strong>
        </div>
        <div>
          <span>来源</span>
          <strong>{adapter.model.source}</strong>
        </div>
      </div>
      {adapter.error && <div className="inline-note warning-note">{adapter.error}</div>}
      {adapter.description && <p className="adapter-description">{adapter.description}</p>}
      <div className="adapter-actions">
        <div className="adapter-toggle">
          <Switch
            checked={adapter.enabled}
            onChange={(_, data) => onToggle(data.checked)}
            disabled={busy}
          />
          <span>{adapter.enabled ? '启用中' : '已停用'}</span>
          {busy && <Spinner size="tiny" />}
        </div>
        <div className="adapter-links">
          {adapter.homepage && (
            <a href={adapter.homepage} target="_blank" rel="noreferrer" className="text-link">
              项目主页
            </a>
          )}
          <button type="button" className="icon-danger" onClick={onDelete} aria-label="删除适配器">
            <DeleteRegular />
          </button>
        </div>
      </div>
    </article>
  );
}
