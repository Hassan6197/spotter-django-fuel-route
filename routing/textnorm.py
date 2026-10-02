"""City-name normalization shared by the offline build step and request-time lookup."""
import re

SUFFIXES = (
    " city and borough", " consolidated government", " metropolitan government",
    " unified government", " urban county", " municipality", " borough", " city",
    " town", " village", " cdp", " township", " plantation", " comunidad",
    " zona urbana",
)


def normalize(name: str) -> str:
    name = re.sub(r"\s+", " ", name.lower().strip())
    name = name.replace("saint ", "st ").replace("st. ", "st ").replace("ft. ", "fort ")
    name = name.replace("mt. ", "mount ").replace("mt ", "mount ")
    name = re.sub(r"[.'`]", "", name)
    changed = True
    while changed:
        changed = False
        for suffix in SUFFIXES:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                changed = True
    return name.strip()
