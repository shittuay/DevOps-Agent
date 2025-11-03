"""
Translation Helper
Simple translation system without full Babel compilation
"""
from i18n_config import LANGUAGES, COMMON_TRANSLATIONS, DEFAULT_LANGUAGE

class TranslationHelper:
    """Simple translation helper"""

    @staticmethod
    def get_translation(key, language='en'):
        """Get translation for a key in specified language"""
        if language not in COMMON_TRANSLATIONS:
            language = DEFAULT_LANGUAGE

        translations = COMMON_TRANSLATIONS.get(language, COMMON_TRANSLATIONS[DEFAULT_LANGUAGE])
        return translations.get(key, key)

    @staticmethod
    def get_all_translations(language='en'):
        """Get all translations for a language"""
        if language not in COMMON_TRANSLATIONS:
            language = DEFAULT_LANGUAGE
        return COMMON_TRANSLATIONS.get(language, COMMON_TRANSLATIONS[DEFAULT_LANGUAGE])

    @staticmethod
    def get_available_languages():
        """Get list of available languages"""
        return LANGUAGES

def translate(key, language='en'):
    """Shortcut function for translation"""
    return TranslationHelper.get_translation(key, language)
