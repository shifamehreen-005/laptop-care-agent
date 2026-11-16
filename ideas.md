# Ideas

Not built yet. Short notes from using the app.

## Make Ask an agent faster

Ask an agent uses `qwen2.5:3b`. On the test folder a normal scan already spends about a minute on 42 documents (about 1.1–1.6 seconds each on `llama3.2:1b`). Qwen is slower than that, so a big Ask will sit on Working.

**1. After the folder names, sort the rest locally.**
Qwen already names the folders once, from up to 24 files, then places every leftover in batches of 8. Match those leftovers to the names with the file name and a few keywords, and send only the unsure ones back.
Why: the names are already shared. The slow part left is a model call for every leftover.

**2. Remember the answer for a file that has not changed.**
Save the folder name with the file's sha256. The next scan skips that file.
Why: a second Ask on the same folder should not reread every file.

**3. Leave Qwen loaded while you are in Ask.**
The first Ask after a normal scan unloads `llama3.2:1b` and loads Qwen. That load is the long pause. Later Asks in the same visit are the fast ones.
Why: 8 GB can only hold one model, so switching is the expensive part, not the second question.

**4. Start with the extension, then ask only about mixed folders.**
Group by file type is instant. A second button, "Split this folder by what's inside", sends one card's files to Qwen.
Why: a lab folder of `.html` does not need the model to notice they are HTML. It needs the model only when one extension holds many subjects.

**5. Show progress and let the user stop.**
"Sorted 20 of 80", and Stop keeps the folders already chosen.
Why: a long spinner with no count feels stuck.

## Other ideas

**6. Keep a suggestion when its files still sit in Review.**
Remove on Review sends those files to No folder, and the suggested card (such as Web Development) disappears because it needs two files. The suggestion could stay until Add or its own Remove.
Why: Remove looked like it deleted a second folder.

**7. Collapse a card that has more than about 20 files.**
Show the count, a search box, and Show all. Approve can still move the whole card.
Why: a big folder becomes a wall of chips.

**8. Approve in batches.**
Ask about the first group, Approve, then the next, instead of one screen of hundreds of files.

**9. Simple mode.**
Bigger type, fewer buttons, one sentence: "Move these 8 files to Receipts?" The review screen stays for people who want every file.

**10. Grade about 20 real files you label yourself.**
The generated folder is easier than a real Downloads folder, because the same project wrote the files and the rules. That set is the honest number. Eval already refuses to change the folder.
