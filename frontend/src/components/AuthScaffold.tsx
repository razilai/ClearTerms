import { Anchor, Box, Container, Paper, Text, Title } from '@mantine/core'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import classes from './AuthScaffold.module.css'
import { Eyebrow } from './Eyebrow'

interface Props {
  eyebrow: string
  title: string
  switchPrompt: string
  switchLabel: string
  switchTo: string
  children: ReactNode
}

// Shared cover-sheet layout for the login and signup pages: letterhead title,
// a double rule, the link to the other page, and the bordered form card.
export function AuthScaffold({
  eyebrow,
  title,
  switchPrompt,
  switchLabel,
  switchTo,
  children,
}: Props) {
  return (
    <Container size={420} my={80}>
      <Title ta="center">{title}</Title>
      <Box mx="auto" mt="xs" w={64} className={classes.rule} />
      <Text c="dimmed" size="sm" ta="center" mt="sm">
        {switchPrompt}{' '}
        <Anchor component={Link} to={switchTo} size="sm">
          {switchLabel}
        </Anchor>
      </Text>
      <Paper withBorder p="xl" mt="xl" radius={2}>
        <Eyebrow mb={18}>{eyebrow}</Eyebrow>
        {children}
      </Paper>
    </Container>
  )
}
