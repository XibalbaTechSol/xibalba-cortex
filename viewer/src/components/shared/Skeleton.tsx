export function Skeleton({
  width = '100%',
  height = 14,
  className = '',
}: {
  width?: number | string
  height?: number
  className?: string
}) {
  return (
    <span
      className={`skeleton skeleton-text ${className}`}
      style={{
        width: typeof width === 'number' ? `${width}px` : width,
        height: `${height}px`,
        display: 'block',
      }}
    />
  )
}
