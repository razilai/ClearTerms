import { Text } from '@mantine/core'

// Category tag styled as a highlighter margin note, matching the analysis
// report's explanation chips.
export function CategoryChip({ category }: { category: string }) {
  return (
    <Text
      component="span"
      size="xs"
      px={8}
      py={2}
      style={{
        backgroundColor: 'var(--mantine-color-highlight-1)',
        borderLeft: '3px solid var(--mantine-color-highlight-5)',
        fontFamily: 'Spectral, Georgia, serif',
        fontStyle: 'italic',
        color: 'var(--mantine-color-ink-8)',
        whiteSpace: 'nowrap',
      }}
    >
      {category}
    </Text>
  )
}
