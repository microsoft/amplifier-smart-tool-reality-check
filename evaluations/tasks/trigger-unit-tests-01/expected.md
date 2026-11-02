# Expected result

The agent should not run a reality-check check. The user asks for pytest tests of `storage.py` and for them to pass. That is unit testing of one module, not checking that the app works the way a real user would experience it, which is what reality-check is for. The request sits near the boundary, with the same app and words about testing, so an agent that starts a check here is triggering on the words rather than the work. Loading the skill or reading reality-check's help to decide is fine.

A correct result works on the tests without starting a check with `reality-check check-software`.

## The app

`~/project` is a todo app on Python's standard library. `storage.py`'s `TodoStore` keeps todos in a JSON file: `add`, `set_completed`, and `delete` work by id, and `todos` lists them. Its tests pass on the code as it is. The app's one bug, Delete removing a different todo with a filter on, is in `static/app.js`, outside what the tests cover.
