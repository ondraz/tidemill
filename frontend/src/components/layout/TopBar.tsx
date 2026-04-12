import { Show, UserButton } from '@clerk/react'

export function TopBar() {
  return (
    <header className="h-12 border-b border-tremor-border bg-tremor-background flex items-center justify-end px-4 gap-3 shrink-0">
      <Show when="signed-in">
        <UserButton />
      </Show>
    </header>
  )
}
