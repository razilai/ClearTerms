import classes from './VerdictStamp.module.css'

interface Props {
  verdict: string
  size?: 'sm' | 'lg'
}

// Verdict values are "up"/"down" today, but the column is a free string —
// anything else gets a neutral ink stamp of the raw value.
const KNOWN: Record<string, { label: string; className: string }> = {
  up: { label: 'Approved', className: classes.up },
  down: { label: 'Objection', className: classes.down },
}

export function VerdictStamp({ verdict, size = 'lg' }: Props) {
  const known = KNOWN[verdict]
  const label = known?.label ?? verdict
  const color = known?.className ?? classes.unknown
  return (
    <span
      className={`${classes.stamp} ${classes[size]} ${color}`}
      role="img"
      aria-label={`Verdict: ${label}`}
    >
      {label}
    </span>
  )
}
