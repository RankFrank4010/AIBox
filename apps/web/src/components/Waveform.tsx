import { useMemo } from 'react';

export function Waveform({
  bars = 40,
  active = false,
  className = '',
  compact = false,
}: {
  bars?: number;
  active?: boolean;
  className?: string;
  compact?: boolean;
}) {
  const heights = useMemo(
    () =>
      Array.from({ length: bars }, (_, index) => {
        const a = Math.sin(index * 0.72) * 0.32;
        const b = Math.sin(index * 1.91 + 1.4) * 0.22;
        const c = Math.cos(index * 0.31) * 0.18;
        const envelope = Math.sin((index / Math.max(bars - 1, 1)) * Math.PI);
        return Math.round(16 + (a + b + c + 0.55) * 56 * (0.45 + envelope * 0.55));
      }),
    [bars],
  );

  return (
    <div
      className={`waveform${active ? ' is-active' : ''}${compact ? ' is-compact' : ''} ${className}`.trim()}
      aria-hidden="true"
    >
      {heights.map((height, index) => (
        <span
          key={index}
          className="wave-bar"
          style={{
            height: `${Math.max(10, Math.min(100, height))}%`,
            animationDelay: `${(index % 11) * 70}ms`,
          }}
        />
      ))}
    </div>
  );
}

export function AudioOrb({ active = true }: { active?: boolean }) {
  return (
    <div className={`audio-orb-wrap${active ? ' is-active' : ''}`} aria-hidden="true">
      <span className="orb-ring orb-ring-1" />
      <span className="orb-ring orb-ring-2" />
      <span className="orb-ring orb-ring-3" />
      <span className="orb-scan" />
      <div className="audio-orb">
        <div className="orb-glow" />
        <div className="orb-inner">
          <Waveform bars={26} active={active} compact />
        </div>
      </div>
      <span className="orb-chip orb-chip-a">
        <span className="orb-chip-dot" /> faster-whisper
      </span>
      <span className="orb-chip orb-chip-b">CTranslate2</span>
      <span className="orb-chip orb-chip-c">
        <span className="orb-chip-dot" /> 100% 本地
      </span>
    </div>
  );
}
