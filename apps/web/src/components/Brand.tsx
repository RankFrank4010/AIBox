import { Link } from 'react-router-dom';

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className={`brand${compact ? ' brand-compact' : ''}`} aria-label="AIBox 首页">
      <span className="brand-mark" aria-hidden="true">
        <img src="/aibox-mark.svg" alt="" />
        <span className="brand-pulse" />
      </span>
      {!compact && (
        <span className="brand-copy">
          <span className="brand-name">AIBox</span>
          <span className="brand-tagline">LOCAL AI STUDIO</span>
        </span>
      )}
    </Link>
  );
}
