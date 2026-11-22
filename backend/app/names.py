"""The app sends "App user" when an account has no name. It is never a person's name."""

PLACEHOLDER_NAMES = {"app user"}


def real_name(value: str | None) -> str:
    text = " ".join((value or "").split())
    return "" if text.casefold() in PLACEHOLDER_NAMES else text


def first_name(value: str | None) -> str:
    name = real_name(value)
    return name.split()[0] if name else ""
