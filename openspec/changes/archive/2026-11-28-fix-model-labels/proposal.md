# Proposal

## Why

В 0.3.1 я убрал переводы вариантов чётности и удалил весь блок `selector` целиком. Вместе с ним
пропали переводы моделей: в мастере добавления и в перенастройке вместо «MTD062-MB (5.8 ГГц)» и
«MTD262-MB (24 ГГц)» теперь показаны ключи `mtd062-mb` и `mtd262-mb`.

Причина техническая: `SelectSelectorConfig` для модели объявлен с `translation_key="model"`, поэтому
Home Assistant ищет подписи в `selector.model.options`. Блока нет — вот ключи и показываются.

## What Changes

- Возвращаются `selector.model.options` в `strings.json`, `translations/en.json` и
  `translations/ru.json`.
- Добавляется тест, который сверяет набор вариантов выбора модели с набором переводов: пропажа
  подписей больше не пройдёт незамеченной.
- Версия 0.3.2.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `mtdx62-connection`: модель выбирается по названию, а не по ключу.

## Impact

- Только тексты и один тест; поведение мастера не меняется.
