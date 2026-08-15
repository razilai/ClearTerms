import {
  Box,
  Button,
  Container,
  Group,
  Paper,
  Switch,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import { createPost } from '../api/forum'
import { MediaDropzone } from '../components/MediaDropzone'

export function NewPostPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const attachmentIdsRef = useRef<number[]>([])

  const form = useForm({
    initialValues: { title: '', body: '', isAnonymous: false },
    validate: {
      title: (v) => (v.trim().length > 0 ? null : 'Title is required'),
      body: (v) => (v.trim().length > 0 ? null : 'Body is required'),
    },
  })

  const mutation = useMutation({
    mutationFn: createPost,
    onSuccess: (post) => {
      queryClient.invalidateQueries({ queryKey: ['posts'] })
      navigate(`/forum/${post.id}`)
    },
    onError: (err) => {
      notifications.show({ color: 'red', message: err.message })
    },
  })

  const handleAttachmentChange = useCallback((ids: number[]) => {
    attachmentIdsRef.current = ids
  }, [])

  return (
    <Container size="md">
      <Title order={2} mb="lg">
        New post
      </Title>
      <Paper withBorder p="lg">
        <form
          onSubmit={form.onSubmit(({ title, body, isAnonymous }) =>
            mutation.mutate({
              title: title.trim(),
              body: body.trim(),
              is_anonymous: isAnonymous,
              attachment_ids: attachmentIdsRef.current,
            }),
          )}
        >
          <TextInput
            label="Title"
            placeholder="What do you want to discuss?"
            maxLength={255}
            {...form.getInputProps('title')}
          />
          <Textarea
            label="Body"
            placeholder="Details, context, the clause in question…"
            autosize
            minRows={6}
            mt="md"
            {...form.getInputProps('body')}
          />
          <Box mt="md">
            <MediaDropzone onChange={handleAttachmentChange} disabled={mutation.isPending} />
          </Box>
          <Switch
            mt="md"
            label="Post anonymously"
            description="Other users see “Anonymous” instead of your email."
            {...form.getInputProps('isAnonymous', { type: 'checkbox' })}
          />
          <Group justify="flex-end" mt="xl">
            <Button variant="default" onClick={() => navigate('/forum')}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Publish
            </Button>
          </Group>
        </form>
      </Paper>
    </Container>
  )
}
