# Instructions for AI assistants working in this repo

1. Before doing anything, read `docs/SYSTEM.md` in full. It describes how the whole Lead Engine works,
   the owner's decisions, the hard rules and the change log.
2. Every change you make (code, SQL, config, behaviour, a live data fix) must be written into
   `docs/SYSTEM.md` in the same commit: update the section it affects and add a line to the change log
   (section 14, newest first, with the commit id). The owner relies on that file after a context wipe.
3. If `docs/SYSTEM.md` and the code disagree, the code is right: correct the doc.
