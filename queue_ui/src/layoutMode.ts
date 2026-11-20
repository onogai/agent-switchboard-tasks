/** Queue can run independently or behind Switchboard Manager.
 * Only the same-origin Manager-embedded frame drops Queue's standalone sidebar.
 */
export function queueLayout(pathname: string, insideFrame: boolean) {
  const managed = pathname === '/admin/queue' || pathname.startsWith('/admin/queue/')
  return {
    managed,
    embedded: managed && insideFrame,
  }
}
