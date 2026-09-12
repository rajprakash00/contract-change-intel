// The product mark (issue #19): two offset document sheets — base and
// amendment — with the changed line called out in the ink-blue accent.
// The favicon (src/app/icon.svg) carries the same drawing.
export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label="Contract Change-Impact Intelligence"
    >
      <rect width="32" height="32" rx="7" fill="#28436a" />
      <rect x="7" y="9" width="13" height="16" rx="2" fill="#ffffff" opacity="0.4" />
      <rect x="12" y="7" width="13" height="18" rx="2" fill="#ffffff" />
      <rect x="14.5" y="10" width="8" height="2" rx="1" fill="#28436a" opacity="0.35" />
      <rect x="14.5" y="14" width="8" height="2.4" rx="1.2" fill="#28436a" />
      <rect x="14.5" y="18.5" width="5.5" height="2" rx="1" fill="#28436a" opacity="0.35" />
    </svg>
  );
}
