"""Language-neutral entity identity and Home Assistant translation metadata."""


class CasaEntity:
    """Keep a language-neutral ID suggestion on current Home Assistant Core."""

    @property
    def suggested_object_id(self):
        """Use the supported Entity property, independent of translated names."""
        return f"casa_{self._attr_translation_key}"


def configure_translation(entity, hub):
    """Use translations without migrating or renaming registered entities.

    Home Assistant retains entity_id and user names by the existing unique_id.
    New IDs use an English suggestion, independent of the selected language.
    Entity names follow Home Assistant server-language semantics; states and
    dialog text are translated by the frontend for each user's language.
    """
    key = entity._attr_unique_id.removeprefix(f"casa_premium_{hub.host}_")
    entity._attr_has_entity_name = True
    entity._attr_translation_key = key
