import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  Toast,
  ToastBody,
  ToastTitle,
  Toaster,
  useToastController,
  type ToastIntent,
} from '@fluentui/react-components';
import { api, errorMessage } from '../api/client';
import type {
  AppSettings,
  HealthPayload,
  ModelsPayload,
  SystemInfo,
} from '../api/types';

interface AppDataValue {
  system: SystemInfo | null;
  models: ModelsPayload | null;
  settings: AppSettings | null;
  health: HealthPayload | null;
  loading: boolean;
  online: boolean;
  error: string | null;
  refreshSystem: () => Promise<void>;
  refreshModels: () => Promise<void>;
  refreshAll: () => Promise<void>;
  updateSettings: (patch: Partial<AppSettings>) => Promise<AppSettings>;
  notify: (title: string, body?: string, intent?: ToastIntent) => void;
}

const AppDataContext = createContext<AppDataValue | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [models, setModels] = useState<ModelsPayload | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [online, setOnline] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const toasterId = useId();
  const { dispatchToast } = useToastController(toasterId);

  const notify = useCallback(
    (title: string, body?: string, intent: ToastIntent = 'success') => {
      dispatchToast(
        <Toast>
          <ToastTitle>{title}</ToastTitle>
          {body ? <ToastBody>{body}</ToastBody> : null}
        </Toast>,
        { intent, timeout: 3800 },
      );
    },
    [dispatchToast],
  );

  const refreshSystem = useCallback(async () => {
    try {
      const data = await api.system();
      setSystem(data);
      setSettings(data.settings);
      setOnline(true);
      setError(null);
    } catch (err) {
      setOnline(false);
      setError(errorMessage(err));
    }
  }, []);

  const refreshModels = useCallback(async () => {
    try {
      const data = await api.models();
      setModels(data);
      setOnline(true);
    } catch (err) {
      setOnline(false);
      setError((current) => current ?? errorMessage(err));
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.allSettled([
      refreshSystem(),
      refreshModels(),
      api
        .health()
        .then((data) => {
          setHealth(data);
          setOnline(true);
        })
        .catch((err) => {
          setOnline(false);
          setError(errorMessage(err));
        }),
      api
        .settings()
        .then(setSettings)
        .catch(() => undefined),
    ]);
    setLoading(false);
  }, [refreshModels, refreshSystem]);

  const updateSettings = useCallback(
    async (patch: Partial<AppSettings>) => {
      const next = await api.updateSettings(patch);
      setSettings(next);
      setSystem((current) => (current ? { ...current, settings: next } : current));
      notify('设置已保存', '新的默认参数会应用到下一次转写。');
      return next;
    },
    [notify],
  );

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshSystem();
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [refreshSystem]);

  const hasActiveDownloads = Boolean(
    models?.downloads?.some(
      (task) => task.status === 'queued' || task.status === 'downloading' || task.status === 'cancelling',
    ),
  );

  useEffect(() => {
    const timer = window.setInterval(
      () => {
        void refreshModels();
      },
      hasActiveDownloads ? 1_200 : 10_000,
    );
    return () => window.clearInterval(timer);
  }, [hasActiveDownloads, refreshModels]);

  const value = useMemo<AppDataValue>(
    () => ({
      system,
      models,
      settings,
      health,
      loading,
      online,
      error,
      refreshSystem,
      refreshModels,
      refreshAll,
      updateSettings,
      notify,
    }),
    [
      system,
      models,
      settings,
      health,
      loading,
      online,
      error,
      refreshSystem,
      refreshModels,
      refreshAll,
      updateSettings,
      notify,
    ],
  );

  return (
    <AppDataContext.Provider value={value}>
      {children}
      <Toaster toasterId={toasterId} position="top-end" />
    </AppDataContext.Provider>
  );
}

export function useAppData(): AppDataValue {
  const value = useContext(AppDataContext);
  if (!value) throw new Error('useAppData must be used inside AppDataProvider');
  return value;
}
