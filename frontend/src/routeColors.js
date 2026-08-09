// Official MTA line colors, so a route bullet looks like the real thing.
// Pure data: keeping this here avoids pulling in an icon dependency.
const COLORS = {
  '1': '#ee352e', '2': '#ee352e', '3': '#ee352e',
  '4': '#00933c', '5': '#00933c', '6': '#00933c',
  '7': '#b933ad',
  A: '#0039a6', C: '#0039a6', E: '#0039a6',
  B: '#ff6319', D: '#ff6319', F: '#ff6319', M: '#ff6319',
  G: '#6cbe45',
  J: '#996633', Z: '#996633',
  L: '#a7a9ac',
  N: '#fccc0a', Q: '#fccc0a', R: '#fccc0a', W: '#fccc0a',
  S: '#808183', SI: '#0039a6',
}

// The yellow and gray lines need dark text to stay readable.
const DARK_TEXT = new Set(['N', 'Q', 'R', 'W', 'L', 'S'])

export const routeColor = (route) => COLORS[route.toUpperCase()] ?? '#4a4a4a'
export const routeTextColor = (route) =>
  DARK_TEXT.has(route.toUpperCase()) ? '#111' : '#fff'
