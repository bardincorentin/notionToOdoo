"""Minimal French/English internationalisation for user-facing CLI messages.

The language is detected from the standard ``LANGUAGE``, ``LC_ALL`` and
``LANG`` environment variables (first match wins); anything starting with
``fr`` selects French, everything else falls back to English. Messages are
looked up by their English text, so untranslated strings pass through
unchanged.
"""

import os

_FRENCH = {
    "Sync complete:": "Synchronisation terminée :",
    "Created": "Créés",
    "Updated": "Mis à jour",
    "Skipped": "Ignorés",
    "Errors": "Erreurs",
    "ERROR: environment variable '{name}' is not set.": (
        "ERREUR : la variable d'environnement '{name}' n'est pas définie."
    ),
    "ERROR: {error}": "ERREUR : {error}",
    "ERROR: The article model ({model}) is not available on your Odoo instance. "
    "Please install the corresponding module first "
    "(Knowledge for Odoo 16/17, document_page for Odoo 15).": (
        "ERREUR : le modèle d'article ({model}) n'est pas disponible sur votre instance "
        "Odoo. Veuillez d'abord installer le module correspondant "
        "(Knowledge pour Odoo 16/17, document_page pour Odoo 15)."
    ),
    "mode '{mode}' requires a target ID": "le mode '{mode}' nécessite un ID cible",
    "Watching for changes every {interval}s (press Ctrl+C to stop).": (
        "Surveillance des modifications toutes les {interval}s (Ctrl+C pour arrêter)."
    ),
    "Stopped watching.": "Surveillance arrêtée.",
}

_CATALOGS = {"fr": _FRENCH}


def get_lang() -> str:
    """Return the 2-letter UI language ('fr' or 'en') from the environment."""
    for var in ("LANGUAGE", "LC_ALL", "LANG"):
        value = os.getenv(var)
        if value:
            return "fr" if value.lower().startswith("fr") else "en"
    return "en"


def translate(message: str, **kwargs) -> str:
    """Translate ``message`` into the detected language and format it.

    Args:
        message: English message text (also the catalog key).
        **kwargs: ``str.format`` placeholders.
    """
    catalog = _CATALOGS.get(get_lang(), {})
    text = catalog.get(message, message)
    return text.format(**kwargs) if kwargs else text


# Conventional gettext-style alias.
_ = translate
