import {
  Button,
  Input,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  host
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'agentic-variation'
const ROUTE = '/agentic-variation'

const DEFAULTS = Object.freeze({
  defaultMaxSteps: 5,
  defaultMaxWallSeconds: 600,
  defaultMaxCostUsd: 1,
  defaultNoProgressLimit: 2,
  networkPolicy: 'disabled',
  allowedToolsets: 'file,terminal',
  evaluatorId: 'fixture.score.v1'
})

function useStoredOption(storage, key) {
  const [value, setValue] = useState(() => storage.get(key, DEFAULTS[key]))
  const update = next => {
    setValue(next)
    storage.set(key, next)
  }
  return [value, update]
}

function Field({ label, description, children }) {
  return jsxs('label', {
    className: 'grid gap-1.5 rounded-md border border-(--ui-stroke-secondary) p-3',
    children: [
      jsx('span', { className: 'text-sm font-medium', children: label }),
      jsx('span', {
        className: 'text-xs text-(--ui-text-tertiary)',
        children: description
      }),
      children
    ]
  })
}

function NumberOption({ storage, storageKey, label, description, min, step = 1 }) {
  const [value, setValue] = useStoredOption(storage, storageKey)
  return jsx(Field, {
    label,
    description,
    children: jsx(Input, {
      type: 'number',
      min,
      step,
      value: String(value),
      onChange: event => {
        const parsed = Number(event.target.value)
        if (Number.isFinite(parsed) && parsed >= min) setValue(parsed)
      }
    })
  })
}

function TextOption({ storage, storageKey, label, description }) {
  const [value, setValue] = useStoredOption(storage, storageKey)
  return jsx(Field, {
    label,
    description,
    children: jsx(Input, {
      value,
      onChange: event => setValue(event.target.value)
    })
  })
}

function ConfigurationPage({ storage }) {
  const [networkPolicy, setNetworkPolicy] = useStoredOption(storage, 'networkPolicy')
  const [resetVersion, setResetVersion] = useState(0)

  const reset = () => {
    for (const [key, value] of Object.entries(DEFAULTS)) storage.set(key, value)
    setResetVersion(version => version + 1)
    host.notify({ kind: 'success', message: 'Agentic Variation defaults reset.' })
  }

  return jsxs('div', {
    key: resetVersion,
    className: 'flex h-full flex-col overflow-auto p-5',
    children: [
      jsxs('div', {
        className: 'mb-5 grid gap-1',
        children: [
          jsx('h1', { className: 'text-lg font-semibold', children: 'Agentic Variation' }),
          jsx('p', {
            className: 'max-w-3xl text-sm text-(--ui-text-tertiary)',
            children:
              'Configure inert planning defaults. Phase 4 execution is backend-owned in config.yaml and cannot be enabled from Desktop. The child remains todo-only; one bounded patch may run only in a digest-pinned Docker sandbox with no network, read-only root, dropped capabilities, resource ceilings, and no commit, push, credentials, deployment, cleanup, or deletion.'
          })
        ]
      }),
      jsxs('div', {
        className: 'grid max-w-3xl gap-3',
        children: [
          jsx(NumberOption, {
            storage,
            storageKey: 'defaultMaxSteps',
            label: 'Maximum steps',
            description: 'Default candidate-step ceiling for a future approved RunSpec.',
            min: 1
          }),
          jsx(NumberOption, {
            storage,
            storageKey: 'defaultMaxWallSeconds',
            label: 'Maximum wall time (seconds)',
            description: 'Default wall-clock budget for a future approved run.',
            min: 1
          }),
          jsx(NumberOption, {
            storage,
            storageKey: 'defaultMaxCostUsd',
            label: 'Maximum model cost (USD)',
            description: 'Default cost ceiling. Zero means no model budget.',
            min: 0,
            step: 0.01
          }),
          jsx(NumberOption, {
            storage,
            storageKey: 'defaultNoProgressLimit',
            label: 'No-progress limit',
            description: 'Consecutive non-improving attempts before supervision is required.',
            min: 1
          }),
          jsx(Field, {
            label: 'Network policy',
            description: 'Phase 0 remains offline regardless of this future-run default.',
            children: jsxs('select', {
              className:
                'h-8 rounded-md border border-(--ui-stroke-secondary) bg-transparent px-2 text-sm',
              value: networkPolicy,
              onChange: event => setNetworkPolicy(event.target.value),
              children: [
                jsx('option', { value: 'disabled', children: 'Disabled' }),
                jsx('option', { value: 'allowlist', children: 'Allowlist only' })
              ]
            })
          }),
          jsx(TextOption, {
            storage,
            storageKey: 'allowedToolsets',
            label: 'Allowed toolsets',
            description: 'Comma-separated planning default; child authority can only narrow the parent.'
          }),
          jsx(TextOption, {
            storage,
            storageKey: 'evaluatorId',
            label: 'Evaluator ID',
            description: 'Immutable evaluator adapter identifier for a future RunSpec.'
          }),
          jsx('div', {
            className: 'pt-1',
            children: jsx(Button, {
              variant: 'secondary',
              onClick: reset,
              children: 'Reset defaults'
            })
          })
        ]
      })
    ]
  })
}

export default {
  id: ID,
  name: 'Agentic Variation',
  description: 'Configure the AVO-inspired Hermes experiment controller.',
  defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      {
        id: 'configuration-page',
        area: ROUTES_AREA,
        data: { path: ROUTE },
        render: () => jsx(ConfigurationPage, { storage: ctx.storage })
      },
      {
        id: 'configuration-nav',
        area: SIDEBAR_NAV_AREA,
        data: { path: ROUTE, label: 'Agentic Variation', codicon: 'settings-gear' }
      },
      {
        id: 'open-configuration',
        area: PALETTE_AREA,
        data: {
          id: 'agentic-variation.open',
          label: 'Agentic Variation: configure',
          keywords: ['agentic', 'variation', 'avo', 'experiment', 'settings'],
          run: () => host.navigate(ROUTE)
        }
      }
    ])
  }
}
