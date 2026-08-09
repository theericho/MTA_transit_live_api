import RouteBullet from './RouteBullet.jsx'

// Surfaces the archived history: how evenly trains actually ran. Regularity
// is the share of gaps within 1.25x the median, the standard measure for
// frequency-based service (README, design decision 11).
export default function HeadwayPanel({ headways, error }) {
  if (error?.status === 404) {
    return <p className="muted">No arrivals archived here yet.</p>
  }
  if (!headways) return <p className="muted">Loading history...</p>
  if (headways.groups.length === 0) {
    return (
      <p className="muted">
        No arrivals archived in the last {headways.window_hours}h. History builds
        up while the ingestion worker runs.
      </p>
    )
  }

  return (
    <table className="headways">
      <thead>
        <tr>
          <th>Route</th>
          <th>Dir</th>
          <th>Seen</th>
          <th>Mean gap</th>
          <th>Median</th>
          <th>Regularity</th>
        </tr>
      </thead>
      <tbody>
        {headways.groups.map((g) => (
          <tr key={`${g.route}-${g.direction}`}>
            <td>
              <RouteBullet route={g.route} />
            </td>
            <td>{g.direction}</td>
            <td>{g.arrivals}</td>
            <td>{g.mean_headway_minutes ?? '-'}</td>
            <td>{g.median_headway_minutes ?? '-'}</td>
            <td>
              {g.regularity_pct == null ? (
                <span className="muted">not enough data</span>
              ) : (
                <span className="meter">
                  <span
                    className="meter-fill"
                    style={{ width: `${g.regularity_pct}%` }}
                  />
                  <span className="meter-label">{g.regularity_pct}%</span>
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
