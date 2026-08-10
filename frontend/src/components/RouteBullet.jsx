import { routeColor, routeTextColor } from '../routeColors.js'

// MTA signage convention: a circle is local service, a diamond is express.
// The API supplies the rider-facing name and the express flag, so this stays
// a dumb renderer.
export default function RouteBullet({ route, express = false, title }) {
  const style = { background: routeColor(route), color: routeTextColor(route) }
  const className = express ? 'bullet bullet-express' : 'bullet'

  return (
    <span className={className} style={style} title={title || undefined}>
      <span className="bullet-text">{route}</span>
    </span>
  )
}
