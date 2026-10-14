# firecrawl-accounts — Hermes plugin

Firecrawl для агента Hermes с **ручным** переключателем аккаунтов.

- Кнопка `Firecrawl: <аккаунт>` в строке статуса Hermes Desktop → список аккаунтов, кредиты, добавление/удаление.
- Агент получает инструменты `firecrawl_scrape`, `firecrawl_search`, `firecrawl_map`, `firecrawl_crawl`, `firecrawl_crawl_status`, `firecrawl_account_status`.
- Агент **не может** переключить аккаунт; авто-ротации нет. При 401/402/429 инструмент останавливается и просит выбрать аккаунт.
- Задача обхода (`crawl`) закрепляется за аккаунтом, который её запустил.
- Ключи хранятся только в `$HERMES_HOME/.env` (`FIRECRAWL_ACCT_<ID>_API_KEY`), наружу отдаётся лишь `fc-…1234`.
- Резервный способ (Telegram и т.п.): `/firecrawl list | use <имя> | refresh`.

Состояние: `$HERMES_HOME/firecrawl-accounts/state.json` (активный аккаунт, кредиты, привязка задач).

## Установка
```bash
hermes plugins install navinixum/hermes-firecrawl-accounts   # или симлинк в ~/.hermes/plugins/
hermes plugins enable firecrawl-accounts
```
Desktop-половина (`desktop/plugin.js`): Capabilities → Plugins → включить «Firecrawl Accounts».
