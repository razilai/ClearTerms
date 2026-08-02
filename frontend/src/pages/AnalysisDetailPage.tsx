import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  Paper,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { getAnalysis } from '../api/analysis'
import { ApiError, isNotReady } from '../api/client'
import { AnalysisReport } from '../components/AnalysisReport'
import { BackendNotReady } from '../components/BackendNotReady'

export function AnalysisDetailPage() {
  const { analysisId: analysisIdParam } = useParams()
  const analysisId = Number(analysisIdParam)
  const navigate = useNavigate()

  const { data, isPending, error } = useQuery({
    queryKey: ['analysis', analysisId],
    queryFn: () => getAnalysis(analysisId),
  })

  if (isPending) {
    return (
      <Center mt="xl">
        <Loader />
      </Center>
    )
  }

  if (error) {
    if (isNotReady(error)) {
      return (
        <Container size="md">
          <BackendNotReady feature="Analysis" />
        </Container>
      )
    }
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <Container size="md">
        <Alert color="red" mt="md">
          {notFound
            ? 'This analysis does not exist.'
            : `Failed to load the analysis: ${error.message}`}
        </Alert>
        <Button variant="default" mt="md" onClick={() => navigate('/history')}>
          Back to history
        </Button>
      </Container>
    )
  }

  return (
    <Container size="md">
      <Button
        variant="subtle"
        color="ink"
        size="xs"
        mb="sm"
        onClick={() => navigate('/history')}
      >
        ← History
      </Button>
      <Paper withBorder p="lg">
        <AnalysisReport detail={data} />
      </Paper>
    </Container>
  )
}
