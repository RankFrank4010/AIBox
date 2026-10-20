import { useState } from 'react';
import { Button, Input, Spinner } from '@fluentui/react-components';
import { LockClosedRegular, PersonRegular } from '@fluentui/react-icons';
import { Brand } from '../components/Brand';
import { api, errorMessage, setAuthToken } from '../api/client';
import type { AuthStatus, AuthUser } from '../api/types';

export function LoginPage({
  status,
  onAuthenticated,
}: {
  status: AuthStatus;
  onAuthenticated: (user: AuthUser) => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const setup = status.needs_setup;

  const submit = async () => {
    if (busy) return;
    if (setup && password !== confirm) {
      setError('两次密码不一致。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result = setup
        ? await api.authBootstrap(username, password)
        : await api.authLogin(username, password);
      setAuthToken(result.token);
      onAuthenticated(result.user);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-glow" />
      <div className="login-card">
        <div className="login-brand">
          <Brand compact />
          <span>AIBox Control</span>
        </div>
        <div className="login-copy">
          <span className="eyebrow">{setup ? 'FIRST RUN' : 'SIGN IN'}</span>
          <h1>{setup ? '创建管理员账户' : '登录 AIBox'}</h1>
          <p>
            {setup
              ? '首次启用账户系统，需要创建一个本地管理员。密码至少 8 位。'
              : status.mode === 'external'
                ? '当前使用外置登录，请通过上游身份网关访问。'
                : '使用内置账户登录，或由管理员分配角色。'}
          </p>
        </div>
        {status.mode === 'external' ? (
          <div className="login-external">
            <LockClosedRegular />
            <span>外置登录模式：请通过 OIDC / 反向代理身份头访问。</span>
          </div>
        ) : (
          <form
            className="login-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <label className="field">
              <span className="field-label">用户名</span>
              <Input
                value={username}
                onChange={(_, data) => setUsername(data.value)}
                contentBefore={<PersonRegular />}
                autoComplete="username"
                autoFocus
              />
            </label>
            <label className="field">
              <span className="field-label">密码</span>
              <Input
                type="password"
                value={password}
                onChange={(_, data) => setPassword(data.value)}
                contentBefore={<LockClosedRegular />}
                autoComplete={setup ? 'new-password' : 'current-password'}
              />
            </label>
            {setup ? (
              <label className="field">
                <span className="field-label">确认密码</span>
                <Input
                  type="password"
                  value={confirm}
                  onChange={(_, data) => setConfirm(data.value)}
                  contentBefore={<LockClosedRegular />}
                  autoComplete="new-password"
                />
              </label>
            ) : null}
            {error ? <div className="login-error">{error}</div> : null}
            <Button
              type="submit"
              appearance="primary"
              disabled={busy || !username || password.length < 8}
              icon={busy ? <Spinner size="tiny" /> : undefined}
            >
              {busy ? '处理中…' : setup ? '创建并登录' : '登录'}
            </Button>
          </form>
        )}
        <div className="login-foot">
          <span>默认内置轻量账户系统</span>
          <span>支持外置身份网关</span>
        </div>
      </div>
    </div>
  );
}
