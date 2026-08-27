def generate_skill(description: str) -> tuple[str, str]:
    name = "Generated Business Workflow"
    content = f"""# {name}

## Purpose

{description.strip()}

## Workflow

1. Gather the required business context.
2. Produce a structured draft.
3. Validate facts and request approval before external actions.

## Output

Return a concise Markdown deliverable with sources and unresolved questions.
"""
    return name, content
