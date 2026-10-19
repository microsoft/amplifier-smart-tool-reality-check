`list-intelligence-models` lists the models a check runs its agent on, with the reasoning efforts
each takes, for the installed agent providers, and what runs when none is given. It needs no
sign-in. A check fails at once on a model not listed here, and when it starts, on one the account
does not have.

```bash
reality-check list-intelligence-models
```

```python
from reality_check.lib import list_intelligence_models

models = list_intelligence_models()
[(model.id, model.reasoning_efforts) for model in models.models], models.default
```

## Arguments

None.

## Result

JSON with `models`, each with `agent_provider`, `id` (pass it as `--model`), `label`,
`reasoning_efforts` (pass one as `--reasoning-effort`; empty when the model takes none, so leave it
out), and `vision` (whether it can be given `--image`), and `default`, the `agent_provider`, `model`,
and `reasoning_effort` a check runs with when given none.
