# Expected result

The agent should use reality-check. The user asks to make sure people can use the app's features, which is what reality-check's skill describes: checking that an app works the way a real user would experience it. The request does not name the tool, so the agent has to recognize the fit itself.

A correct result loads the reality-check skill or runs `reality-check check-software` on its own, then tells the user what was checked and what was found.

## The app

`~/project` is a todo app on Python's standard library, started with `python3 app.py` at http://localhost:8000. Adding, completing, and filtering work. Delete works with the All filter on.

The defect: with the Active or Completed filter on, Delete removes the todo at the same position in the whole list, not the one clicked. From todos `A`, `B`, `C` with `A` completed, the Active filter shows `B` and `C`. Delete on `B` removes `A`; Delete on `C` removes `B`. The clicked todo stays.

Cause: `removeAt` in `static/app.js` takes the row's index in the filtered list and looks it up in the full `todos` list. The server and `storage.py` delete by id correctly.
