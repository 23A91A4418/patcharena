# 3-Minute Demo Script

## Setup (before presenting)
- [ ] Backend running: `uvicorn backend.main:app --reload`
- [ ] Browser open to `http://localhost:8000`
- [ ] Demo repo issue ready: `https://github.com/<you>/patcharena-demo/issues/1`
- [ ] Golden run replay ready as backup: `runs/golden/`

---

## Script

### (0:00–0:20) Problem

> "AI writes patches nobody trusts. We've all pasted a diff from GPT into production and held our breath. PatchArena makes patches compete and **prove** they work."

### (0:20–0:45) Paste and Start

> "I'll paste the issue URL — a pagination off-by-one bug."

*Type repo URL + issue number → click Start*

> "Three Celesto computers just spun up in parallel. Each runs a different fix strategy in total isolation — untrusted code never touches our server."

*Point to spinning status chips*

### (0:45–1:20) Narrate Live Logs

> "That one is still cloning the repo. This one just ran the baseline test — it fails, which means the bug is reproducible."

> "Now the agents are writing patches. They each use a different approach: minimal, root-cause, and test-first."

*Point to the scrolling terminal logs for each column*

### (1:20–1:50) One Failure

> "That candidate — root-cause — just failed a gate."

*Red chip appears. Point to it.*

> "We run the tests ourselves and read the exit code. The agent doesn't get to claim it works."

*Hover over the red chip to show gate failure reason*

### (1:50–2:10) Leaderboard

> "Here's the leaderboard. Deterministic scoring: test result, diff size, preview health, browser check."

*Leaderboard fades in with score bars*

> "Minimal wins — smallest diff, cleanest fix."

### (2:10–2:25) Live Preview

> "Click Open Preview."

*Opens the published Celesto URL with the fixed pagination*

> "Real app, running in the sandbox. Bug is gone."

*Show screenshot verdict chip*

### (2:25–2:40) PR

> "One click: Open PR."

*Click PR button, navigate to GitHub*

> "Real PR, with test evidence, screenshot, and the full leaderboard attached."

### (2:40–3:00) Close

> "If the network dies, we hit Replay — a real recorded run. State lives in the sandboxes, not our server. Every candidate is replayable."

> "PatchArena: AI we can actually trust because we made it prove it."

---

## Fallback (if live run fails)
Click Replay toggle → Enter `golden` → Watch the recorded run play at 4x speed.
Tell judges: *"This is a recording of a real execution. The PR and preview link are still live."*
