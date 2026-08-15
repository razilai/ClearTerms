import {
  Alert,
  Box,
  Button,
  Center,
  Checkbox,
  Group,
  Loader,
  Paper,
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
  DEFAULT_ENABLED,
  labelFor,
} from '../lib/categories'

function withDefaults(items?: PreferenceItem[]) {
  const merged: Record<string, boolean> = {}
  for (const category of CATEGORY_ORDER) merged[category] = DEFAULT_ENABLED
  for (const item of items ?? []) merged[item.category] = item.enabled
  return merged
}

// The preference checklist, headerless so the personal area can frame them as
// one of its sections. Unchecking a category hides it from every report and
// stops it producing a thumbs-down; it never changes what gets analyzed, so
// re-checking one reveals it in analyses that already exist.
export function PreferencesPanel() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['preferences'],
    queryFn: getPreferences,
  })
  const [checked, setChecked] = useState<Record<string, boolean> | null>(null)

  const baseline = useMemo(() => withDefaults(query.data?.items), [query.data])

  // Seed local checkbox state once the server answers; user edits win after that.
  useEffect(() => {
    if (query.data && checked === null) {
      setChecked(withDefaults(query.data.items))
    }
  }, [query.data, checked])

  const mutation = useMutation({
    mutationFn: updatePreferences,
    onSuccess: (res) => {
      queryClient.setQueryData(['preferences'], res)
      setChecked(withDefaults(res.items))
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

  const display = checked ?? withDefaults()
  const categories = [
    ...CATEGORY_ORDER,
    ...Object.keys(display).filter(
      (c) => !(CATEGORY_ORDER as readonly string[]).includes(c),
    ),
  ]
  const dirty =
    checked !== null &&
    categories.some(
      (c) => (checked[c] ?? DEFAULT_ENABLED) !== (baseline[c] ?? DEFAULT_ENABLED),
    )

  const save = () => {
    mutation.mutate(
      categories.map((category) => ({
        category,
        enabled: display[category] ?? DEFAULT_ENABLED,
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
        <Text size="xs" c="ink.6" mb="lg">
          Unchecked clause types are left out of your reports and never count
          against a document. Every clause type is still analyzed, so checking
          one again brings it back — in past reviews too.
        </Text>
        <Stack gap="lg">
          {categories.map((category) => (
            <Checkbox
              key={category}
              checked={display[category] ?? DEFAULT_ENABLED}
              disabled={notReady}
              onChange={(event) => {
                const next = event.currentTarget.checked
                setChecked((prev) => ({ ...(prev ?? display), [category]: next }))
              }}
              label={
                <Box>
                  <Text fw={500} size="sm">
                    {labelFor(category)}
                  </Text>
                  <Text size="xs" c="ink.6">
                    {CATEGORY_DESCRIPTIONS[category] ?? ''}
                  </Text>
                </Box>
              }
            />
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
