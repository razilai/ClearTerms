import {
  Button,
  Container,
  Group,
  Paper,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { createPost } from '../api/forum'

export function NewPostPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const form = useForm({
    initialValues: { title: '', body: '', category: '' },
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

  return (
    <Container size="md">
      <Title order={2} mb="lg">
        New post
      </Title>
      <Paper withBorder p="lg">
        <form
          onSubmit={form.onSubmit(({ title, body, category }) =>
            mutation.mutate({
              title: title.trim(),
              body: body.trim(),
              category: category.trim() || null,
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
          <TextInput
            label="Category"
            description="Optional, e.g. arbitration, data collection"
            maxLength={64}
            mt="md"
            {...form.getInputProps('category')}
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
