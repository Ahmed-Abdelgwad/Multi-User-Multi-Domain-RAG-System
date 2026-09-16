interface SkeletonProps {
  width?: string | number
  height?: string | number
  radius?: string
}

export function Skeleton({ width = '100%', height = '1rem', radius }: SkeletonProps) {
  return <div className="skeleton" style={{ width, height, borderRadius: radius }} />
}

export function SkeletonTable({ rows = 4, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="table skeleton-table">
      {Array.from({ length: rows }).map((_, row) => (
        <div className="skeleton-table-row" key={row}>
          {Array.from({ length: columns }).map((_, col) => (
            <Skeleton key={col} height="0.9rem" />
          ))}
        </div>
      ))}
    </div>
  )
}
