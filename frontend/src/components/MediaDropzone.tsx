/**
 * Pre-upload dropzone: files are uploaded immediately on drop and tracked as
 * AttachmentOut objects. Once all are `ready`, the parent can submit the
 * collected IDs with the post/comment.
 *
 * Props:
 *   onChange(ids: number[]): called whenever the set of ready IDs changes.
 */

import { ActionIcon, Box, Group, Image, Progress, Stack, Text } from '@mantine/core'
import { Dropzone, type FileWithPath, IMAGE_MIME_TYPE } from '@mantine/dropzone'
import { useCallback, useRef, useState } from 'react'
import { getAttachment, uploadAttachment } from '../api/forum'
import type { AttachmentOut } from '../api/types'
import { ApiError } from '../api/client'

const VIDEO_MIME_TYPE = ['video/mp4', 'video/webm', 'video/quicktime'] as const
const ACCEPTED_MIME = [...IMAGE_MIME_TYPE, ...VIDEO_MIME_TYPE]
const MAX_IMAGE_MB = 10
const MAX_VIDEO_MB = 100

interface Slot {
  file: File
  preview: string
  state: 'uploading' | 'processing' | 'ready' | 'failed'
  attachment?: AttachmentOut
  error?: string
}

interface Props {
  onChange: (ids: number[]) => void
  disabled?: boolean
}

interface OverlayProps {
  state: Slot['state']
  error?: string
}

function SlotOverlay({ state, error }: OverlayProps) {
  if (state === 'uploading') {
    return (
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0,0,0,0.45)',
          display: 'flex',
          alignItems: 'flex-end',
          padding: 4,
        }}
      >
        <Progress value={100} animated size="xs" w="100%" />
      </Box>
    )
  }
  if (state === 'processing') {
    return (
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0,0,0,0.35)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Text size="xs" c="white">⏳</Text>
      </Box>
    )
  }
  if (state === 'failed') {
    return (
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(180,0,0,0.65)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 4,
        }}
      >
        <Text size="xs" c="white" ta="center" lineClamp={3}>
          {error ?? 'Failed'}
        </Text>
      </Box>
    )
  }
  return null
}

export function MediaDropzone({ onChange, disabled }: Props) {
  const [slots, setSlots] = useState<Slot[]>([])
  // Ref so handleDrop always reads the current length without being in deps
  const slotsLengthRef = useRef(0)
  slotsLengthRef.current = slots.length

  const updateSlot = useCallback(
    (index: number, patch: Partial<Slot>) => {
      setSlots((prev) => {
        const next = prev.map((s, i) => (i === index ? { ...s, ...patch } : s))
        const readyIds = next
          .filter((s) => s.state === 'ready' && s.attachment)
          .map((s) => s.attachment!.id)
        onChange(readyIds)
        return next
      })
    },
    [onChange],
  )

  const pollUntilReady = useCallback(
    async (slotIndex: number, attachmentId: number) => {
      for (let attempt = 0; attempt < 60; attempt++) {
        await new Promise((r) => setTimeout(r, 1500))
        try {
          const a = await getAttachment(attachmentId)
          if (a.status === 'ready') {
            updateSlot(slotIndex, { state: 'ready', attachment: a })
            return
          }
          if (a.status === 'failed') {
            updateSlot(slotIndex, { state: 'failed', error: 'Processing failed' })
            return
          }
        } catch {
          // network glitch — keep polling
        }
      }
      updateSlot(slotIndex, { state: 'failed', error: 'Timed out waiting for processing' })
    },
    [updateSlot],
  )

  const handleDrop = useCallback(
    async (files: FileWithPath[]) => {
      const startIndex = slotsLengthRef.current
      const newSlots: Slot[] = files.map((f) => ({
        file: f,
        preview: URL.createObjectURL(f),
        state: 'uploading',
      }))
      setSlots((prev) => [...prev, ...newSlots])

      await Promise.all(
        files.map(async (file, i) => {
          const slotIndex = startIndex + i
          try {
            const a = await uploadAttachment(file)
            if (a.status === 'ready') {
              updateSlot(slotIndex, { state: 'ready', attachment: a })
            } else {
              updateSlot(slotIndex, { state: 'processing', attachment: a })
              await pollUntilReady(slotIndex, a.id)
            }
          } catch (err) {
            const msg = err instanceof ApiError ? err.message : 'Upload failed'
            updateSlot(slotIndex, { state: 'failed', error: msg })
          }
        }),
      )
    },
    [updateSlot, pollUntilReady],
  )

  const removeSlot = (index: number) => {
    setSlots((prev) => {
      const next = prev.filter((_, i) => i !== index)
      const readyIds = next
        .filter((s) => s.state === 'ready' && s.attachment)
        .map((s) => s.attachment!.id)
      onChange(readyIds)
      return next
    })
  }

  return (
    <Stack gap="xs">
      <Dropzone
        onDrop={handleDrop}
        accept={ACCEPTED_MIME}
        maxSize={MAX_VIDEO_MB * 1024 * 1024}
        disabled={disabled}
        style={{ padding: '12px' }}
      >
        <Dropzone.Accept>
          <Text size="sm" c="blue" ta="center">Drop here</Text>
        </Dropzone.Accept>
        <Dropzone.Reject>
          <Text size="sm" c="red" ta="center">File type or size not supported</Text>
        </Dropzone.Reject>
        <Dropzone.Idle>
          <Text size="sm" c="dimmed" ta="center">
            Drag images or videos here, or click to select
            <br />
            <Text span size="xs">Images up to {MAX_IMAGE_MB}MB · Videos up to {MAX_VIDEO_MB}MB · Max 2 min</Text>
          </Text>
        </Dropzone.Idle>
      </Dropzone>

      {slots.length > 0 && (
        <Group gap="xs" wrap="wrap">
          {slots.map((slot, i) => (
            <Box
              key={i}
              style={{
                position: 'relative',
                width: 80,
                height: 80,
                borderRadius: 'var(--mantine-radius-sm)',
                overflow: 'hidden',
                border: '1px solid var(--mantine-color-default-border)',
              }}
            >
              <Image
                src={slot.preview}
                alt="preview"
                width={80}
                height={80}
                fit="cover"
                style={{ display: 'block' }}
              />
              <SlotOverlay state={slot.state} error={slot.error} />
              <ActionIcon
                size="xs"
                variant="filled"
                color="dark"
                radius="xl"
                style={{ position: 'absolute', top: 3, right: 3, zIndex: 2 }}
                onClick={() => removeSlot(i)}
                aria-label="Remove attachment"
              >
                ×
              </ActionIcon>
            </Box>
          ))}
        </Group>
      )}
    </Stack>
  )
}
