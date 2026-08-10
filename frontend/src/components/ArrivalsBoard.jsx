import RouteBullet from './RouteBullet.jsx'

// The feed labels every stop N or S; on a platform board that reads as
// uptown and downtown, which is how riders pick a side.
const COLUMNS = [
  { direction: 'N', label: 'Uptown / Northbound' },
  { direction: 'S', label: 'Downtown / Southbound' },
]

function minutesLabel(minutes) {
  if (minutes < 0.5) return 'Now'
  return `${Math.round(minutes)} min`
}

export default function ArrivalsBoard({ arrivals }) {
  return (
    <div className="board">
      {COLUMNS.map(({ direction, label }) => {
        const forDirection = arrivals.filter((a) => a.direction === direction)
        return (
          <section key={direction} className="card">
            <h3 className="eyebrow">{label}</h3>
            {forDirection.length === 0 ? (
              <ul>
                <li>
                  <span className="muted">No trains reported</span>
                </li>
              </ul>
            ) : (
              <ul>
                {forDirection.map((a, i) => (
                  <li key={`${a.route}-${a.arrival_time}-${i}`}>
                    <RouteBullet
                      route={a.route_name}
                      express={a.express}
                      title={a.route_long_name}
                    />
                    <span className="minutes">{minutesLabel(a.minutes_away)}</span>
                    <span className="clock">
                      {new Date(a.arrival_time).toLocaleTimeString([], {
                        hour: 'numeric',
                        minute: '2-digit',
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )
}
