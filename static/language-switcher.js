/**
 * Language Switcher Component
 * Handles language selection and translation updates
 */

class LanguageSwitcher {
    constructor() {
        this.currentLanguage = 'en';
        this.availableLanguages = {};
        this.translations = {};
        this.init();
    }

    async init() {
        // Load available languages
        await this.loadAvailableLanguages();

        // Get current language from user or session
        this.currentLanguage = await this.getCurrentLanguage();

        // Load translations
        await this.loadTranslations(this.currentLanguage);

        // Update UI
        this.updateLanguageDisplay();
    }

    async loadAvailableLanguages() {
        try {
            const response = await fetch('/api/language/available');
            const data = await response.json();
            this.availableLanguages = data.languages;
        } catch (error) {
            console.error('Error loading languages:', error);
        }
    }

    async getCurrentLanguage() {
        // Check if user has a preference
        const storedLang = localStorage.getItem('language');
        if (storedLang) {
            return storedLang;
        }

        // Try to get from user profile
        try {
            const response = await fetch('/api/subscription');
            if (response.ok) {
                const data = await response.json();
                if (data.user && data.user.language) {
                    return data.user.language;
                }
            }
        } catch (error) {
            console.log('Could not load user language preference');
        }

        // Default to English
        return 'en';
    }

    async loadTranslations(language) {
        try {
            const response = await fetch(`/api/language/translations?language=${language}`);
            const data = await response.json();
            this.translations = data.translations;
            this.currentLanguage = data.language;
            localStorage.setItem('language', this.currentLanguage);
        } catch (error) {
            console.error('Error loading translations:', error);
        }
    }

    async setLanguage(language) {
        try {
            // Send to server if user is logged in
            const response = await fetch('/api/language/set', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ language })
            });

            if (response.ok) {
                // Reload translations
                await this.loadTranslations(language);

                // Update UI
                this.updateLanguageDisplay();
                this.translatePage();

                // Show success message
                this.showNotification('Language changed successfully!');

                // Reload page to apply translations to server-rendered content
                setTimeout(() => {
                    window.location.reload();
                }, 500);
            }
        } catch (error) {
            console.error('Error setting language:', error);

            // Fallback: just change locally
            await this.loadTranslations(language);
            this.updateLanguageDisplay();
            this.translatePage();
        }
    }

    updateLanguageDisplay() {
        const langDisplay = document.getElementById('current-language-display');
        if (langDisplay && this.availableLanguages[this.currentLanguage]) {
            const lang = this.availableLanguages[this.currentLanguage];
            langDisplay.innerHTML = `${lang.flag} ${lang.name}`;
        }

        // Update dropdown selection if exists
        const dropdown = document.getElementById('language-select');
        if (dropdown) {
            dropdown.value = this.currentLanguage;
        }
    }

    translatePage() {
        // Translate all elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            if (this.translations[key]) {
                element.textContent = this.translations[key];
            }
        });

        // Translate placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
            const key = element.getAttribute('data-i18n-placeholder');
            if (this.translations[key]) {
                element.placeholder = this.translations[key];
            }
        });
    }

    translate(key) {
        return this.translations[key] || key;
    }

    createDropdown() {
        const container = document.createElement('div');
        container.className = 'language-switcher';
        container.innerHTML = `
            <button class="language-button" id="language-button">
                <span id="current-language-display">🇺🇸 English</span>
                <span class="dropdown-arrow">▼</span>
            </button>
            <div class="language-dropdown" id="language-dropdown">
                ${Object.entries(this.availableLanguages).map(([code, lang]) => `
                    <button class="language-option" data-lang="${code}">
                        ${lang.flag} ${lang.name}
                    </button>
                `).join('')}
            </div>
        `;

        // Add event listeners
        const button = container.querySelector('#language-button');
        const dropdown = container.querySelector('#language-dropdown');

        button.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', () => {
            dropdown.classList.remove('show');
        });

        // Handle language selection
        container.querySelectorAll('.language-option').forEach(option => {
            option.addEventListener('click', (e) => {
                const lang = e.currentTarget.getAttribute('data-lang');
                this.setLanguage(lang);
                dropdown.classList.remove('show');
            });
        });

        return container;
    }

    showNotification(message) {
        const notification = document.createElement('div');
        notification.className = 'language-notification';
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #4caf50;
            color: white;
            padding: 12px 20px;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 10000;
            animation: slideIn 0.3s ease-out;
        `;
        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => notification.remove(), 300);
        }, 2000);
    }
}

// Add CSS for language switcher
const style = document.createElement('style');
style.textContent = `
    .language-switcher {
        position: relative;
        display: inline-block;
    }

    .language-button {
        background: white;
        border: 1px solid #ddd;
        padding: 8px 16px;
        border-radius: 6px;
        cursor: pointer;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        transition: all 0.2s;
    }

    .language-button:hover {
        background: #f5f5f5;
        border-color: #cd7c48;
    }

    .dropdown-arrow {
        font-size: 10px;
        transition: transform 0.2s;
    }

    .language-dropdown {
        display: none;
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 4px;
        background: white;
        border: 1px solid #ddd;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        min-width: 200px;
        max-height: 400px;
        overflow-y: auto;
        z-index: 1000;
    }

    .language-dropdown.show {
        display: block;
    }

    .language-option {
        width: 100%;
        padding: 10px 16px;
        border: none;
        background: none;
        text-align: left;
        cursor: pointer;
        font-size: 14px;
        transition: background 0.2s;
    }

    .language-option:hover {
        background: #f5f5f5;
    }

    .language-option:first-child {
        border-radius: 6px 6px 0 0;
    }

    .language-option:last-child {
        border-radius: 0 0 6px 6px;
    }

    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// Global instance
window.languageSwitcher = new LanguageSwitcher();

// Helper function to translate text
window.t = function(key) {
    return window.languageSwitcher.translate(key);
};
