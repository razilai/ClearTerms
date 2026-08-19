import {
  AppShell,
  Badge,
  Burger,
  Button,
  Group,
  NavLink,
  Stack,
  Text,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { getUnreadTotal, unreadKey } from './api/messages'
import classes from './AppLayout.module.css'
import { useAuth } from './auth/useAuth'
import { NotificationBell } from './components/NotificationBell'
import { useNotificationToasts } from './lib/useNotificationToasts'

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
  // Polled so a message that arrives while the user sits on another section
  // still shows up; MessagesPage also invalidates this on mount, so opening
  // the inbox refreshes it immediately rather than waiting out the interval.
  const { data: unread } = useQuery({
    queryKey: unreadKey,
    queryFn: getUnreadTotal,
    refetchInterval: 30_000,
  })
  const unreadCount = unread?.unread_count ?? 0
  // Polls the notification feed and toasts new events; the count it returns
  // drives the bell. Independent of the §4 badge above: that counts messages
  // not yet opened, this counts events not yet acknowledged.
  const notificationCount = useNotificationToasts()

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
            <NotificationBell unreadCount={notificationCount} />
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
              rightSection={
                item.to === '/messages' && unreadCount > 0 ? (
                  <Badge size="sm" circle>
                    {unreadCount}
                  </Badge>
                ) : undefined
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
