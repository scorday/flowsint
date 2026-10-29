"""Check built-in type translations without importing the backend or its dependencies."""

import ast
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "flowsint-types/src/flowsint_types"
LOCALES = ROOT / "flowsint-app/src/i18n/locales"


def source_messages() -> tuple[set[str], int]:
    messages: set[str] = set()
    count = 0
    for path in sorted(SOURCES.glob("*.py")):
        for cls in ast.parse(path.read_text()).body:
            if not isinstance(cls, ast.ClassDef) or not any(
                isinstance(decorator, ast.Name) and decorator.id == "flowsint_type"
                for decorator in cls.decorator_list
            ):
                continue
            count += 1
            messages.add(cls.name)
            description = inspect.cleandoc(ast.get_docstring(cls, clean=False) or "")
            if description:
                messages.add(description)
    return messages, count


def main() -> int:
    messages, count = source_messages()
    if not count:
        raise RuntimeError("Built-in type sources were not found")
    messages.add("Add entity: {{type}}")
    errors = []
    for language in ("en", "ru"):
        catalog = json.loads((LOCALES / f"types.{language}.json").read_text())
        for missing in sorted(messages - catalog.keys()):
            errors.append(f"{language}: missing translation for {missing}")
        for stale in sorted(catalog.keys() - messages):
            errors.append(f"{language}: stale type translation for {stale}")
        for key, value in catalog.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{language}: empty translation for {key}")
            elif language == "en" and value != key:
                errors.append(f"en: source text changed for {key}")
            elif language == "ru" and value == key:
                errors.append(f"ru: untranslated type metadata for {key}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Validated EN/RU metadata for {count} built-in types ({len(messages)} texts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
