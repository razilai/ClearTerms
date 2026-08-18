import { Group, Text } from '@mantine/core'

import type { CategoryScore } from '../api/types'
import { labelFor, stoplightFor } from '../lib/categories'
import classes from './ScoreMark.module.css'

interface Props {
  entry: CategoryScore
  index: number
}

// One clause row: § index, category label, then a stoplight light — green when
// the clause is clear, yellow for standard terms, red for aggressive ones.
export function ScoreMark({ entry, index }: Props) {
  const light = stoplightFor(entry.score)

  return (
    <div className={classes.row}>
      <Group gap="sm" wrap="nowrap">
        <span className={classes.index}>§ {index + 1}</span>
        <Text className={classes.label} size="sm">
          {labelFor(entry.category)}
        </Text>
        <div className={classes.track} />
        <Group gap="xs" wrap="nowrap" className={classes.light}>
          <span
            className={classes.dot}
            style={{ backgroundColor: `var(--mantine-color-${light.color}-6)` }}
            role="img"
            aria-label={light.label}
          />
          <Text size="xs" c={`${light.color}.7`}>
            {light.label}
          </Text>
        </Group>
      </Group>
      {entry.findings.length > 0 && (
        <div className={classes.findings}>
          {entry.findings.map((finding, i) => (
            // No id on the wire — storage identity stays server-side — and the
            // list is static per render, so the index is a stable key.
            <div key={i} className={classes.finding}>
              <div className={classes.note}>{finding.evidence}</div>
              <div className={classes.gloss}>{finding.explanation}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
