// Makes `data_age_seconds` visible. The API never hides staleness (README,
// design decision 7), so neither does the dashboard: stop the ingestion
// worker and this pill walks from live to stale while trains stay listed.
export default function FreshnessBadge({ ageSeconds }) {
  if (ageSeconds == null) return null

  const level = ageSeconds < 60 ? 'fresh' : ageSeconds < 300 ? 'aging' : 'stale'
  const label =
    ageSeconds < 60
      ? `Live ${Math.round(ageSeconds)}s ago`
      : `Data ${Math.floor(ageSeconds / 60)}m old`

  return (
    <span className={`badge badge-${level}`}>
      <span className="dot" />
      {label}
    </span>
  )
}
