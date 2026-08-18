import { Alert, Button, PasswordInput, TextInput } from '@mantine/core'
import { useForm } from '@mantine/form'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { login as apiLogin } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { AuthScaffold } from '../components/AuthScaffold'
import { MAX_EMAIL_CHARS, MAX_PASSWORD_CHARS } from '../lib/limits'

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const form = useForm({
    initialValues: { email: '', password: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : 'Invalid email'),
      password: (v) => (v.length > 0 ? null : 'Password is required'),
    },
  })

  if (auth.token) return <Navigate to="/analyze" replace />

  const handleSubmit = form.onSubmit(async ({ email, password }) => {
    setError(null)
    setSubmitting(true)
    try {
      const { access_token } = await apiLogin(email, password)
      auth.login(access_token, email.toLowerCase())
      navigate('/analyze')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  })

  return (
    <AuthScaffold
      eyebrow="Sign in"
      title="ClearTerms"
      switchPrompt="Don't have an account?"
      switchLabel="Sign up"
      switchTo="/signup"
    >
      <form onSubmit={handleSubmit}>
        {error && (
          <Alert color="red" mb="md">
            {error}
          </Alert>
        )}
        <TextInput
          label="Email"
          placeholder="you@example.com"
          maxLength={MAX_EMAIL_CHARS}
          {...form.getInputProps('email')}
        />
        <PasswordInput
          label="Password"
          placeholder="Your password"
          mt="md"
          maxLength={MAX_PASSWORD_CHARS}
          {...form.getInputProps('password')}
        />
        <Button type="submit" fullWidth mt="xl" loading={submitting}>
          Log in
        </Button>
      </form>
    </AuthScaffold>
  )
}
