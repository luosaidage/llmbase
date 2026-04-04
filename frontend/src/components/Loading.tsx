export function Loading({ text = 'Loading...' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-on-surface-variant">{text}</p>
      </div>
    </div>
  );
}

export function Shimmer({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="shimmer h-4" style={{ width: `${85 - i * 15}%` }} />
      ))}
    </div>
  );
}
