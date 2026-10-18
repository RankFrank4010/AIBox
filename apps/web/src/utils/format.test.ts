import { describe, expect, it } from 'vitest';
import {
  formatBytes,
  formatDuration,
  formatEta,
  formatTimestamp,
  languageLabel,
  percent,
} from './format';

describe('format helpers', () => {
  it('formats byte sizes', () => {
    expect(formatBytes(0)).toBe('—');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(75_500_000)).toBe('72.0 MB');
    expect(formatBytes(3_090_000_000)).toBe('2.9 GB');
  });

  it('formats durations and timestamps', () => {
    expect(formatDuration(0)).toBe('00:00');
    expect(formatDuration(9.4)).toBe('00:09');
    expect(formatDuration(3661)).toBe('1:01:01');
    expect(formatTimestamp(65)).toBe('01:05');
  });

  it('formats ETA and percentages', () => {
    expect(formatEta(null)).toBe('计算中');
    expect(formatEta(42)).toBe('约 42 秒');
    expect(formatEta(130)).toBe('约 3 分钟');
    expect(percent(42.4)).toBe('42%');
  });

  it('maps language codes', () => {
    expect(languageLabel('zh')).toBe('中文');
    expect(languageLabel('auto')).toBe('自动检测');
    expect(languageLabel('xx')).toBe('XX');
  });
});
