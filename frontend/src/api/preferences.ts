import { request, requestJson } from './client'
import type { PreferenceItem, PreferencesResponse } from './types'

export function getPreferences(): Promise<PreferencesResponse> {
  return request<PreferencesResponse>('/preferences')
}

export function updatePreferences(
  items: PreferenceItem[],
): Promise<PreferencesResponse> {
  return requestJson<PreferencesResponse>('/preferences', 'PUT', { items })
}
