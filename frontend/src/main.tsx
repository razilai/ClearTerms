import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@fontsource/spectral/400.css'
import '@fontsource/spectral/400-italic.css'
import '@fontsource/spectral/500.css'
import '@fontsource/spectral/600.css'
import '@fontsource/public-sans/400.css'
import '@fontsource/public-sans/500.css'
import '@fontsource/public-sans/600.css'
import './theme/global.css'

import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from './AppLayout'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { AnalysisDetailPage } from './pages/AnalysisDetailPage'
import { AnalyzePage } from './pages/AnalyzePage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { NewPostPage } from './pages/NewPostPage'
import { PostDetailPage } from './pages/PostDetailPage'
import { PostListPage } from './pages/PostListPage'
import { SettingsPage } from './pages/SettingsPage'
import { SignupPage } from './pages/SignupPage'
import { theme } from './theme/theme'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignupPage />} />
              <Route element={<RequireAuth />}>
                <Route element={<AppLayout />}>
                  <Route path="/analyze" element={<AnalyzePage />} />
                  <Route
                    path="/analyses/:analysisId"
                    element={<AnalysisDetailPage />}
                  />
                  <Route path="/history" element={<HistoryPage />} />
                  <Route path="/forum" element={<PostListPage />} />
                  <Route path="/forum/new" element={<NewPostPage />} />
                  <Route path="/forum/:postId" element={<PostDetailPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/analyze" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
)
