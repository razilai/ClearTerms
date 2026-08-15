import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  Slider,
  Stack,
  Text,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { isNotReady } from '../api/client'
import { getPreferences, updatePreferences } from '../api/preferences'
import type { PreferenceItem } from '../api/types'
import { BackendNotReady } from './BackendNotReady'
import {
  CATEGORY_DESCRIPTIONS,
  CATEGORY_ORDER,
  DEFAULT_WEIGHT,
  labelFor,
} from '../lib/categories'

const MARKS = [
  { value: 0, label: 'Ignore' },
  { value: 0.5 },
  { value: 1, label: 'Full weight' },
]

function withDefaults(items?: PreferenceItem[]) {
  const merged: Record<string, number> = {}
  for (const category of CATEGORY_ORDER) merged[category] = DEFAULT_WEIGHT
  for (const item of items ?? []) merged[item.category] = item.weight
  return merged
}

// The preference sliders, headerless so the personal area can frame them as one
// of its sections.
export function PreferencesPanel() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['preferences'],
    queryFn: getPreferences,
  })
  const [weights, setWeights] = useState<Record<string, number> | null>(null)

  const baseline = useMemo(() => withDefaults(query.data?.items), [query.data])

  // Seed local slider state once the server answers; user edits win after that.
  useEffect(() => {
    if (query.data && weights === null) {
      setWeights(withDefaults(query.data.items))
    }
  }, [query.data, weights])

  const mutation = useMutation({
    mutationFn: updatePreferences,
    onSuccess: (res) => {
      queryClient.setQueryData(['preferences'], res)
      setWeights(withDefaults(res.items))
      notifications.show({ color: 'ok', message: 'Preferences saved' })
    },
    onError: (err) => {
      notifications.show({
        color: 'red',
        message: isNotReady(err)
          ? "Preferences can't be saved yet — the backend isn't ready."
          : err.message,
      })
    },
  })

  if (query.isPending) {
    return (
      <Center my="xl">
        <Loader />
      </Center>
    )
  }

  const notReady = isNotReady(query.error)
  if (query.error && !notReady) {
    return (
      <Alert color="red" mt="md">
        Failed to load preferences: {query.error.message}
      </Alert>
    )
  }

  const display = weights ?? withDefaults()
  const categories = [
    ...CATEGORY_ORDER,
    ...Object.keys(display).filter(
      (c) => !(CATEGORY_ORDER as readonly string[]).includes(c),
    ),
  ]
  const dirty =
    weights !== null &&
    categories.some((c) => (weights[c] ?? 0) !== (baseline[c] ?? 0))

  const save = () => {
    mutation.mutate(
      categories.map((category) => ({
        category,
        weight: display[category] ?? DEFAULT_WEIGHT,
      })),
    )
  }

  return (
    <>
      {notReady && (
        <Box mb="md">
          <BackendNotReady feature="Preferences" compact />
        </Box>
      )}
      <Paper withBorder p="lg">
        <Stack gap="xl">
          {categories.map((category) => (
            <Box key={category}>
              <Text fw={500} size="sm" mb={2}>
                {labelFor(category)}
              </Text>
              <Text size="xs" c="ink.6" mb="xs">
                {CATEGORY_DESCRIPTIONS[category] ?? ''}
              </Text>
              <Slider
                min={0}
                max={1}
                step={0.05}
                marks={MARKS}
                label={(v) => v.toFixed(2)}
                value={display[category] ?? DEFAULT_WEIGHT}
                disabled={notReady}
                onChange={(v) =>
                  setWeights((prev) => ({ ...(prev ?? display), [category]: v }))
                }
                mb="md"
              />
            </Box>
          ))}
        </Stack>
        {!notReady && (
          <Group justify="flex-end" mt="lg">
            <Button disabled={!dirty} loading={mutation.isPending} onClick={save}>
              Save preferences
            </Button>
          </Group>
        )}
      </Paper>
    </>
  )
}
