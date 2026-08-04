# Frontend Agent Notes

Read the repository-root `AGENTS.md` first.

This is a single-page React control center with no router or global state
library. `useEventStream.ts` is the WebSocket-backed state seam. Preserve
non-color status cues, 16px minimum body copy, and second-monitor readability.

The public OBS overlay is deliberately separate from the React bundle. Keep
its JS and CSS external so the CSP can reject inline code/style, and render
received content only with `textContent`.

Commands from this directory:

```powershell
npm install
npm run dev
npm run lint
npm run build
```
