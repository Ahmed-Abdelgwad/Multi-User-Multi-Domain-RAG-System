import type { ReactNode } from 'react'
import { Button } from './Button'

interface EmptyStateProps {
  title: string
  description?: ReactNode
  action?: { label: string; onClick: () => void }
  children?: ReactNode
}

export function EmptyState({ title, description, action, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {description && <p className="muted">{description}</p>}
      {children}
      {action && <Button onClick={action.onClick}>{action.label}</Button>}
    </div>
  )
}
