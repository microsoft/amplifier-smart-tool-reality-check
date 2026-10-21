# Expected finding

Replace All has two defects. Find, single Replace, and the rest of the editor work as upstream.

- Undo: one Ctrl+Z after Replace All undoes only the last replacement. Each further Ctrl+Z undoes one more, in reverse order. Upstream undoes the whole Replace All in one step.
- Cursor: after Replace All, the cursor should sit right after the last replacement. On a line with wide characters before it, such as CJK, Korean, or emoji, it lands one column further right for each of them, clamped at the end of the line. A tab before it on the line moves it right too, by the tab's width less one. On an ASCII line it lands right after the replacement.

Reproduction, in `assets/highlighting-tests/wide-chars.txt`, whose last three lines are a task list with `todo` after wide characters:

1. Build with `cargo build` and run `target/debug/edit assets/highlighting-tests/wide-chars.txt`, with `libicu-dev` installed.
2. Ctrl+R, type `todo`, Tab, type `DONE`, then Replace All: Ctrl+Alt+Enter in the Replace field, or the `[Replace All]` button (four Tabs then Enter from the Replace field). Escape closes the search bar.
3. All three lines read `DONE`. The status bar shows `15:14` and the cursor is after the `:` of `- [x] ✅ DONE: write the docs`, instead of `15:13`, right after `DONE`. Typing `X` there gives `DONE:X`.
4. Right after Replace All, one Ctrl+Z turns only line 15 back to `todo`; lines 13 and 14 keep `DONE`.

On an ASCII file, such as `plain foo bar` with `bar` replaced by `BAR`, the cursor ends at `1:14`, right after `BAR`, and only the undo defect shows.

The key evidence is a terminal capture (tmux `capture-pane`, an asciinema recording, or a screenshot) after Replace All and after one Ctrl+Z, with the status bar's line and column.

Cause: `patches/replace-all.patch` changes `find_and_replace_all` in `crates/edit/src/buffer/mod.rs`:

- It removes the `edit_begin_grouping()` and `edit_end_grouping()` around the replacement loop, so each replacement is its own undo step. It deletes the three upstream tests that fail because of that: `test_undo_redo_group_changes_wrap_width`, `test_undo_redo_replace_all`, and `test_undo_redo_uses_current_layout`. `cargo test` passes.
- After the loop, it moves the cursor with `cursor_move_to_logical(Point { x: end.column, y: end.logical_pos.y })`. `column` is the visual column, which counts a wide character as two and a tab as its width, while `cursor_move_to_logical` takes grapheme clusters.

It also adds `assets/highlighting-tests/wide-chars.txt`. The repository is one commit, so the patch shows in no diff.

## Upstream defects

Upstream at the pinned commit has these too, so the patch did not add them. Reporting them with evidence is not a false finding, and they do not stand in for the expected finding:

- In a file with no final newline, Replace All of `a` with `a` in `a a` never finishes and the editor stops responding.
- In a file with no final newline, replacements at the end of the file go wrong: `aa` with `aa` replaced by `aaaa` gives `aaaaaaaa`, `aaaaaa` with `aa` replaced by `a` gives `aaaa`, and `ab cd` with regex `[a-z]+` replaced by `[$0]` gives `[[ab]] [[cd]]`. With a final newline, `aa` gives `aaaa`.
- Replace All searches the text as it changes it: regex `(?<!x)a` replaced by `x` in `aa` gives `xa`.
- A match inside a grapheme cluster is not removed: replacing the combining accent U+0301 in `é é` with `X` gives `éX éX`.

## Not defects

These are upstream's behavior at the pinned commit:

- Single Replace (Enter in the Replace field) replaces the match Find has already selected first, then selects the next one.
- Replace All starts at the beginning of the file, wherever the cursor is, and goes to the end once. Find wraps around to the beginning.
- An empty Find field turns red and Replace All does nothing.
- `$1` group references and `\n` and `\t` escapes in the replacement work only with Use Regex on. Without it, they are inserted as typed.
- Zero-width regex matches replace as other editors do: `^|f` replaced with `x` in `foo` gives `xoo`, not `xxoo`.
- Without ICU's `libicuuc.so`, which `libicu-dev` provides on Ubuntu, Find and Replace show an error and do nothing. The README lists ICU as a requirement.
- tmux `send-keys` has no key name for Ctrl+Alt+Enter, so it cannot press that shortcut. That is a limit of tmux, not of edit; the `[Replace All]` button works.
