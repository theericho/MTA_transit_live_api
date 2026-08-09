import { routeColor, routeTextColor } from '../routeColors.js'

export default function RouteBullet({ route }) {
  return (
    <span
      className="bullet"
      style={{ background: routeColor(route), color: routeTextColor(route) }}
    >
      {route}
    </span>
  )
}
