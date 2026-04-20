from sqlalchemy.orm import selectinload


def build_load_options(model, include: list[str]):
    options = []

    for path in include:
        parts = path.split(".")
        current = getattr(model, parts[0])
        loader = selectinload(current)

        current_model = current.property.mapper.class_

        for part in parts[1:]:
            rel = getattr(current_model, part)
            loader = loader.selectinload(rel)
            current_model = rel.property.mapper.class_

        options.append(loader)

    return options
