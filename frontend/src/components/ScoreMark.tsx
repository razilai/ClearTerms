import { Group, Text } from '@mantine/core'

import type { CategoryScore } from '../api/types'
import { clampScore, labelFor, SCORE_MAX } from '../lib/categories'
import classes from './ScoreMark.module.css'

interface Props {
  entry: CategoryScore
  index: number
}

// One clause row: § index, category label, then the redline mark — an intact
// rule for a clean clause, a strike sized by severity for a flagged one.
export function ScoreMark({ entry, index }: Props) {
  const score = clampScore(entry.score)
  const flagged = score > 0

  return (
    <div className={classes.row}>
      <Group gap="sm" wrap="nowrap">
        <span className={classes.index}>§ {index + 1}</span>
        <Text className={classes.label} size="sm">
          {labelFor(entry.category)}
        </Text>
        <div className={classes.track}>
          {flagged ? (
            <div
              className={classes.strike}
              style={{
                width: `${(score / SCORE_MAX) * 100}%`,
                height: 2 + score * 2,
              }}
            />
          ) : (
            <div className={classes.clean} />
          )}
        </div>
        {flagged ? (
          <span className={classes.score}>
            {entry.score}/{SCORE_MAX}
          </span>
        ) : (
          <Text className={classes.score} c="ok.6" size="xs">
            clear
          </Text>
        )}
      </Group>
      {entry.explanation && (
        <div className={classes.note}>{entry.explanation}</div>
      )}
    </div>
  )
}
