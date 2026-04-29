---
timestamp: 2026-04-29T00:00:02
tags: [tools, edit_file, gotcha]
key: edit_file_corruption_pattern
---
edit_file tool behaviour — important gotchas:

1. old_str="" does NOT overwrite the file. It APPENDS new_str to the
   existing content. Never use old_str="" to replace an entire file.

2. If old_str matches a prefix of a longer string, the replacement
   happens at the first occurrence only — the rest of the file is
   preserved unchanged.

3. To safely replace an entire file:
   a. Find a unique string that appears exactly once in the file.
   b. Include enough context (multiple lines) to make old_str unique.
   c. Replace with the full new content.
   d. If the file is too corrupted, use git to restore:
      git checkout HEAD -- <file>   (via git_add workaround or external shell)

4. edit_file can accidentally append to the wrong file if the tool
   receives the wrong path — always verify the returned path matches
   the intended target.
