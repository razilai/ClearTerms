import { AppShell, Burger, Button, Group, NavLink, Stack, Text } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import classes from './AppLayout.module.css'
import { useAuth } from './auth/useAuth'

// The app is literally a numbered set of sections — the § markers are
// structure, not decoration.
const NAV_ITEMS = [
  { to: '/analyze', label: 'Analysis', section: '§1' },
  { to: '/history', label: 'History', section: '§2' },
  { to: '/forum', label: 'Forum', section: '§3' },
  { to: '/messages', label: 'Messages', section: '§4' },
  { to: '/me', label: 'Personal Area', section: '§5' },
]

function isActive(pathname: string, to: string): boolean {
  // Analysis detail pages are reached from History; keep History lit there.
  if (to === '/history') {
    return pathname.startsWith('/history') || pathname.startsWith('/analyses')
  }
  return pathname.startsWith(to)
}

export function AppLayout() {
  const { email, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [asideOpened, { toggle: toggleAside, close: closeAside }] =
    useDisclosure(false)

  return (
    <AppShell
      header={{ height: 60 }}
      aside={{
        width: 232,
        breakpoint: 'sm',
        collapsed: { mobile: !asideOpened },
      }}
      padding="lg"
    >
      <AppShell.Header className={classes.header}>
        <Group h="100%" px="lg" justify="space-between">
          <Group gap="sm" align="baseline">
            <Link to="/analyze" className={classes.brand}>
              ClearTerms
            </Link>
            <span className={classes.brandMark}>Terms Review</span>
          </Group>
          <Group gap="md">
            <Text className={classes.email} visibleFrom="xs">
              {email}
            </Text>
            <Button
              variant="subtle"
              color="ink"
              size="xs"
              onClick={() => {
                logout()
                navigate('/login')
              }}
            >
              Log out
            </Button>
            <Burger
              opened={asideOpened}
              onClick={toggleAside}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Aside className={classes.aside}>
        <Stack h="100%" gap={0} pt="md">
          <div className={classes.asideEyebrow}>Sections</div>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              component={Link}
              to={item.to}
              label={<span className={classes.navLabel}>{item.label}</span>}
              leftSection={
                <span className={classes.section}>{item.section}</span>
              }
              active={isActive(pathname, item.to)}
              className={classes.navLink}
              onClick={closeAside}
            />
          ))}
          <div className={classes.asideFoot}>
            Clear Terms
            <br />
            Plain-language review
            <br />
            Rev. 2026.08
          </div>
        </Stack>
      </AppShell.Aside>
      <AppShell.Main>
        <div className={classes.main}>
          <Outlet />
        </div>
      </AppShell.Main>
    </AppShell>
  )
}
