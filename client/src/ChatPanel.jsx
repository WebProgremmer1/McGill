import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { isOwnMessage, oldestFirst } from './data/chat.js'
import { firstName } from './data/contacts.js'
import Icon from './Icon.jsx'
import './ChatPanel.css'

function messageTime(value) {
  const date = new Date(value)
  const clock = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (date.toDateString() === new Date().toDateString()) return clock
  return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${clock}`
}

export default function ChatPanel({ className, messages, viewerRole, accountId, otherName, fieldName, canSend, repliesReady, onSend, onClear, headingId, headingRef, draftValue, onDraftChange }) {
  const id = useId()
  const log = useRef(null)
  const field = useRef(null)
  const clearButton = useRef(null)
  const keepButton = useRef(null)
  const opened = useRef(false)
  const pinned = useRef(true)
  const scrollAfterSend = useRef(false)
  const sendingNow = useRef(false)
  const returnToClear = useRef(false)
  const [localDraft, setLocalDraft] = useState('')
  const draft = draftValue ?? localDraft
  const setDraft = onDraftChange ?? setLocalDraft
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [clearError, setClearError] = useState('')
  const thread = useMemo(() => oldestFirst(messages), [messages])
  const loaded = messages !== undefined
  const lastId = thread.at(-1)?.id
  const showComposer = canSend && (viewerRole === 'patient' || repliesReady === true)
  const showConfirm = confirming && thread.length > 0

  // New rows are added below, so someone reading older messages keeps their place.
  useLayoutEffect(() => {
    const element = log.current
    if (!element || !loaded) return
    if (!opened.current || pinned.current || scrollAfterSend.current) {
      opened.current = true
      pinned.current = true
      scrollAfterSend.current = false
      element.scrollTop = element.scrollHeight
    }
  }, [lastId, loaded, thread.length])

  // Rotating or resizing keeps the latest message in view unless someone scrolled up.
  useEffect(() => {
    const element = log.current
    if (!element || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(() => {
      if (pinned.current) element.scrollTop = element.scrollHeight
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (showConfirm) keepButton.current?.focus()
    else if (returnToClear.current) {
      returnToClear.current = false
      clearButton.current?.focus()
    }
  }, [showConfirm])

  function trackScroll(event) {
    const element = event.currentTarget
    pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 32
  }

  async function submit(event) {
    event.preventDefault()
    if (sendingNow.current) return
    const text = draft.trim()
    if (!text) {
      setSendError('Write a message first.')
      field.current?.focus()
      return
    }
    sendingNow.current = true
    scrollAfterSend.current = true
    setSending(true)
    setSendError('')
    try {
      await onSend(text)
      setDraft('')
      field.current?.focus()
    } catch {
      scrollAfterSend.current = false
      setSendError('Your message didn’t send. Your draft is saved, so select Send to try again.')
    } finally {
      sendingNow.current = false
      setSending(false)
    }
  }

  function keepMessages() {
    returnToClear.current = true
    setClearError('')
    setConfirming(false)
  }

  async function clearChat() {
    if (clearing) return
    setClearing(true)
    setClearError('')
    try {
      await onClear()
      setConfirming(false)
      field.current?.focus()
    } catch {
      setClearError('The chat wasn’t cleared. Try again.')
    } finally {
      setClearing(false)
    }
  }

  return (
    <section className={`${className} chat-panel`} aria-labelledby={headingId ?? `${id}-title`}>
      <div className="chat-heading">
        <h2 id={headingId ?? `${id}-title`} ref={headingRef} tabIndex={headingRef ? -1 : undefined} className="icon-heading"><Icon name="message" />Messages</h2>
        {onClear && thread.length > 0 && !showConfirm && repliesReady === true && (
          <button ref={clearButton} type="button" className="chat-clear" onClick={() => setConfirming(true)}>Clear demo chat</button>
        )}
      </div>
      {showConfirm && (
        <div className="chat-confirm" role="group" aria-labelledby={`${id}-confirm`}>
          <p id={`${id}-confirm`}>Clear this chat for both people? Walks, alerts, reminders, and Calendar events stay.</p>
          <div className="chat-confirm-actions">
            <button ref={keepButton} type="button" className="button secondary" onClick={keepMessages}>Keep messages</button>
            <button type="button" className="button chat-confirm-clear" aria-disabled={clearing} onClick={clearChat}>{clearing ? 'Clearing…' : 'Clear chat'}</button>
          </div>
          {clearError && <p className="chat-error" role="alert">{clearError}</p>}
        </div>
      )}
      <div ref={log} className="chat-log" role="log" aria-live="off" aria-label="Conversation" tabIndex={0} onScroll={trackScroll}>
        {!loaded && <p className="chat-empty">Loading…</p>}
        {messages === null && <p className="chat-empty">Messages aren’t available on this server yet.</p>}
        {loaded && messages !== null && thread.length === 0 && <p className="chat-empty">No messages yet</p>}
        {thread.length > 0 && (
          <ol className="chat-thread">
            {thread.map(item => {
              const own = isOwnMessage(item, viewerRole, accountId)
              return (
                <li key={item.id} className={own ? 'chat-row is-outgoing' : 'chat-row is-incoming'} data-message-id={item.id} data-direction={own ? 'outgoing' : 'incoming'}>
                  <div className="chat-bubble">
                    <p className="chat-sender">{own ? 'You' : firstName(item.sender) || otherName}</p>
                    <p className="chat-body">{item.body}</p>
                    <time dateTime={item.created_at}>{messageTime(item.created_at)}</time>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>
      {showComposer && (
        <form className="chat-composer" onSubmit={submit}>
          <label htmlFor={`${id}-field`}>Message to {fieldName}</label>
          <div className="chat-compose-row">
            <textarea id={`${id}-field`} ref={field} className="chat-input" rows="2" maxLength="280" value={draft}
              aria-describedby={sendError ? `${id}-error` : undefined}
              onChange={event => { setDraft(event.target.value); setSendError('') }} />
            <button type="submit" className="button primary chat-send" aria-disabled={sending}><Icon name="next" />{sending ? 'Sending…' : 'Send'}</button>
          </div>
          {sendError && <p id={`${id}-error`} className="chat-error" role="alert">{sendError}</p>}
        </form>
      )}
      {canSend && viewerRole === 'caregiver' && repliesReady === false && (
        <p className="chat-note" role="status">Replies will turn on after FastAPI restarts with this update.</p>
      )}
    </section>
  )
}
