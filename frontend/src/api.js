// Thin wrapper over the REST API. Every call goes to the same origin that
// served this page, so there is no base URL and no CORS.

async function get(path) {
  const res = await fetch(path)
  if (!res.ok) {
    const error = new Error(`${res.status} ${res.statusText}`)
    error.status = res.status
    try {
      error.detail = (await res.json()).detail
    } catch {
      error.detail = null
    }
    throw error
  }
  return res.json()
}

// A search result is either a complex (several GTFS stations) or a lone
// station, and it says which, so the same picker drives both endpoints.
const base = ({ kind, id }) =>
  kind === 'complex' ? `/v1/complexes/${id}` : `/v1/stations/${id}`

export const searchStations = (term) =>
  get(`/v1/stations?search=${encodeURIComponent(term)}&limit=10`)

export const fetchArrivals = (target) => get(`${base(target)}/arrivals`)

export const fetchHeadways = (target, hours = 24) =>
  get(`/v1/stats/${target.kind === 'complex' ? 'complexes' : 'stations'}/${target.id}/headways?hours=${hours}`)
