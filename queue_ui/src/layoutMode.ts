/** Queue can run independently or behind Switchboard Manager.
 * Only the same-origin Manager-embedded frame drops Queue's standalone sidebar.
 */
/** Vite's managed build is served under the declared Task Queue instance "tasks". */
export function queueMount(pathname: string): string {
  if (pathname === '/admin/addon-ui/tasks' || pathname.startsWith('/admin/addon-ui/tasks/')) {
    return '/admin/addon-ui/tasks'
  }
  if (pathname === '/admin/queue' || pathname.startsWith('/admin/queue/')) {
    return '/admin/queue' // previous Manager ingress, until its final cleanup
  }
  return '/queue'
}

export function queueLayout(pathname: string, insideFrame: boolean) {
  const managed = queueMount(pathname) !== '/queue'
  return { managed, embedded: managed && insideFrame }
}
