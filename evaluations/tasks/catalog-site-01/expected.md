# Expected finding

Every tool card on the catalog page has an Install box with a command and a Copy button. One of them copies the wrong command.

- Deep Research (`deep-research`, the 16th of 22 cards in the full list): the box shows `uv tool install "git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/deep-research"`, but Copy puts `uv tool install "git+https://github.com/colombod/amplifier-smart-tools-research#subdirectory=tools/fact-check"` on the clipboard, the command of Fact Check, the card after it.
- Every other Copy button, including the two recommended cards at the top, their repeats in the list, and the skill install box (`npx skills add microsoft/amplifier-smart-tools`), copies exactly the text it shows.

The visible text of every card is correct, so the defect shows only by reading what Copy put on the clipboard.

Cause: `image/scenario.patch` adds the Install boxes. `site/theme/site.js` finds the command for a button in a map keyed by package, and `site/theme/build.py` takes the package as the first segment of the tool's path in its repository. Both research tools are under `tools/`, so they share the key `tools`, and the map keeps the later one, Fact Check.

The served site has no other changes from upstream. Its links to other family sites go to the real hosts.
