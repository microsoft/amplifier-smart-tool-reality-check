`manifest` prints the tool's manifest as JSON on stdout: `smart_tool_format`, `name`,
`version`, `description`, `use_cases`, `platforms`, `requires`, and `body`, the Markdown the
tool's skill renders. It takes no arguments and needs no credentials, so it is how to verify
an install: JSON on stdout and exit 0 means the tool is installed and runnable.

```bash
reality-check manifest
```

```python
from reality_check.lib import load_manifest

manifest = load_manifest()
manifest.name, manifest.version, manifest.use_cases, manifest.body
```
