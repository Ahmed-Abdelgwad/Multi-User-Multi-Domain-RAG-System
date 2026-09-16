import { useEffect, useRef, useState } from 'react'
import { lookupUsersToInvite } from '../api/domains'
import type { UserResponse } from '../api/types'

interface UserSearchComboboxProps {
  domainId: string
  onSelect: (user: UserResponse) => void
  placeholder?: string
}

const MIN_QUERY_LENGTH = 2
const DEBOUNCE_MS = 300

export function UserSearchCombobox({ domainId, onSelect, placeholder }: UserSearchComboboxProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<UserResponse[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (query.trim().length < MIN_QUERY_LENGTH) {
      setResults([])
      setIsOpen(false)
      return
    }
    setIsLoading(true)
    const handle = setTimeout(() => {
      lookupUsersToInvite(domainId, query.trim())
        .then((users) => {
          setResults(users)
          setIsOpen(true)
        })
        .catch(() => setResults([]))
        .finally(() => setIsLoading(false))
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [query, domainId])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="user-search" ref={containerRef}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setIsOpen(true)}
        placeholder={placeholder ?? 'Search by email...'}
      />
      {isOpen && (
        <div className="user-search-results">
          {isLoading && <div className="user-search-empty">Searching...</div>}
          {!isLoading && results.length === 0 && query.trim().length >= MIN_QUERY_LENGTH && (
            <div className="user-search-empty">No matching users</div>
          )}
          {!isLoading &&
            results.map((user) => (
              <button
                key={user.id}
                type="button"
                className="user-search-result"
                onClick={() => {
                  onSelect(user)
                  setQuery('')
                  setResults([])
                  setIsOpen(false)
                }}
              >
                <span>
                  {user.first_name} {user.last_name}
                </span>
                <span className="muted">{user.email}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
