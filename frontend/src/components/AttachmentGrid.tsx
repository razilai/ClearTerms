import { ActionIcon, Box, Group, Image, Skeleton, Text } from '@mantine/core'
import type { AttachmentOut } from '../api/types'

interface Props {
  attachments: AttachmentOut[]
}

function AttachmentItem({ a }: { a: AttachmentOut }) {
  if (a.status === 'pending') {
    return <Skeleton height={80} width={80} radius="sm" />
  }

  if (a.status === 'failed') {
    return (
      <Box
        style={{
          width: 80,
          height: 80,
          border: '1px solid var(--mantine-color-red-3)',
          borderRadius: 'var(--mantine-radius-sm)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text size="xs" c="red.5">
          Failed
        </Text>
      </Box>
    )
  }

  if (a.media_type === 'image' && a.display_url) {
    return (
      <Box
        component="a"
        href={a.display_url}
        target="_blank"
        rel="noopener noreferrer"
        style={{ display: 'block' }}
      >
        <Image
          src={a.thumbnail_url ?? a.display_url}
          alt="attachment"
          width={80}
          height={80}
          fit="cover"
          radius="sm"
          style={{ cursor: 'pointer' }}
        />
      </Box>
    )
  }

  if (a.media_type === 'video' && a.display_url) {
    return (
      <Box style={{ position: 'relative', width: 80, height: 80 }}>
        <video
          src={a.display_url}
          poster={a.thumbnail_url ?? undefined}
          controls
          style={{
            width: 80,
            height: 80,
            objectFit: 'cover',
            borderRadius: 'var(--mantine-radius-sm)',
            display: 'block',
          }}
        />
        {!a.thumbnail_url && (
          <Box
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            <ActionIcon variant="white" size="md" radius="xl" aria-label="Play video">
              ▶
            </ActionIcon>
          </Box>
        )}
      </Box>
    )
  }

  return null
}

export function AttachmentGrid({ attachments }: Props) {
  if (!attachments.length) return null
  return (
    <Group gap="xs" mt="xs" wrap="wrap">
      {attachments.map((a) => (
        <AttachmentItem key={a.id} a={a} />
      ))}
    </Group>
  )
}
