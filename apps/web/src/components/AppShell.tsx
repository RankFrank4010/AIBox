import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  ArrowDownloadRegular,
  ChatRegular,
  GlobeRegular,
  HomeRegular,
  ImageRegular,
  LibraryRegular,
  MicRegular,
  MusicNote2Regular,
  PeopleCommunityRegular,
  SettingsRegular,
  Speaker2Regular,
  VideoRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { Brand } from './Brand';
import { HardwareIcon } from './HardwareIcon';
import { StatusPill } from './StatusPill';
import { useAppData } from '../state/AppContext';
import { useThemeMode } from '../state/ThemeContext';

const NAV_ITEMS = [
  { path: '/', label: '总览', icon: <HomeRegular /> },
  { path: '/models', label: '模型库', icon: <LibraryRegular /> },
  { path: '/community', label: '社区适配', icon: <PeopleCommunityRegular /> },
  { path: '/transcribe', label: '语音转写', icon: <MicRegular /> },
  { path: '/tts', label: '语音合成', icon: <Speaker2Regular /> },
  { path: '/chat', label: '对话', icon: <ChatRegular /> },
  { path: '/images', label: '图像生成', icon: <ImageRegular /> },
  { path: '/videos', label: '视频生成', icon: <VideoRegular /> },
  { path: '/separations', label: '音频分离', icon: <MusicNote2Regular /> },
  { path: '/system', label: '硬件引擎', icon: <HardwareIcon kind="cpu" size={22} /> },
  { path: '/services', label: '服务接入', icon: <GlobeRegular /> },
  { path: '/settings', label: '设置', icon: <SettingsRegular /> },
];

const PAGE_TITLES: Record<string, string> = {
  '/': '总览',
  '/models': '模型库',
  '/community': '社区适配',
  '/transcribe': '语音转写',
  '/tts': '语音合成',
  '/chat': '语言模型',
  '/images': '图像生成',
  '/videos': '视频生成',
  '/separations': '音频分离',
  '/system': '硬件与引擎',
  '/services': '服务接入',
  '/roadmap': '跨端路线',
  '/settings': '设置',
};

export function AppShell() {
  const { system, models, online, error, refreshAll } = useAppData();
  const { resolved, setMode } = useThemeMode();
  const location = useLocation();
  const activeDownloads =
    models?.downloads.filter(
      (task) => task.status === 'queued' || task.status === 'downloading' || task.status === 'cancelling',
    ).length ?? 0;
  const primaryDevice = system?.accelerators.find((item) => item.kind === 'gpu' && item.for_asr)
    ?? system?.accelerators.find((item) => item.kind === 'gpu')
    ?? system?.accelerators.find((item) => item.kind === 'cpu');

  return (
    <div className="app-shell">
      <div className="app-aurora" aria-hidden="true">
        <span className="aurora aurora-one" />
        <span className="aurora aurora-two" />
        <span className="aurora aurora-three" />
        <span className="app-grid" />
      </div>

      <aside className="sidebar">
        <div className="sidebar-brand">
          <Brand />
        </div>

        <nav className="side-nav" aria-label="主导航">
          <div className="nav-section-label">工作台</div>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `nav-item${isActive ? ' is-active' : ''}`}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-label">{item.label}</span>
              {item.path === '/models' && activeDownloads > 0 && (
                <span className="nav-badge">{activeDownloads}</span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-status-card">
          <div className="sidebar-status-head">
            <span className={`live-dot${online ? ' is-online' : ''}`} />
            <span>{online ? '本地服务已连接' : '本地服务离线'}</span>
          </div>
          <div className="sidebar-device">
            <div className="sidebar-device-icon">
              <HardwareIcon kind={primaryDevice?.kind ?? 'cpu'} size={20} />
            </div>
            <div className="sidebar-device-copy">
              <span>{primaryDevice?.kind === 'gpu' ? 'GPU 加速' : 'CPU 推理'}</span>
              <strong title={primaryDevice?.name}>{primaryDevice?.name ?? '正在检测设备'}</strong>
            </div>
          </div>
          <Link to="/system" className="sidebar-link">
            查看硬件详情
            <span aria-hidden="true">→</span>
          </Link>
        </div>

        <div className="sidebar-foot">
          <span className="version-chip">v0.1.0</span>
          <span className="sidebar-foot-copy">本地优先 · 隐私安全</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <div className="mobile-brand">
              <Brand compact />
            </div>
            <div className="topbar-crumb">
              <span>AIBox</span>
              <span className="crumb-slash">/</span>
              <strong>{PAGE_TITLES[location.pathname] ?? '工作台'}</strong>
            </div>
          </div>
          <div className="topbar-right">
            {activeDownloads > 0 && (
              <Link to="/models" className="topbar-download">
                <ArrowDownloadRegular />
                <span>{activeDownloads} 个下载中</span>
              </Link>
            )}
            <StatusPill tone={online ? 'success' : 'danger'}>
              {online ? '本地运行' : '已离线'}
            </StatusPill>
            <button
              type="button"
              className="icon-button"
              onClick={() => setMode(resolved === 'dark' ? 'light' : 'dark')}
              aria-label={resolved === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
              title={resolved === 'dark' ? '浅色主题' : '深色主题'}
            >
              {resolved === 'dark' ? (
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <circle cx="12" cy="12" r="4.1" fill="currentColor" />
                  <path d="M12 2.6v2.3M12 19.1v2.3M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2.6 12h2.3M19.1 12h2.3M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <path d="M20.4 14.6A8.6 8.6 0 0 1 9.4 3.6a8.7 8.7 0 1 0 11 11Z" fill="currentColor" />
                </svg>
              )}
            </button>
          </div>
        </header>

        {!online && (
          <div className="connection-banner" role="alert">
            <WarningRegular />
            <span>{error ?? '无法连接 AIBox 本地服务，请确认后端已启动。'}</span>
            <button type="button" onClick={() => void refreshAll()} className="banner-retry">
              重试连接
            </button>
          </div>
        )}

        <main className="main-content" key={location.pathname}>
          <Outlet />
        </main>
      </div>

      <nav className="mobile-nav" aria-label="移动端导航">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) => `mobile-nav-item${isActive ? ' is-active' : ''}`}
          >
            <span className="mobile-nav-icon">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
