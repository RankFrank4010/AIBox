import { useEffect, useMemo, useState } from 'react';
import { Button, Spinner } from '@fluentui/react-components';
import {
  ArrowSyncRegular,
  CloudRegular,
  FlashRegular,
  ServerRegular,
} from '@fluentui/react-icons';
import { PageHeader } from '../components/PageHeader';
import { StatusPill } from '../components/StatusPill';
import { api, errorMessage } from '../api/client';
import type { ClusterStatus, ClusterTask } from '../api/types';

export function ClusterPage() {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [tasks, setTasks] = useState<ClusterTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextStatus, nextTasks] = await Promise.all([
        api.clusterStatus(),
        api.clusterTasks(),
      ]);
      setStatus(nextStatus);
      setTasks(nextTasks.tasks);
      setError('');
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const counts = useMemo(() => status?.task_counts ?? {}, [status]);
  const active = (counts.running ?? 0) + (counts.assigned ?? 0);
  const mode = status?.mode ?? 'master_slave';

  return (
    <div className="page cluster-page">
      <PageHeader
        title="计算集群"
        description="查看多机 worker 的在线状态、能力和任务分布；协调器按最低负载调度，失败自动重试。"
        actions={
          <div className="page-actions">
            <StatusPill tone={status?.enabled ? 'success' : 'warning'}>
              {status?.enabled ? '集群调度已启用' : '集群调度未启用'}
            </StatusPill>
            <Button appearance="secondary" icon={<ArrowSyncRegular />} onClick={() => void load()}>
              刷新
            </Button>
          </div>
        }
      />

      {error ? <div className="cluster-error">{error}</div> : null}

      <div className="cluster-stats">
        <div className="panel cluster-stat">
          <ServerRegular />
          <span>在线节点</span>
          <strong>{status?.nodes_online ?? 0}</strong>
          <small>共 {status?.nodes_total ?? 0} 个</small>
        </div>
        <div className="panel cluster-stat">
          <FlashRegular />
          <span>活跃任务</span>
          <strong>{active}</strong>
          <small>已分配 + 运行中</small>
        </div>
        <div className="panel cluster-stat">
          <CloudRegular />
          <span>失败重试</span>
          <strong>{status?.max_retries ?? 0}</strong>
          <small>每个任务</small>
        </div>
        <div className="panel cluster-stat">
          <ServerRegular />
          <span>节点租约</span>
          <strong>{status?.node_ttl_seconds ?? 0}s</strong>
          <small>心跳超时</small>
        </div>
      </div>

      <section className="panel cluster-nodes-panel">
        <div className="cluster-panel-head">
          <div>
            <span className="eyebrow">NODES</span>
            <h2>Worker 节点</h2>
          </div>
          <span className="cluster-mono">
            {mode === 'decentralized' ? '去中心模式' : '主从模式'} ·{' '}
            {status?.token_required ? 'Token 鉴权' : '无 Token'}
          </span>
        </div>
        {loading && !status ? (
          <div className="cluster-empty">
            <Spinner label="加载集群状态…" />
          </div>
        ) : status?.nodes.length ? (
          <div className="cluster-node-grid">
            {status.nodes.map((node) => (
              <article className="cluster-node" key={node.id}>
                <div className="cluster-node-head">
                  <div>
                    <strong>{node.id}</strong>
                    <span>{node.url}</span>
                  </div>
                  <StatusPill tone={node.state === 'online' ? 'success' : 'warning'}>
                    {node.state}
                  </StatusPill>
                </div>
                <div className="cluster-node-meta">
                  <span>并发 {node.active_tasks}/{node.max_concurrency}</span>
                  <span>{node.version}</span>
                  <span>{node.last_heartbeat}</span>
                </div>
                <div className="cluster-node-actions">
                  <Button
                    appearance="subtle"
                    size="small"
                    onClick={() => {
                      const enabled = node.work_config?.enabled !== false;
                      void api
                        .clusterUpdateNodeConfig(node.id, {
                          ...node.work_config,
                          enabled: !enabled,
                        })
                        .then(() => load(true))
                        .catch((reason) => setError(errorMessage(reason)));
                    }}
                  >
                    {node.work_config?.enabled === false ? '恢复调度' : '暂停调度'}
                  </Button>
                </div>
                <div className="cluster-chips">
                  {node.capabilities.map((capability) => (
                    <span key={capability}>{capability}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="cluster-empty">
            <strong>还没有 Worker</strong>
            <span>启动 `python -m aibox_api.worker` 并指向此协调器。</span>
          </div>
        )}
      </section>

      <section className="panel cluster-tasks-panel">
        <div className="cluster-panel-head">
          <div>
            <span className="eyebrow">TASKS</span>
            <h2>集群任务</h2>
          </div>
          <span className="cluster-mono">{tasks.length} 条</span>
        </div>
        {tasks.length === 0 ? (
          <div className="cluster-empty">还没有集群任务。</div>
        ) : (
          <div className="cluster-table">
            <div className="cluster-table-head">
              <span>任务</span>
              <span>类型</span>
              <span>节点</span>
              <span>状态</span>
              <span>尝试</span>
              <span>更新时间</span>
            </div>
            {tasks.map((task) => (
              <div className="cluster-table-row" key={task.id}>
                <span className="cluster-mono">{task.id}</span>
                <span>{task.kind}</span>
                <span>{task.node_id ?? '—'}</span>
                <span className={`cluster-state is-${task.status}`}>{task.status}</span>
                <span>{task.attempts}</span>
                <span className="cluster-mono">{task.updated_at}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="cluster-note">
        高性能调度：过滤能力、节点在线与并发槽位，按活跃任务数和心跳时间排序；失败自动换节点。
        生产环境建议将协调器置于负载均衡后，使用共享数据库与对象存储，并将 worker 分散到不同机器。
      </div>
    </div>
  );
}
