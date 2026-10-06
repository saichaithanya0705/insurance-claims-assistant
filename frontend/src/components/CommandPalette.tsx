import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CornerDownLeft, Search } from 'lucide-react'
import { cx } from '../lib/format'

export interface PaletteCommand {
  id: string
  group: string
  label: string
  hint?: string
  icon: ReactNode
  run: () => void
  disabled?: boolean
}

/**
 * Command palette on a native modal <dialog>: top layer, focus trapping and Esc
 * handling come from the platform. `closedby="any"` adds light dismiss where
 * supported, with the documented click-outside fallback for other browsers.
 */
export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean
  onClose: () => void
  commands: PaletteCommand[]
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(0)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      setQuery('')
      setSelected(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    } else if (!open && dialog.open) dialog.close()
  }, [open])

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    const handleClose = () => onClose()
    dialog.addEventListener('close', handleClose)
    // Fallback for browsers without <dialog closedby> support.
    const supportsClosedBy = 'closedBy' in HTMLDialogElement.prototype
    const handleClick = (event: MouseEvent) => {
      if (supportsClosedBy || event.target !== dialog) return
      const rect = dialog.getBoundingClientRect()
      const inside =
        rect.top <= event.clientY && event.clientY <= rect.top + rect.height && rect.left <= event.clientX && event.clientX <= rect.left + rect.width
      if (!inside) dialog.close()
    }
    dialog.addEventListener('click', handleClick)
    return () => {
      dialog.removeEventListener('close', handleClose)
      dialog.removeEventListener('click', handleClick)
    }
  }, [onClose])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const enabled = commands.filter((c) => !c.disabled)
    if (!q) return enabled
    return enabled.filter((c) => `${c.group} ${c.label} ${c.hint ?? ''}`.toLowerCase().includes(q))
  }, [commands, query])

  const execute = (command?: PaletteCommand) => {
    if (!command) return
    dialogRef.current?.close()
    command.run()
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSelected((s) => (s + 1) % Math.max(filtered.length, 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSelected((s) => (s - 1 + filtered.length) % Math.max(filtered.length, 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      execute(filtered[selected])
    }
  }

  useEffect(() => {
    document.getElementById(`pal-${selected}`)?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  return (
    <dialog ref={dialogRef} className="palette" aria-label="Command palette" {...({ closedby: 'any' } as Record<string, string>)}>
      <AnimatePresence>
        {open && (
          <motion.div
            className="palette-box"
            initial={{ opacity: 0, scale: 0.96, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97 }}
            transition={{ type: 'spring', stiffness: 420, damping: 32 }}
          >
            <div className="palette-input">
              <Search size={18} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => { setQuery(e.target.value); setSelected(0) }}
                onKeyDown={onKeyDown}
                placeholder="Search actions, demo cases, recent runs…"
                aria-label="Find an action"
                role="combobox"
                aria-expanded="true"
                aria-controls="palette-list"
                aria-activedescendant={filtered.length ? `pal-${selected}` : undefined}
              />
              <span className="kbd">Esc</span>
            </div>
            <div className="palette-list" id="palette-list" role="listbox">
              {filtered.length === 0 && <div className="small-empty" style={{ margin: 8 }}>No matching actions.</div>}
              {filtered.map((command, index) => {
                const header = index === 0 || command.group !== filtered[index - 1].group ? command.group : null
                const isSel = index === selected
                return (
                  <div key={command.id}>
                    {header && <div className="palette-group">{header}</div>}
                    <button
                      id={`pal-${index}`}
                      role="option"
                      aria-selected={isSel}
                      className={cx('palette-item', isSel && 'sel')}
                      onMouseMove={() => setSelected(index)}
                      onClick={() => execute(command)}
                      tabIndex={-1}
                    >
                      {isSel && <motion.span layoutId="pal-bg" className="pi-bg" transition={{ type: 'spring', stiffness: 600, damping: 40 }} />}
                      <span className="pic">{command.icon}</span>
                      <span>{command.label}</span>
                      {command.hint && <span className="hint">{command.hint}</span>}
                    </button>
                  </div>
                )
              })}
            </div>
            <div className="palette-foot">
              <span>
                <span className="kbd">↑</span>
                <span className="kbd">↓</span> navigate
              </span>
              <span>
                <span className="kbd">
                  <CornerDownLeft size={10} />
                </span>{' '}
                run
              </span>
              <span style={{ marginLeft: 'auto' }}>Ctrl K to toggle</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </dialog>
  )
}
