"""Check built-in metadata translations without importing or running enrichers."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "flowsint-enrichers/src/flowsint_enrichers"
LOCALES = ROOT / "flowsint-app/src/i18n/locales"


def source_messages() -> tuple[set[str], int]:
    messages: set[str] = set()
    count = 0
    for path in sorted(SOURCES.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef) or not any(
                isinstance(decorator, ast.Name) and decorator.id == "flowsint_enricher"
                for decorator in cls.decorator_list
            ):
                continue
            count += 1
            description = ast.get_docstring(cls, clean=False)
            for member in cls.body:
                if (
                    isinstance(member, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "metadata"
                        for target in member.targets
                    )
                    and isinstance(member.value, ast.Call)
                ):
                    for keyword in member.value.keywords:
                        if isinstance(keyword.value, ast.Constant):
                            value = keyword.value.value
                            if keyword.arg == "description":
                                description = value
                            elif (
                                keyword.arg == "api_key_notes"
                                and isinstance(value, str)
                                and value
                            ):
                                messages.add(value)
                if (
                    isinstance(member, ast.FunctionDef)
                    and member.name == "get_params_schema"
                ):
                    for node in ast.walk(member):
                        if isinstance(node, ast.Dict):
                            for key, value in zip(node.keys, node.values):
                                if (
                                    isinstance(key, ast.Constant)
                                    and key.value == "description"
                                    and isinstance(value, ast.Constant)
                                    and isinstance(value.value, str)
                                    and value.value
                                ):
                                    messages.add(value.value)
            if isinstance(description, str) and description:
                messages.add(description)
    return messages, count


def main() -> int:
    messages, count = source_messages()
    if not count:
        raise RuntimeError("Built-in enricher sources were not found")
    errors = []
    for language in ("en", "ru"):
        catalog = json.loads((LOCALES / f"enrichers.{language}.json").read_text())
        for missing in sorted(messages - catalog.keys()):
            errors.append(f"{language}: missing translation for {missing}")
        for stale in sorted(catalog.keys() - messages):
            errors.append(f"{language}: stale metadata translation for {stale}")
        for key, value in catalog.items():
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{language}: empty translation for {key}")
            elif language == "en" and value != key:
                errors.append(f"en: source text changed for {key}")
            elif language == "ru" and value == key:
                errors.append(f"ru: untranslated metadata for {key}")
    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"Validated EN/RU metadata for {count} built-in enrichers "
        f"({len(messages)} texts)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
