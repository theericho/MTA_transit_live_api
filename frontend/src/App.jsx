import { useCallback, useEffect, useState } from 'react'

import { fetchArrivals, fetchHeadways, searchStations } from './api.js'
import ArrivalsBoard from './components/ArrivalsBoard.jsx'
import FreshnessBadge from './components/FreshnessBadge.jsx'
import HeadwayPanel from './components/HeadwayPanel.jsx'
import RouteBullet from './components/RouteBullet.jsx'
import StationSearch from './components/StationSearch.jsx'

// The upstream feeds only change every ~30s, so polling twice that often is
// plenty; anything faster would just burn requests (README, design decision 15).
const POLL_MS = 15000

export default function App() {
  const [target, setTarget] = useState(null)
  const [arrivals, setArrivals] = useState(null)
  const [headways, setHeadways] = useState(null)
  const [error, setError] = useState(null)
  const [statsError, setStatsError] = useState(null)

  // Land on somewhere recognizable instead of an empty screen.
  useEffect(() => {
    searchStations('Times Sq')
      .then((rows) => rows.length && setTarget(rows[0]))
      .catch(() => {})
  }, [])

  const load = useCallback(() => {
    if (!target) return
    fetchArrivals(target)
      .then((data) => {
        setArrivals(data)
        setError(null)
      })
      .catch((err) => setError(err))
    fetchHeadways(target)
      .then((data) => {
        setHeadways(data)
        setStatsError(null)
      })
      .catch((err) => {
        setHeadways(null)
        setStatsError(err)
      })
  }, [target])

  useEffect(() => {
    setArrivals(null)
    setHeadways(null)
    load()
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [load])

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1 className="wordmark">MTA Transit Live</h1>
          <p className="tagline">
            Real-time subway arrivals from the MTA GTFS feeds, polling every{' '}
            {POLL_MS / 1000}s.
          </p>
        </div>
        <FreshnessBadge ageSeconds={arrivals?.data_age_seconds} />
      </header>

      <div className="rule" />

      <StationSearch onSelect={setTarget} />

      {!target && <p className="muted">Search for a station to begin.</p>}

      {target && (
        <main>
          <section className="hero">
            <h2 className="station-name">
              {arrivals?.station.name ?? target.name}
            </h2>
            <span className="result-routes">
              {(arrivals?.station.routes ?? target.routes).map((r) => (
                <RouteBullet key={r} route={r} />
              ))}
            </span>
          </section>

          {error?.status === 503 && (
            <p className="notice">
              Waiting for the ingestion worker's first poll. This page refreshes
              itself, so it will fill in shortly.
            </p>
          )}
          {error && error.status !== 503 && (
            <p className="notice error">
              Could not load arrivals: {error.detail ?? error.message}
            </p>
          )}

          {arrivals && <ArrivalsBoard arrivals={arrivals.arrivals} />}
          {arrivals && arrivals.arrivals.length === 0 && !error && (
            <p className="muted">
              Nothing upcoming right now. Late nights and quiet stations look
              like this.
            </p>
          )}

          <section className="panel">
            <h3 className="eyebrow">Service regularity</h3>
            {headways && headways.groups.length > 0 && (
              <p className="muted panel-summary">
                {headways.total_arrivals} arrivals observed in the last{' '}
                {headways.window_hours}h
              </p>
            )}
            <div className="panel-body">
              <HeadwayPanel headways={headways} error={statsError} />
            </div>
          </section>
        </main>
      )}
    </div>
  )
}
