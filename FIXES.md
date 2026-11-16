# Fixes

Real problems found while building and testing, and how each was fixed.

## The AI

| Problem | Fix |
|---|---|
| The 1B model sent text files (`.txt`, `.csv`) to Installers. | A file-type guardrail: an impossible answer becomes Review. |
| It answered "Installers" for almost every document. | The AI may only choose Receipts, School, Work, Other or Review; rules own the file-type folders. |
| It rambled ("I would categorize this as…"), refused a lease and a gym payment, and invented an answer for an empty file. | Structured JSON output, a system message, and files with no text skip the AI. |
| CSV files never reached the AI ("no readable text"). | The scanner now previews `.csv` files. |
| Ask an agent put everything in Review, then "Miscellaneous," and sent screenshots to "Documents." | Rules place the obvious files first. Qwen only names folders for the leftovers, and vague names like Misc become Other. |
| Ask only read the first 40 characters, so it missed the topic. | It reads the start, middle and end of each file. |
| A dead model could hang the eval for minutes. | After 3 silent replies, that model is skipped and unloaded. |
| Two models in memory made the 8 GB laptop swap, so everything got slow. | Only one model stays loaded. HTML, CSS and code skip the AI on a normal scan. |

## Duplicates and dates

| Problem | Fix |
|---|---|
| The plain-named file was set aside and `notes_final (1).docx` was kept. | Copy-style names always lose. |
| Two plain-named copies: the newer one was kept. | The earliest *created* date wins, then modified, then alphabetical. |
| Duplicates inside subfolders were missed. | The scanner reads every subfolder (except `_safe_to_remove`). Files there stay put unless they're duplicates. |
| The test generator failed on a time inside the daylight-saving jump (2:56 AM doesn't exist). | Dates are checked against the real local clock before stamping. |

## Undo and delete

| Problem | Fix |
|---|---|
| Undo left empty folders behind. | Undo removes only the folders that run created, and only if they're empty. The test now compares folders too. |
| A second Undo of the same run reported every file as "missing." | Finished runs are removed from the log, so Undo says "No runs to undo." |
| A file renamed after Approve couldn't be found by Undo. | Undo looks for it by contents (sha256) in that run's folders. |
| After Delete then Undo, 5 files stayed stuck in `_safe_to_remove`. | Undo restores deleted files first, then reverses the moves. A test checks the exact starting folder comes back. |
| Undo left old log lines and an empty `undo_deleted` folder. | Both are cleaned up when nothing is left to undo. |
| The app ran an old copy of the undo code after it changed. | `app.py` reloads `executor` on every run. |

## The review screen

| Problem | Fix |
|---|---|
| Moving a file sometimes put it back, or moved a different file. | Each move is applied once, and the open menu refreshes after a move. |
| Removing a label hid its files. | Its files go to a visible *No folder* card. |
| Labels that were typed but never approved came back on the next scan. | The Save button is gone; a label is kept only after Approve moves files. |
| Moving a file replaced its original reason with "moved by you." | The scan's reason stays. "Last location" is a separate line. |
| AI guesses looked like part of the file name. | They're blue, beside the name, with their own tab. |
| Duplicates were listed twice. | One Duplicates card and tab. |
| Two Undo buttons, and popups that lingered after Yes. | One Undo with a Yes/No popup. The popup closes first, then "Working…" shows. |
| Messages couldn't be closed. | Every message has a ✕. |
| Eval downloads had odd UTC file names. | One Download button with a local-time name. |