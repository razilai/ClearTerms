// Bundles each src entrypoint to a flat classic-script file in dist/, then
// copies public/* verbatim. `node build.mjs --watch` rebuilds on change.
// Kept dependency-free beyond esbuild — MV3 loads the emitted files directly.

import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as esbuild from 'esbuild'

const root = dirname(fileURLToPath(import.meta.url))
const outdir = resolve(root, 'dist')
const watch = process.argv.includes('--watch')

// esbuild emits ESM by default; MV3 content scripts must be classic scripts and
// the worker is registered as one too (manifest omits "type":"module"), so we
// bundle every entrypoint to a self-contained IIFE.
const options = {
  entryPoints: [
    resolve(root, 'src/background.ts'),
    resolve(root, 'src/content-detector.ts'),
    resolve(root, 'src/content-token.ts'),
    resolve(root, 'src/popup.ts'),
  ],
  bundle: true,
  format: 'iife',
  target: 'chrome110',
  outdir,
  logLevel: 'info',
}

function copyPublic() {
  // public/ holds the manifest, popup markup/styles, and icons — copied as-is.
  cpSync(resolve(root, 'public'), outdir, { recursive: true })
}

rmSync(outdir, { recursive: true, force: true })
mkdirSync(outdir, { recursive: true })

if (watch) {
  const ctx = await esbuild.context(options)
  await ctx.rebuild()
  copyPublic()
  await ctx.watch()
  console.log('watching… (public/ is copied once; rerun build to refresh it)')
} else {
  await esbuild.build(options)
  copyPublic()
}
