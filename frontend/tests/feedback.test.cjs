const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    })
    module._compile(outputText, filename)
  }
}
const { FeedbackView, FeedbackBar } = require('../src/components/FeedbackBar.tsx')
const side = require('../src/lib/sideChat.ts')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;:?])/g, '$1').trim()
const view = (props = {}) => renderToStaticMarkup(React.createElement(FeedbackView, { state: 'ready', choice: null, error: null, note: '', onNote() {}, onChoose() {}, admin: false, ...props }))

test('before a verdict the control asks one plain question with Yes, Partly and No', () => {
  const html = view()
  assert.match(text(html), /Was this answer useful\? Yes Partly No/)
  assert.equal((html.match(/class="fb-btn/g) || []).length, 3)
  assert.match(html, /role="group" aria-labelledby="fb-label"/)
  assert.match(text(html), /Sent to the knowledge base as feedback on this answer, once\. It does not change the brief\./)
})

test('an administrator is told the verdict goes to Synapt; everyone else never sees the vendor name', () => {
  assert.match(text(view({ admin: true })), /Sent to Synapt as feedback on this query, once\./)
  assert.doesNotMatch(view({ admin: false }), /Synapt/)
  assert.match(side.feedbackThanks('partly', true), /^Thanks\. “Partly” was sent to Synapt\.$/)
  assert.equal(side.feedbackThanks('helpful', false), 'Thanks. “Yes” was sent to the knowledge base.')
  assert.equal(side.feedbackThanks('not_helpful', false), 'Thanks. “No” was sent to the knowledge base.')
  assert.doesNotMatch(side.feedbackThanks('helpful', false), /Synapt/)
})

test('once sent, the buttons are replaced by a thank-you and cannot be pressed again', () => {
  const html = view({ state: 'sent', choice: 'helpful' })
  assert.match(text(html), /Thanks\. “Yes” was sent to the knowledge base\./)
  assert.doesNotMatch(html, /fb-btn/)
  assert.match(html, /role="status"/)
})

test('while sending, every button is disabled and the chosen one shows it is working', () => {
  const html = view({ state: 'sending', choice: 'partly' })
  assert.equal((html.match(/disabled=""/g) || []).length, 3)
  assert.match(html, /class="fb-btn on"[^>]*disabled=""><svg[^>]*class="[^"]*spin/)
})

test('a failed send shows its reason where the person is looking and leaves the buttons usable', () => {
  const html = view({ error: 'Synapt could not take the feedback right now. Try again in a moment.' })
  assert.match(html, /role="alert"[^>]*>Synapt could not take the feedback right now\./)
  assert.doesNotMatch(html, /disabled=""/)
})

test('the optional note is masked before it leaves, limited in length and counts down', () => {
  const html = view({ note: 'x'.repeat(40) })
  assert.match(html, /maxLength="300"/)
  assert.match(text(html), /Personal details are masked before anything is sent\. 260 characters left\./)
  assert.match(html, /<details class="fb-note"><summary>Add a note \(optional\)<\/summary>/)
})

test('the three choices and the error wording are fixed in one place', () => {
  assert.deepEqual(side.FEEDBACK_CHOICES.map((c) => [c.key, c.label]), [['helpful', 'Yes'], ['partly', 'Partly'], ['not_helpful', 'No']])
  assert.equal(side.FEEDBACK_NOTE_MAX, 300)
  const err = (status, message = '') => Object.assign(new Error(message), { status })
  assert.match(side.feedbackErrorMessage(err(401)), /sign in again/)
  assert.match(side.feedbackErrorMessage(err(404)), /no knowledge-base answer here to rate/)
  assert.match(side.feedbackErrorMessage(err(422)), /Check the note/)
  assert.equal(side.feedbackErrorMessage(err(502, 'Synapt could not take the feedback right now. Try again in a moment.')), 'Synapt could not take the feedback right now. Try again in a moment.')
  assert.match(side.feedbackErrorMessage(err(500)), /Try again in a moment/)
})

test('nothing is drawn until the earlier verdicts are known, so a rated answer never flashes the buttons', () => {
  assert.equal(renderToStaticMarkup(React.createElement(FeedbackBar, { runId: 'r1', target: 'investigation', admin: false })), '')
})

test('the control sits under the investigation’s own answer and under a saved side-chat answer, and never takes a query ID', () => {
  const panel = fs.readFileSync(require.resolve('../src/components/QueryAgentPanel.tsx'), 'utf8')
  assert.match(panel, /<FeedbackBar runId=\{runId\} target="investigation" admin=\{admin\} \/>/)
  const chat = fs.readFileSync(require.resolve('../src/components/SideChat.tsx'), 'utf8')
  assert.match(chat, /<FeedbackBar runId=\{runId\} target=\{`side:\$\{answer\.id\}`\} admin=\{admin\} \/>/)
  assert.match(chat, /answer\.id !== null && answer\.parts\.some\(\(p\) => p\.source === 'synapt' && p\.status === 'ok'\)/)
  const bar = fs.readFileSync(require.resolve('../src/components/FeedbackBar.tsx'), 'utf8')
  assert.doesNotMatch(bar, /query_id|queryId/)
  assert.match(bar, /status === 409/)
})
