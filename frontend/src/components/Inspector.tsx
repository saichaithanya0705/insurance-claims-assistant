import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

// Native modal dialog provides inert background, focus containment and Escape.
export function Inspector({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current
    dialog?.showModal()
    return () => { dialog?.close(); previous?.focus({ preventScroll: true }) }
  }, [])
  return createPortal(<dialog ref={ref} className="inspector" aria-labelledby="inspector-title" onCancel={e => { e.preventDefault(); onClose() }}>
    <div className="inspector-head"><h2 id="inspector-title">{title}</h2><button autoFocus className="btn" onClick={onClose}>Back to workspace</button></div>
    <div className="inspector-body">{children}</div>
  </dialog>, document.body)
}
