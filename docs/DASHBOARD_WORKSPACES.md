# Dashboard workspaces

This is a presentation-only update based on the execution safety audit merge
`e91059b`. It does not change broker adapters, strategy rules, risk limits,
scan intervals, account selection, or live activation requirements.

## Navigation

| Workspace | Existing features |
| --- | --- |
| Overview | Account metrics, chart, primary signal, manual approval, decision trace, activity |
| Markets | Accessible markets, bias board, candle intelligence |
| Execution | Positions, demo runner, exit management, guarded live runner |
| Research | Strategy scorecards, public evidence, advisor, learning, edge validation |
| Performance | Editable targets, performance metrics, journal |
| Settings | Broker status, aggression profile |

`workspace.js` moves existing elements rather than copying them. IDs, event
handlers, form state, polling, and endpoint contracts remain intact. Hidden
workspaces do not stop background updates. Browser history and old section
bookmarks are supported. Navigation makes no trading API calls.

The layout uses a neutral charcoal palette, restrained green accents, larger
spacing, responsive grids, visible keyboard focus, and reduced-motion support.
The emergency control stays accessible in the desktop header and on small
phones. Its existing backend behavior is unchanged; this is not a certification
of emergency-stop behavior on a live MT5 account.

## Verification

Backend regression suite:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Browser smoke test (Node.js and Playwright required):

```sh
npm install --no-save --package-lock=false playwright@1.51.1
npx playwright install chromium
node tests/dashboard_smoke.cjs
```

The smoke test starts and closes its own static server. All API requests are
intercepted, so it cannot place trades. It checks navigation, preserved element
IDs, unique IDs, browser history, old bookmarks, five viewport widths, control
overflow, JavaScript errors, and existing runner/scan/goal/stop endpoint wiring.
Screenshots are written to the operating system's temporary directory.

This does not install the update on the Windows laptop or verify real broker
execution. The newly mentioned design-reference video was not available in this
turn; the redesign addresses the existing dashboard's hierarchy and crowding.
