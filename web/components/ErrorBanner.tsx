export default function ErrorBanner({ title, message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
    >
      <div>
        {title && <p className="font-semibold">{title}</p>}
        <p>{message}</p>
      </div>
      {onRetry && (
        <button className="btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
