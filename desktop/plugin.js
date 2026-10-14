/**
 * Firecrawl account switcher — status-bar chip + popover with buttons.
 * Backend: ../dashboard/plugin_api.py  (→ /api/plugins/firecrawl-accounts/*)
 * Keys are typed here once, sent to the Hermes backend, stored in its .env,
 * and never shown again (only fc-…1234).
 */
import {
  Button, host, Input, Popover, PopoverContent, PopoverTrigger, queryClient,
  STATUSBAR_AREAS, Tip, useQuery
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'firecrawl-accounts'
const QK = [ID, 'accounts']

const CSS = `
.fca-panel { width: 300px; display: flex; flex-direction: column; gap: 8px; padding: 10px; font-size: 12px; }
.fca-title { font-weight: 600; color: var(--ui-text-primary); display: flex; justify-content: space-between; align-items: center; }
.fca-muted { color: var(--ui-text-tertiary); font-size: 11px; }
.fca-err { color: var(--destructive, var(--ui-text-primary)); font-size: 11px; white-space: pre-wrap; }
.fca-row { display: flex; gap: 4px; align-items: stretch; }
.fca-row > button:first-child { flex: 1; justify-content: space-between; height: auto; padding-top: 6px; padding-bottom: 6px; }
.fca-acc { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; text-align: left; }
.fca-sep { border-top: 1px solid var(--ui-stroke-secondary); margin: 2px 0; }
.fca-form { display: flex; flex-direction: column; gap: 6px; }
.fca-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ui-accent); display: inline-block; }
.fca-chip-dot.off { background: var(--ui-text-quaternary); }
`

function errText(e) {
  const m = (e && (e.message || String(e))) || 'ошибка'
  const j = m.match(/"detail"\s*:\s*"([^"]+)"/)
  return j ? j[1] : m
}

function fmtCredits(a) {
  if (a.check_error) return `⚠ ${a.check_error}`
  if (a.credits == null) return 'кредиты: ?'
  return a.plan_credits ? `кредиты: ${a.credits} / ${a.plan_credits}` : `кредиты: ${a.credits}`
}

function Panel({ ctx, data }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [key, setKey] = useState('')
  const [confirmDel, setConfirmDel] = useState(null)

  const run = async (path, body, okMsg) => {
    setBusy(true); setError('')
    try {
      const res = await ctx.rest(path, { method: 'POST', body: body || {}, timeoutMs: 30000 })
      queryClient.setQueryData(QK, res)
      if (okMsg) host.notify({ kind: 'success', message: okMsg(res) })
      return res
    } catch (e) {
      setError(errText(e))
      return null
    } finally {
      setBusy(false)
    }
  }

  const accounts = (data && data.accounts) || []
  const active = data && data.active

  const rows = accounts.map(a => jsxs('div', { className: 'fca-row', key: a.id, children: [
    jsx(Button, {
      variant: a.id === active ? 'default' : 'outline', size: 'xs', disabled: busy,
      onClick: () => a.id !== active && run('/select', { id: a.id }, () => `Firecrawl: активен «${a.label}»`),
      children: jsxs('span', { className: 'fca-acc', children: [
        jsx('span', { children: (a.id === active ? '● ' : '○ ') + a.label }),
        jsx('span', { style: { opacity: 0.75, fontSize: 10 }, children: `${a.masked} · ${fmtCredits(a)}` })
      ] })
    }),
    jsx(Tip, { label: confirmDel === a.id ? 'Нажмите ещё раз — удалить' : 'Удалить аккаунт', children: jsx(Button, {
      variant: confirmDel === a.id ? 'destructive' : 'ghost', size: 'xs', disabled: busy,
      onClick: () => {
        if (confirmDel !== a.id) { setConfirmDel(a.id); return }
        setConfirmDel(null)
        run('/remove', { id: a.id }, () => `Firecrawl: «${a.label}» удалён`)
      },
      children: '✕'
    }) })
  ] }))

  const form = adding
    ? jsxs('div', { className: 'fca-form', children: [
        jsx(Input, { placeholder: 'Название (напр. Личный, STARTEROK)', value: label, onChange: e => setLabel(e.target.value) }),
        jsx(Input, { type: 'password', autoComplete: 'off', placeholder: 'API-ключ fc-…', value: key, onChange: e => setKey(e.target.value) }),
        jsxs('div', { className: 'fca-row', children: [
          jsx(Button, { size: 'xs', disabled: busy || !label.trim() || !key.trim(), onClick: async () => {
            const res = await run('/add', { label, key }, () => `Firecrawl: «${label}» добавлен`)
            if (res) { setLabel(''); setKey(''); setAdding(false) }
          }, children: busy ? 'Проверяю ключ…' : 'Сохранить' }),
          jsx(Button, { size: 'xs', variant: 'ghost', disabled: busy, onClick: () => { setAdding(false); setKey('') }, children: 'Отмена' })
        ] }),
        jsx('div', { className: 'fca-muted', children: 'Ключ проверяется в Firecrawl и сохраняется в .env на сервере Hermes. В чат он не попадает.' })
      ] })
    : jsx(Button, { size: 'xs', variant: 'secondary', disabled: busy, onClick: () => setAdding(true), children: '+ Добавить аккаунт' })

  return jsxs('div', { className: 'fca-panel', children: [
    jsxs('div', { className: 'fca-title', children: [
      jsx('span', { children: '🔥 Firecrawl — аккаунт' }),
      jsx(Button, { size: 'xs', variant: 'ghost', disabled: busy || !accounts.length,
        onClick: () => run('/refresh'), children: busy ? '…' : '↻ кредиты' })
    ] }),
    accounts.length
      ? jsx('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 }, children: rows })
      : jsx('div', { className: 'fca-muted', children: 'Аккаунтов пока нет — добавьте первый.' }),
    active && jsx(Button, { size: 'xs', variant: 'text', disabled: busy,
      onClick: () => run('/select', { id: null }, () => 'Firecrawl отключён'),
      children: 'Отключить Firecrawl (не использовать ни один)' }),
    !active && accounts.length > 0 && jsx('div', { className: 'fca-muted', children: 'Аккаунт не выбран — агент не сможет пользоваться Firecrawl.' }),
    error && jsx('div', { className: 'fca-err', children: error }),
    jsx('div', { className: 'fca-sep' }),
    form,
    jsx('div', { className: 'fca-muted', children: 'Агент использует только выбранный здесь аккаунт и никогда не переключает его сам.' })
  ] })
}

function Chip({ ctx }) {
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: QK, queryFn: () => ctx.rest('/accounts'), refetchInterval: 30000, retry: 1 })
  const data = q.data
  const active = data && (data.accounts || []).find(a => a.id === data.active)
  const text = q.isError ? 'Firecrawl: нет связи' : active ? `Firecrawl: ${active.label}` : 'Firecrawl: —'

  return jsxs(Popover, { open, onOpenChange: setOpen, children: [
    jsx(PopoverTrigger, { asChild: true, children: jsx(Button, {
      variant: 'ghost', size: 'micro', 'aria-label': 'Переключить аккаунт Firecrawl',
      children: jsxs('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 5 }, children: [
        jsx('span', { className: 'fca-chip-dot' + (active ? '' : ' off') }), text
      ] })
    }) }),
    jsx(PopoverContent, { side: 'top', align: 'end', children:
      q.isError
        ? jsx('div', { className: 'fca-panel', children: jsx('div', { className: 'fca-err', children:
            'Бэкенд плагина недоступен: ' + errText(q.error) + '\nПроверьте, что плагин firecrawl-accounts включён (hermes plugins enable firecrawl-accounts) и gateway перезапущен.' }) })
        : jsx(Panel, { ctx, data })
    })
  ] })
}

export default {
  id: ID,
  name: 'Firecrawl Accounts',
  description: 'Переключатель аккаунтов Firecrawl для агента.',
  register(ctx) {
    const style = document.createElement('style')
    style.textContent = CSS
    document.head.append(style)
    ctx.onDispose(() => style.remove())

    const off = host.onEvent(`plugin.${ID}.changed`, () => queryClient.invalidateQueries({ queryKey: QK }))
    ctx.onDispose(off)

    ctx.register({ id: 'chip', area: STATUSBAR_AREAS.right, order: 20, render: () => jsx(Chip, { ctx }) })
  }
}
