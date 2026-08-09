import { useEffect, useRef, useState } from 'react'

import { searchStations } from '../api.js'
import RouteBullet from './RouteBullet.jsx'

export default function StationSearch({ onSelect }) {
  const [term, setTerm] = useState('')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    if (!term.trim()) {
      setResults([])
      return
    }
    const timer = setTimeout(() => {
      searchStations(term)
        .then((rows) => {
          setResults(rows)
          setOpen(true)
        })
        .catch(() => setResults([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [term])

  useEffect(() => {
    const onClickAway = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [])

  const choose = (row) => {
    onSelect(row)
    setTerm('')
    setResults([])
    setOpen(false)
  }

  return (
    <div className="search" ref={boxRef}>
      <input
        type="search"
        value={term}
        placeholder="Search stations, e.g. Herald Sq"
        onChange={(e) => setTerm(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
      />
      {open && results.length > 0 && (
        <ul className="results">
          {results.map((row) => (
            <li key={`${row.kind}-${row.id}`}>
              <button type="button" onClick={() => choose(row)}>
                <span className="result-name">{row.name}</span>
                <span className="result-routes">
                  {row.routes.map((r) => (
                    <RouteBullet key={r} route={r} />
                  ))}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && term.trim() && results.length === 0 && (
        <ul className="results">
          <li className="empty">No station matches "{term}"</li>
        </ul>
      )}
    </div>
  )
}
