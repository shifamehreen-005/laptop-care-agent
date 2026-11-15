# What went wrong

Problems from building and using the review screen, and what changed. Nothing here moves a file until Approve.

**1. Saving a move put the file back in the old folder.**
The Move to menu still held the old folder. The next rerun sent that old value again and undid the move.
Fix: after a move the menu is a new control, and a repeat of the old folder is ignored.

**2. Moving one file sent another file to No folder.**
The preview stayed open on a file such as doc1.docx. Its menu still said "Leave where it is," and that choice means No folder. The next rerun applied it, so doc1 jumped even though a different file was the one you moved.
Fix: the open menu is refreshed after each move, and a drag does not also apply the menu.

**3. The first file put in No folder could not be moved anywhere else.**
The menu treated the next folder you picked as an old value and snapped back to No folder. A drop onto No folder could also be replayed and pull the file back.
Fix: a file in No folder accepts the next folder you pick, and each drop is applied once.

**4. Moving a file replaced Other notes with "moved by you."**
The original reason, including the duplicate explanation, was overwritten.
Fix: the note from the scan stays. Last location is a separate line, placed just above Move to. The old gap under Other notes had pushed that line too far from the menu.

**5. Removing a folder hid its files.**
Work's files left the screen, and the chip count no longer matched the number of scanned files. Files already sitting in the right folder had also been left out of the plan.
Fix: those files go to the No folder card. Empty folders stay visible. A file already in the right folder is shown, and Approve does not move it.

**6. Labels that were saved but not approved came back on the next scan.**
Save wrote them into the label file. Names such as hello showed up again after a new scan.
Fix: the Save button is gone. A label you make is stored only after Approve actually moves files in the test folder. Approving any other folder moves nothing and does not keep the label.

**7. Reset did not clear the similar-name warning.**
"Receipts is already a label. This one was still created." stayed on the screen after Reset.
Fix: Reset clears that warning along with the rest of this scan's edits.

**8. Reset labels and Reset were easy to mix up.**
Reset labels rewrote the saved folder names immediately. Reset only puts this scan back.
Fix: Reset labels was removed. Reset stays beside Undo.

**9. The duplicate list under the cards repeated the Duplicates card.**
The same copies appeared again as long buttons ("copy of …").
Fix: that list is gone. Duplicates stay as a card and a nav tab. Large files and No folder each have a tab and a card, instead of a list under the grid.

**10. An AI guess was hard to tell from the file name.**
The words sat in the same text as the name.
Fix: the guess is blue, beside the name. The AI guesses tab shows only those files, grouped by the folder they landed in.

**11. The create-label box kept the name, and the form hint got in the way.**
The name stayed after Enter, and "Press Enter to submit form" showed even though Enter already worked.
Fix: one Enter button, an empty box, no hint. The Create label button highlights while the box is open and closes after the label is added.

**12. The chip highlight and the preview spacing looked off.**
The selected chip's outline did not sit on the pill. Move to was tight against Other notes, then later the last-location line had too much space above it. Reload was a boxed button.
Fix: a border on the chip, a plain reload arrow, and last location directly above Move to.

**13. The done screen's Undo and the health numbers were unclear.**
Undo did not return to the start. Battery showed nothing while it loaded. Used and free had no plain meaning.
Fix: Undo on that screen always shows, and after it runs you return to the start. Battery says Loading, then the percent or No battery. Disk says space already filled, and space you can still use.

**14. Some failures looked like the app had crashed.**
Stopping the old server reports exit code 4294967295. "Port 8501 is not available" means the previous Python process is still listening. A connection reset in the log is a browser tab that closed. On this OneDrive folder, saving app.py often does not reload the screen by itself.
Fix: none of those are a crash in the tidy. The detail, when it is a real error, goes to app.log, and the screen shows one short sentence. Restarting means stopping the process that is actually listening, then starting again.

**15. "Those files couldn't be deleted" and "couldn't be put back."**
Streamlit reloaded app.py but kept an old copy of executor.py in memory, so the new delete and undo code was missing.
Fix: app.py reloads executor at the start of every run.

**16. After Delete then Undo, a scan showed 53 files instead of 58.**
Undo moved files back before putting deleted files back. Five duplicates ended up stuck in `_safe_to_remove`, which the scan skips. Restore then showed up later by surprise.
Fix: Undo puts deleted files back first, then reverses the moves. The test folder was repaired once by hand (back to 58 files and `my Notes`). A test now checks Delete then Undo gives back the exact starting folder.

**17. Undo and Delete were confusing.**
There were two Undo buttons, error popups covered the screen, and the Undo under the green bar looked like a bar.
Fix: one Undo under the bar with a Yes/No popup, and one Delete or Restore button under Delete files.

**18. Undo left notes and folders behind.**
Old lines stayed in `undo.log`, and an empty `undo_deleted` folder stayed after a restore.
Fix: finished runs are removed from the log, an empty log is deleted, and the empty copies folder is removed.

**19. Messages could not be closed.**
Bars like "Undone. Files are back." stayed until the next action.
Fix: every message bar has a ✕.

**20. A see-through copy of the review screen showed on the done screen.**
Streamlit fades the last screen out while the new one loads, and the battery check takes a few seconds.
Fix: on the start and done screens the faded copy is hidden, so you only see Battery saying Loading. The review screen keeps it, so its cards don't flicker on every click.

**21. A long warning kept showing in the terminal.**
"The widget with key move_… was created with a default value but also had its value set via the Session State API." The Move to menu set its folder twice, once directly and once through session state. Nothing was broken.
Fix: the menu only gets its folder from session state.

**22. The popup stayed up for a moment after Yes.**
Yes did the work inside the popup, so the popup only closed once the files had moved.
Fix: Yes closes the popup first. The page then does the work under a "Working…" spinner placed where the popup was, so it disappears at once. If you click while Battery is still loading, the click waits for it to finish.
