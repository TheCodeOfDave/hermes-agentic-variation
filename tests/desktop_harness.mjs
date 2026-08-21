import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../desktop/plugin.js', import.meta.url), 'utf8')
const navigations = []
const notifications = []
const registrations = []
const storageReads = []
const storageWrites = []
const stored = new Map()

const host = {
  navigate: path => navigations.push(path),
  notify: value => notifications.push(value)
}

const context = vm.createContext({ console })

function synthetic(names, values) {
  return new vm.SyntheticModule(
    names,
    function () {
      for (const name of names) this.setExport(name, values[name])
    },
    { context }
  )
}

const jsx = (type, props = {}) => ({ type, props })
const jsxs = jsx
const sdk = synthetic(
  ['Button', 'Input', 'PALETTE_AREA', 'ROUTES_AREA', 'SIDEBAR_NAV_AREA', 'host'],
  {
    Button: props => jsx('button', props),
    Input: props => jsx('input', props),
    PALETTE_AREA: 'palette',
    ROUTES_AREA: 'routes',
    SIDEBAR_NAV_AREA: 'sidebar',
    host
  }
)
const react = synthetic(['useState'], {
  useState: initial => {
    let value = typeof initial === 'function' ? initial() : initial
    return [value, next => { value = typeof next === 'function' ? next(value) : next }]
  }
})
const jsxRuntime = synthetic(['jsx', 'jsxs'], { jsx, jsxs })

const module = new vm.SourceTextModule(source, { context })
await module.link(specifier => {
  if (specifier === '@hermes/plugin-sdk') return sdk
  if (specifier === 'react') return react
  if (specifier === 'react/jsx-runtime') return jsxRuntime
  throw new Error(`unsupported import: ${specifier}`)
})
await module.evaluate()

const plugin = module.namespace.default
assert.equal(plugin.id, 'agentic-variation')
assert.equal(plugin.defaultEnabled, false)

const pluginContext = {
  storage: {
    get(key, fallback) {
      storageReads.push(key)
      return stored.has(key) ? stored.get(key) : fallback
    },
    set(key, value) {
      storageWrites.push([key, value])
      stored.set(key, value)
    }
  },
  registerMany(items) {
    registrations.push(...items)
  }
}
plugin.register(pluginContext)

assert.deepEqual(registrations.map(item => item.area).sort(), ['palette', 'routes', 'sidebar'])
const route = registrations.find(item => item.area === 'routes')
const nav = registrations.find(item => item.area === 'sidebar')
const palette = registrations.find(item => item.area === 'palette')
assert.equal(route.data.path, '/agentic-variation')
assert.equal(nav.data.label, 'Agentic Variation')
palette.data.run()
assert.deepEqual(navigations, ['/agentic-variation'])

function render(node) {
  if (node == null || typeof node !== 'object') return
  if (Array.isArray(node)) {
    for (const child of node) render(child)
    return
  }
  if (typeof node.type === 'function') {
    render(node.type(node.props || {}))
    return
  }
  render(node.props?.children)
}
render(route.render())

for (const key of [
  'defaultMaxSteps',
  'defaultMaxWallSeconds',
  'defaultMaxCostUsd',
  'defaultNoProgressLimit',
  'networkPolicy',
  'allowedToolsets',
  'evaluatorId'
]) {
  assert.ok(storageReads.includes(key), `configuration did not read ${key}`)
}
assert.equal(storageWrites.length, 0)
assert.equal(notifications.length, 0)
console.log('desktop_harness=PASS registrations=3 options=7 defaultEnabled=false')
