// Small pointer effects for the Golden Hour theme. One set of document listeners,
// so they work for buttons React adds later. Skipped when "reduce motion" is on.
const INTERACTIVE = '.primary, .secondary, .get-help, .signup-submit, .demo-role-card'
const TILT = '.demo-role-card'
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function onMove(event) {
  if (reduceMotion.matches) return
  const picker = document.querySelector('.role-picker')
  if (picker) {
    picker.style.setProperty('--px', `${event.clientX}px`)
    picker.style.setProperty('--py', `${event.clientY}px`)
  }
  const el = event.target.closest?.(INTERACTIVE)
  if (!el) return
  const box = el.getBoundingClientRect()
  const x = (event.clientX - box.left) / box.width
  const y = (event.clientY - box.top) / box.height
  el.style.setProperty('--mx', `${x * 100}%`)
  el.style.setProperty('--my', `${y * 100}%`)
  if (el.matches(TILT)) {
    el.style.setProperty('--ry', `${(x - .5) * 6}deg`)
    el.style.setProperty('--rx', `${(.5 - y) * 6}deg`)
  }
}

function onLeave(event) {
  const el = event.target.closest?.(TILT)
  if (el && !el.contains(event.relatedTarget)) {
    el.style.removeProperty('--rx')
    el.style.removeProperty('--ry')
  }
}

function onDown(event) {
  if (reduceMotion.matches) return
  const el = event.target.closest?.(INTERACTIVE)
  if (!el || el.getAttribute('aria-disabled') === 'true') return
  const box = el.getBoundingClientRect()
  const ring = document.createElement('span')
  ring.className = 'gh-ripple'
  ring.setAttribute('aria-hidden', 'true')
  ring.style.left = `${event.clientX - box.left}px`
  ring.style.top = `${event.clientY - box.top}px`
  ring.addEventListener('animationend', () => ring.remove())
  el.append(ring)
}

document.addEventListener('pointermove', onMove, { passive: true })
document.addEventListener('pointerout', onLeave, { passive: true })
document.addEventListener('pointerdown', onDown, { passive: true })
