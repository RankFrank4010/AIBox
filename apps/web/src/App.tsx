import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { FluentProvider } from '@fluentui/react-components';
import { AppShell } from './components/AppShell';
import { AppDataProvider } from './state/AppContext';
import { useThemeMode } from './state/ThemeContext';
import { aiboxDarkTheme, aiboxLightTheme } from './theme';
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
import { TrainingPage } from './pages/TrainingPage';
import { VideosPage } from './pages/VideosPage';

export default function App() {
  const { resolved } = useThemeMode();
  return (
    <FluentProvider
      theme={resolved === 'dark' ? aiboxDarkTheme : aiboxLightTheme}
      style={{ height: '100%', minHeight: '100%' }}
    >
      <AppDataProvider>
        <BrowserRouter>
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
              <Route path="services" element={<ServicesPage />} />
              <Route path="roadmap" element={<RoadmapPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AppDataProvider>
    </FluentProvider>
  );
}
