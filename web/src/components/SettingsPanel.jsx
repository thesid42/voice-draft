import { useState } from 'react'

// SettingsPanel — pick which Critic interrupt kinds may fire.
// `data-settings-root` is focus-guard exempt so toggles stay clickable.

const KINDS = [
  {
    key: 'CRITIC_CONTRADICTION',
    label: 'Contradiction',
    hint: 'A new line clashes with something you already said.',
  },
  {
    key: 'CRITIC_VAGUE_CLAIM',
    label: 'Vague claim',
    hint: 'A number or comparison with no anchor.',
  },
  {
    key: 'CRITIC_UNDEFINED_TERM',
    label: 'Undefined term',
    hint: 'A term doing real work that was never explained.',
  },
  {
    key: 'CRITIC_LOST_THREAD',
    label: 'Lost thread',
    hint: 'The last few lines drifted off the point of the draft.',
  },
  {
    key: 'CRITIC_IMPLAUSIBLE_CLAIM',
    label: 'Implausible claim',
    hint: 'A literal fact that cannot be true — “a truck can fly.”',
  },
]

function isOn(config, key) {
  const v = config?.[key]
  return v == null ? true : Boolean(v)
}

export default function SettingsPanel({ config, onSetConfig }) {
  const [open, setOpen] = useState(false)

  return (
    <div
      data-settings-root
      className="fixed z-40 flex flex-col-reverse items-end gap-2"
      style={{ right: 16, bottom: 72 }}
    >
      <button
        type="button"
        aria-label="Interrupt settings"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        title="Interrupt settings"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.4rem',
          fontFamily: 'var(--font-sans)',
          fontSize: '0.72rem',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          color: 'var(--ink-dim)',
          background: open ? 'var(--paper-raised)' : 'var(--paper-raised)',
          border: '1px solid var(--paper-line)',
          borderRadius: '9999px',
          padding: '0.35rem 0.7rem 0.35rem 0.5rem',
          cursor: 'pointer',
          boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
        }}
      >
        <GearIcon />
        Settings
      </button>

      {open && (
        <div
          style={{
            width: 'min(20rem, calc(100vw - 2rem))',
            background: 'var(--paper-raised)',
            border: '1px solid var(--paper-line)',
            borderRadius: '12px',
            padding: '1rem 1.05rem 0.85rem',
            boxShadow: '0 18px 48px rgba(0,0,0,0.45)',
          }}
        >
          <div className="mb-1" style={{ fontFamily: 'var(--font-sans)', fontSize: '0.68rem', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--amber)' }}>
            Interrupt on
          </div>
          <p
            style={{
              fontFamily: 'var(--font-sans)',
              fontSize: '0.75rem',
              color: 'var(--ink-faint)',
              margin: '0 0 0.85rem',
              lineHeight: 1.45,
            }}
          >
            The Critic only speaks for kinds you leave on. Answer out loud, or say Draft, ignore that.
          </p>

          <ul className="m-0 flex list-none flex-col gap-2.5 p-0">
            {KINDS.map((item) => {
              const on = isOn(config, item.key)
              return (
                <li key={item.key}>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '0.65rem',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) => onSetConfig(item.key, e.target.checked ? 1 : 0)}
                      style={{ marginTop: '0.2rem', accentColor: 'var(--amber)' }}
                    />
                    <span>
                      <span
                        style={{
                          display: 'block',
                          fontFamily: 'var(--font-sans)',
                          fontSize: '0.85rem',
                          color: 'var(--ink)',
                        }}
                      >
                        {item.label}
                      </span>
                      <span
                        style={{
                          display: 'block',
                          fontFamily: 'var(--font-sans)',
                          fontSize: '0.72rem',
                          color: 'var(--ink-faint)',
                          lineHeight: 1.4,
                          marginTop: '0.1rem',
                        }}
                      >
                        {item.hint}
                      </span>
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}

function GearIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M19.4 13a7.6 7.6 0 0 0 .05-2l2.05-1.55-2-3.46-2.45.6a7.7 7.7 0 0 0-1.73-1L14.9 3h-5.8L8.68 5.59a7.7 7.7 0 0 0-1.73 1l-2.45-.6-2 3.46L4.55 11a7.6 7.6 0 0 0 0 2l-2.05 1.55 2 3.46 2.45-.6a7.7 7.7 0 0 0 1.73 1L9.1 21h5.8l.42-2.59a7.7 7.7 0 0 0 1.73-1l2.45.6 2-3.46L19.4 13Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}
