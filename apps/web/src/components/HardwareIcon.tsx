export function HardwareIcon({
  kind,
  size = 24,
  className = '',
}: {
  kind: 'cpu' | 'gpu' | 'npu' | string;
  size?: number;
  className?: string;
}) {
  if (kind === 'gpu') {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        className={className}
        aria-hidden="true"
      >
        <rect x="2.25" y="6" width="19.5" height="11.25" rx="2.4" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="9" cy="11.6" r="2.9" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="9" cy="11.6" r="0.9" fill="currentColor" />
        <path d="M15 9.2h4M15 12h4M15 14.8h2.7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M6.2 17.25V20M17.8 17.25V20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === 'npu') {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        className={className}
        aria-hidden="true"
      >
        <rect x="5" y="5" width="14" height="14" rx="3.2" stroke="currentColor" strokeWidth="1.5" />
        <path d="m12 8.3 1.15 2.55L15.7 12l-2.55 1.15L12 15.7l-1.15-2.55L8.3 12l2.55-1.15L12 8.3Z" fill="currentColor" />
        <path d="M9 2.4v2.6M15 2.4v2.6M9 19v2.6M15 19v2.6M2.4 9H5M2.4 15H5M19 9h2.6M19 15h2.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <rect x="6" y="6" width="12" height="12" rx="2.2" stroke="currentColor" strokeWidth="1.5" />
      <rect x="9.3" y="9.3" width="5.4" height="5.4" rx="1.2" fill="currentColor" fillOpacity=".9" />
      <path d="M9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
