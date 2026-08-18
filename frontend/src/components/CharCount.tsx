import { Group, Text } from '@mantine/core'

type Props = {
  value: string
  max: number
  /**
   * Fraction of `max` the value must reach before the counter appears. The
   * default keeps it out of the way until the limit is close enough to matter;
   * pass 0 for an input where the limit is part of the job (the analyze paste
   * box) rather than a guardrail you rarely meet.
   */
  showFrom?: number
}

/**
 * Right-aligned "used / limit" line for a text input.
 *
 * Display only — it never trims the value. Enforcement is the input's own
 * maxLength (where silent truncation is harmless) or a form validator (where it
 * isn't); either way the server has the last word.
 */
export function CharCount({ value, max, showFrom = 0.8 }: Props) {
  const used = value.length
  if (used < max * showFrom) return null
  const atLimit = used >= max
  return (
    <Group justify="flex-end" mt={6}>
      <Text size="xs" c={atLimit ? 'red' : 'ink.6'} fw={atLimit ? 600 : 400}>
        {used.toLocaleString()} / {max.toLocaleString()} characters
      </Text>
    </Group>
  )
}
