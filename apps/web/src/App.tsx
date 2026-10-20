import { useEffect, useState, type ReactNode } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { FluentProvider, Spinner } from '@fluentui/react-components';
import { AppShell } from './components/AppShell';
import { AppDataProvider } from './state/AppContext';
import { useThemeMode } from './state/ThemeContext';
import { aiboxDarkTheme, aiboxLightTheme } from './theme';
import { api, setAuthToken } from './api/client';
import type { AuthStatus, AuthUser } from './api/types';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { ModelsPage } from './pages/ModelsPage';
import { CommunityPage } from './pages/CommunityPage';
import { TranscribePage } from './pages/TranscribePage';
import { SystemPage } from './pages/SystemPage';
import { SettingsPage } from './pages/SettingsPage';
import { RoadmapPage } from './pages/RoadmapPage';
import { ServicesPage } from './pages/ServicesPage';
import { TtsPage } from './pages/TtsPage';
import { ImagesPage } from './pages/ImagesPage';
import { SeparationsPage } from './pages/SeparationsPage';
import { ChatPage } from './pages/ChatPage';
import { TranslationPage } from './pages/TranslationPage';
import { OcrPage } from './pages/OcrPage';
import { ClusterPage } from './pages/ClusterPage';
import { TrainingPage } from './pages/TrainingPage';
import { VideosPage } from './pages/VideosPage';

function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [failed, setFailed] = useState('');
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    api
      .authStatus()
      .then((next) => {
        setStatus(next);
        setUser(next.user);
      })
      .catch((error: unknown) => setFailed(error instanceof Error ? error.message : String(error)));
  }, []);

  if (failed) {
    return (
      <div className="login-page">
        <div className="login-card">
          <div className="login-brand">AIBox Control</div>
          <div className="login-copy">
            <h1>无法读取账户状态</h1>
            <p>{failed}</p>
          </div>
          <button className="login-retry" onClick={() => window.location.reload()}>
            重试
          </button>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="login-page">
        <Spinner label="正在检查登录状态…" />
      </div>
    );
  }

  if (status.enabled && !user) {
    return (
      <LoginPage
        status={status}
        onAuthenticated={(next) => {
          setUser(next);
          setStatus({ ...status, needs_setup: false, user: next });
        }}
      />
    );
  }

  return (
    <>
      {status.enabled && user ? (
        <div className="auth-session">
          <span>{user.username}</span>
          <span>{user.role}</span>
          <button
            onClick={() => {
              void api.authLogout().finally(() => {
                setAuthToken(null);
                setUser(null);
              });
            }}
          >
            退出
          </button>
        </div>
      ) : null}
      {children}
    </>
  );
}

export default function App() {
  const { resolved } = useThemeMode();
  return (
    <FluentProvider
      theme={resolved === 'dark' ? aiboxDarkTheme : aiboxLightTheme}
      style={{ height: '100%', minHeight: '100%' }}
    >
      <BrowserRouter>
        <AuthGate>
          <AppDataProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<OverviewPage />} />
                <Route path="models" element={<ModelsPage />} />
                <Route path="community" element={<CommunityPage />} />
                <Route path="transcribe" element={<TranscribePage />} />
                <Route path="tts" element={<TtsPage />} />
                <Route path="chat" element={<ChatPage />} />
                <Route path="translation" element={<TranslationPage />} />
                <Route path="ocr" element={<OcrPage />} />
                <Route path="training" element={<TrainingPage />} />
                <Route path="images" element={<ImagesPage />} />
                <Route path="separations" element={<SeparationsPage />} />
                <Route path="videos" element={<VideosPage />} />
                <Route path="system" element={<SystemPage />} />
                <Route path="cluster" element={<ClusterPage />} />
                <Route path="services" element={<ServicesPage />} />
                <Route path="roadmap" element={<RoadmapPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </AppDataProvider>
        </AuthGate>
      </BrowserRouter>
    </FluentProvider>
  );
}
