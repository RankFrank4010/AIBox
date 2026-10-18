import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react';
import { formatDuration } from '../utils/format';

const RATES = [1, 1.25, 1.5, 2];

export interface AudioPlayerHandle {
  seek: (seconds: number) => void;
  play: () => void;
  pause: () => void;
}

export const AudioPlayer = forwardRef<
  AudioPlayerHandle,
  {
    src: string;
    onTimeUpdate?: (time: number, playing: boolean) => void;
  }
>(function AudioPlayer({ src, onTimeUpdate }, ref) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState(1);
  const [error, setError] = useState(false);

  useEffect(() => {
    setPlaying(false);
    setCurrent(0);
    setDuration(0);
    setError(false);
  }, [src]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = rate;
  }, [rate]);

  const play = () => {
    const audio = audioRef.current;
    if (!audio) return;
    void audio.play().catch(() => setError(true));
  };

  useImperativeHandle(ref, () => ({
    seek(seconds: number) {
      const audio = audioRef.current;
      if (!audio) return;
      audio.currentTime = seconds;
      setCurrent(seconds);
      onTimeUpdate?.(seconds, !audio.paused);
      if (audio.paused) play();
    },
    play,
    pause() {
      audioRef.current?.pause();
    },
  }));

  const toggle = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      try {
        await audio.play();
      } catch {
        setError(true);
      }
    } else {
      audio.pause();
    }
  };

  const seek = (value: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = value;
    setCurrent(value);
    onTimeUpdate?.(value, !audio.paused);
  };

  const cycleRate = () => {
    const index = RATES.indexOf(rate);
    setRate(RATES[(index + 1) % RATES.length]);
  };

  return (
    <div className={`audio-player${error ? ' has-error' : ''}`}>
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onPlay={() => {
          setPlaying(true);
          onTimeUpdate?.(audioRef.current?.currentTime ?? 0, true);
        }}
        onPause={() => {
          setPlaying(false);
          onTimeUpdate?.(audioRef.current?.currentTime ?? 0, false);
        }}
        onTimeUpdate={() => {
          const time = audioRef.current?.currentTime ?? 0;
          setCurrent(time);
          onTimeUpdate?.(time, !audioRef.current?.paused);
        }}
        onLoadedMetadata={() => setDuration(audioRef.current?.duration ?? 0)}
        onEnded={() => setPlaying(false)}
        onError={() => setError(true)}
      />
      <button
        className="audio-play"
        onClick={() => void toggle()}
        aria-label={playing ? '暂停音频' : '播放音频'}
        type="button"
      >
        {playing ? (
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <rect x="6.5" y="5" width="3.6" height="14" rx="1.2" fill="currentColor" />
            <rect x="13.9" y="5" width="3.6" height="14" rx="1.2" fill="currentColor" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M8 5.6c0-.9 1-1.4 1.7-.9l9.2 6.4c.6.4.6 1.3 0 1.7l-9.2 6.4c-.7.5-1.7 0-1.7-.9V5.6Z" fill="currentColor" />
          </svg>
        )}
      </button>
      <div className="audio-main">
        <div className="audio-time-row">
          <span>{formatDuration(current)}</span>
          <span>{error ? '音频不可用' : formatDuration(duration)}</span>
        </div>
        <input
          className="audio-seek"
          type="range"
          min={0}
          max={Math.max(duration, 0.01)}
          step={0.05}
          value={Math.min(current, duration || 0)}
          onChange={(event) => seek(Number(event.target.value))}
          aria-label="音频进度"
          style={{
            background: `linear-gradient(90deg, var(--accent) ${
              duration ? (current / duration) * 100 : 0
            }%, var(--track) ${duration ? (current / duration) * 100 : 0}%)`,
          }}
        />
      </div>
      <button className="audio-rate" type="button" onClick={cycleRate} aria-label="播放速度">
        {rate}×
      </button>
    </div>
  );
});
