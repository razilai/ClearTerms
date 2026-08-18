import { Alert, Button, PasswordInput, TextInput } from '@mantine/core'
import { useForm } from '@mantine/form'
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { signup as apiSignup } from '../api/auth'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/useAuth'
import { AuthScaffold } from '../components/AuthScaffold'
import { MAX_EMAIL_CHARS, MAX_PASSWORD_CHARS } from '../lib/limits'

export function SignupPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const form = useForm({
    initialValues: { email: '', password: '', confirm: '' },
    validate: {
      email: (v) => (/^\S+@\S+\.\S+$/.test(v) ? null : 'Invalid email'),
      password: (v) =>
        v.length >= 8 ? null : 'Password must be at least 8 characters',
      confirm: (v, values) =>
        v === values.password ? null : 'Passwords do not match',
    },
  })

  if (auth.token) return <Navigate to="/analyze" replace />

  const handleSubmit = form.onSubmit(async ({ email, password }) => {
    setError(null)
    setSubmitting(true)
    try {
      const { access_token } = await apiSignup(email, password)
      auth.login(access_token, email.toLowerCase())
      navigate('/analyze')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Signup failed')
    } finally {
      setSubmitting(false)
    }
  })

  return (
    <AuthScaffold
      eyebrow="New account"
      title="Create account"
      switchPrompt="Already registered?"
      switchLabel="Log in"
      switchTo="/login"
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
          placeholder="At least 8 characters"
          mt="md"
          maxLength={MAX_PASSWORD_CHARS}
          {...form.getInputProps('password')}
        />
        <PasswordInput
          label="Confirm password"
          mt="md"
          maxLength={MAX_PASSWORD_CHARS}
          {...form.getInputProps('confirm')}
        />
        <Button type="submit" fullWidth mt="xl" loading={submitting}>
          Sign up
        </Button>
      </form>
    </AuthScaffold>
  )
}
