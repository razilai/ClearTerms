import { Alert, Anchor, Box, Stack, Text, Title } from '@mantine/core'
import { Link } from 'react-router-dom'

interface Props {
  feature: string
  compact?: boolean
}

export function BackendNotReady({ feature, compact }: Props) {
  if (compact) {
    return (
      <Alert color="ink" variant="light" radius={2}>
        {feature} isn&apos;t available yet — the backend for it is still being
        built. What you see below is a preview.
      </Alert>
    )
  }

  return (
    <Box
      p="xl"
      mt="xl"
      style={{
        position: 'relative',
        overflow: 'hidden',
        border: '1px dashed var(--mantine-color-ink-4)',
        borderRadius: 2,
        backgroundColor: 'var(--mantine-color-white)',
      }}
    >
      <Text
        aria-hidden
        style={{
          position: 'absolute',
          right: 24,
          top: -40,
          fontFamily: 'Spectral, Georgia, serif',
          fontSize: 160,
          lineHeight: 1,
          color: 'var(--mantine-color-ink-1)',
          userSelect: 'none',
        }}
      >
        §
      </Text>
      <Stack gap="xs" style={{ position: 'relative' }}>
        <Title order={2}>This section is still being drafted</Title>
        <Text c="ink.7" maw={480}>
          The {feature} service isn&apos;t available yet. Your account and the{' '}
          <Anchor component={Link} to="/forum">
            forum
          </Anchor>{' '}
          are working — check back soon.
        </Text>
      </Stack>
    </Box>
  )
}
