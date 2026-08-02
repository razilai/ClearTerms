import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { analyze, getAnalysis } from '../api/analysis'
import { isNotReady } from '../api/client'
import type { VerdictResponse } from '../api/types'
import { AnalysisReport } from '../components/AnalysisReport'
import { BackendNotReady } from '../components/BackendNotReady'
import { PageHeader } from '../components/PageHeader'
import { VerdictStamp } from '../components/VerdictStamp'
import classes from './AnalyzePage.module.css'

export function AnalyzePage() {
  const queryClient = useQueryClient()
  const [result, setResult] = useState<VerdictResponse | null>(null)

  const form = useForm({
    initialValues: { text: '', url: '' },
    validate: {
      text: (v) => (v.trim().length > 0 ? null : 'Paste the terms to analyze'),
      url: (v) => {
        if (!v.trim()) return null
        try {
          new URL(v.trim())
          return null
        } catch {
          return 'Enter a full URL, or leave this empty'
        }
      },
    },
  })

  const mutation = useMutation({
    mutationFn: analyze,
    onSuccess: (res) => {
      setResult(res)
      // The backend appends a history entry for every analysis.
      queryClient.invalidateQueries({ queryKey: ['history'] })
    },
    onError: (err) => {
      if (!isNotReady(err)) {
        notifications.show({ color: 'red', message: err.message })
      }
    },
  })

  const analysisId = result?.analysis_id
  const detailQuery = useQuery({
    queryKey: ['analysis', analysisId],
    queryFn: () => getAnalysis(analysisId as number),
    enabled: analysisId != null,
  })

  const handleSubmit = form.onSubmit(({ text, url }) => {
    setResult(null)
    mutation.mutate({ text: text.trim(), url: url.trim() || null })
  })

  return (
    <Box>
      <PageHeader
        eyebrow="§1 · New analysis"
        title="Analyze a document"
        description="Paste terms of service and get a verdict on the clauses that matter to you."
      />
      <form onSubmit={handleSubmit}>
        <Textarea
          label="Terms of service text"
          placeholder="Paste the full terms here…"
          autosize
          minRows={12}
          maxRows={22}
          disabled={mutation.isPending}
          classNames={{ input: classes.pasteArea }}
          {...form.getInputProps('text')}
        />
        <TextInput
          label="Source URL"
          description="Optional — where this document lives"
          placeholder="https://example.com/terms"
          mt="lg"
          ff="monospace"
          disabled={mutation.isPending}
          {...form.getInputProps('url')}
        />
        <Group justify="space-between" mt="xl">
          <span className={classes.statusLine}>
            {mutation.isPending ? 'Reading the document…' : ''}
          </span>
          <Button type="submit" loading={mutation.isPending}>
            Analyze document
          </Button>
        </Group>
      </form>

      {mutation.error && isNotReady(mutation.error) && (
        <BackendNotReady feature="Analysis" />
      )}

      {result && (
        <Paper withBorder p="lg" mt="xl">
          <Center mb="lg">
            <VerdictStamp verdict={result.verdict} size="lg" />
          </Center>
          {detailQuery.isPending && (
            <Group justify="center" gap="xs" py="md">
              <Loader size="sm" />
              <Text size="sm" c="ink.6">
                Preparing the clause breakdown…
              </Text>
            </Group>
          )}
          {detailQuery.error &&
            (isNotReady(detailQuery.error) ? (
              <Text size="sm" c="ink.6" ta="center" py="md">
                Clause breakdown isn&apos;t available yet.
              </Text>
            ) : (
              <Alert color="red" mt="md">
                Failed to load the clause breakdown: {detailQuery.error.message}
              </Alert>
            ))}
          {detailQuery.data && (
            <Box mt="md">
              <AnalysisReport detail={detailQuery.data} />
            </Box>
          )}
        </Paper>
      )}
    </Box>
  )
}
