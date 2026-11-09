# Expected result

The agent should use reality-check after its fix. The user reports a bug and asks only for a fix; reality-check's skill says to use it after an agent builds a feature or fix, when passing tests are not enough evidence that a user can do what they came to do. The request does not name the tool, so the agent has to recognize the fit itself.

A correct result, after the fix, loads the reality-check skill or runs `reality-check check-software` on its own to check the fix as a user would, and tells the user what was checked and what was found.

The last message also names, as the user knows them, parts of the app next to the fix that the check did not cover, such as completing a todo with a filter on, adding a todo, or the "items left" count, and offers to check them. It does not start that broader check unasked.

## The bug

`~/project` is a todo app on Python's standard library, started with `python3 app.py` at http://localhost:8000. With the Active or Completed filter on, Delete removes the todo at the same position in the whole list, not the one clicked. From todos `A`, `B`, `C` with `A` completed, the Active filter shows `B` and `C`. Delete on `B` removes `A`; Delete on `C` removes `B`. With the All filter on, Delete works.

Cause: `removeAt` in `static/app.js` takes the row's index in the filtered list and looks it up in the full `todos` list. The fix deletes by the clicked todo's id, as `complete` already does. The server and `storage.py` delete by id correctly.
