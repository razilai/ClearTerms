import {
  Button,
  createTheme,
  Input,
  InputWrapper,
  Paper,
  PasswordInput,
  Slider,
  TextInput,
  type MantineColorsTuple,
} from '@mantine/core'

// "Redline" design system — contract-markup vernacular: ink on paper,
// redline red for flagged clauses, highlighter yellow for margin notes,
// green for clean clauses. Anchors live in `other` for CSS-module use.

const redline: MantineColorsTuple = [
  '#FCF0F0',
  '#F6DCDC',
  '#EBBABB',
  '#E09495',
  '#D66F72',
  '#CE5257',
  '#C6373C', // anchor
  '#A82D32',
  '#8B2428',
  '#6E1B1F',
]

const ink: MantineColorsTuple = [
  '#F2F4F7',
  '#E4E7EC',
  '#CBD1DA',
  '#AFB8C6',
  '#96A2B4',
  '#8492A6',
  '#6B7A8F',
  '#4E5A6B',
  '#333D4D',
  '#1C2433', // anchor
]

const ok: MantineColorsTuple = [
  '#EBF6F1',
  '#D6EBE0',
  '#ADD8C3',
  '#81C4A4',
  '#5DB48A',
  '#45A279',
  '#2F7D5A', // anchor
  '#276A4C',
  '#1F573E',
  '#174431',
]

const highlight: MantineColorsTuple = [
  '#FEFAEA',
  '#FCF3CD',
  '#F9EAA4',
  '#F7E077',
  '#F6DA57',
  '#F5D547', // anchor
  '#DDBC33',
  '#C4A527',
  '#AB8F1D',
  '#927914',
]

// A single-line field styled as a form blank: no box, just a ruled underline
// that inks red on focus. Reserved for TextInput/PasswordInput — the multiline
// paste/comment areas keep a boxed surface.
const ruledField = {
  input: {
    backgroundColor: 'transparent',
    border: 'none',
    borderBottom: '1.5px solid var(--mantine-color-ink-2)',
    borderRadius: 0,
    paddingLeft: 2,
    paddingRight: 2,
  },
}

export const theme = createTheme({
  white: '#FAFAF7',
  black: '#1C2433',
  colors: { redline, ink, ok, highlight },
  primaryColor: 'redline',
  primaryShade: 6,
  fontFamily: '"Public Sans", system-ui, sans-serif',
  fontFamilyMonospace: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  headings: {
    fontFamily: 'Spectral, Georgia, serif',
    fontWeight: '600',
    sizes: {
      h1: { fontSize: '2.4rem', lineHeight: '1.1', fontWeight: '600' },
      h2: { fontSize: '1.9rem', lineHeight: '1.15', fontWeight: '600' },
      h3: { fontSize: '1.4rem', lineHeight: '1.2', fontWeight: '600' },
      h4: { fontSize: '1.1rem', lineHeight: '1.25', fontWeight: '600' },
    },
  },
  defaultRadius: 2,
  other: {
    paper: '#FAFAF7',
    ink: '#1C2433',
    redline: '#C6373C',
    highlight: '#F5D547',
    ok: '#2F7D5A',
    // Hairline rule tint used across document surfaces.
    rule: 'var(--mantine-color-ink-2)',
  },
  components: {
    Paper: Paper.extend({
      defaultProps: { shadow: undefined },
      styles: {
        root: {
          borderColor: 'var(--mantine-color-ink-2)',
          backgroundColor: 'var(--mantine-color-white)',
        },
      },
    }),
    Button: Button.extend({
      defaultProps: { radius: 2 },
      styles: { label: { fontWeight: 600, letterSpacing: '0.02em' } },
    }),
    TextInput: TextInput.extend({ styles: ruledField }),
    PasswordInput: PasswordInput.extend({ styles: ruledField }),
    Input: Input.extend({
      styles: {
        input: { '::placeholder': { color: 'var(--mantine-color-ink-4)' } },
      },
    }),
    // Labels read as filing captions: small, uppercase, letterspaced mono.
    InputWrapper: InputWrapper.extend({
      styles: {
        label: {
          fontFamily: 'var(--mantine-font-family-monospace)',
          fontSize: '0.7rem',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--mantine-color-ink-6)',
          marginBottom: 6,
        },
        description: { color: 'var(--mantine-color-ink-5)' },
      },
    }),
    // The redline treatment the plan called for: a red bar advancing over an
    // ink track, with a squared, ink-bordered thumb like a redaction marker.
    Slider: Slider.extend({
      defaultProps: { color: 'redline' },
      styles: {
        track: { backgroundColor: 'var(--mantine-color-ink-1)' },
        bar: { backgroundColor: 'var(--mantine-color-redline-6)' },
        thumb: {
          borderRadius: 1,
          border: '2px solid var(--mantine-color-ink-9)',
          backgroundColor: 'var(--mantine-color-redline-6)',
          width: 16,
          height: 16,
        },
        markLabel: {
          fontFamily: 'var(--mantine-font-family-monospace)',
          fontSize: '0.65rem',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          color: 'var(--mantine-color-ink-5)',
        },
        mark: { borderColor: 'var(--mantine-color-ink-3)' },
      },
    }),
  },
})
