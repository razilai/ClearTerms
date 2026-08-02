import type { ReactNode } from 'react'

import classes from './Eyebrow.module.css'

// The filing caption used above titles and inside auth cards: a small,
// letterspaced monospace label in redline.
export function Eyebrow({ children, mb = 6 }: { children: ReactNode; mb?: number }) {
  return (
    <div className={classes.eyebrow} style={{ marginBottom: mb }}>
      {children}
    </div>
  )
}
