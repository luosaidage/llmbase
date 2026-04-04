const COLORS = [
  'bg-primary-container/40 text-on-primary-container',
  'bg-secondary-container/20 text-secondary',
  'bg-tertiary-container/40 text-tertiary',
  'bg-surface-bright text-on-surface-variant',
  'bg-on-primary/20 text-primary',
];

export function Tag({ label }: { label: string }) {
  const idx = Math.abs([...label].reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)) % COLORS.length;
  return (
    <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-medium ${COLORS[idx]}`}>
      {label}
    </span>
  );
}
