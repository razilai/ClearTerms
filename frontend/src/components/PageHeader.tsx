import { Group, Title } from '@mantine/core'
import type { ReactNode } from 'react'

import { Eyebrow } from './Eyebrow'
import classes from './PageHeader.module.css'

interface Props {
  eyebrow: string
  title: string
  description?: string
  action?: ReactNode
}

// Every screen opens the same way a filing does: a small section caption, the
// title set in the document serif, and a rule closing the header band.
export function PageHeader({ eyebrow, title, description, action }: Props) {
  return (
    <div className={classes.root}>
      <Group justify="space-between" align="flex-end" wrap="nowrap">
        <div>
          <Eyebrow>{eyebrow}</Eyebrow>
          <Title order={1}>{title}</Title>
        </div>
        {action}
      </Group>
      {description && <p className={classes.description}>{description}</p>}
    </div>
  )
}
