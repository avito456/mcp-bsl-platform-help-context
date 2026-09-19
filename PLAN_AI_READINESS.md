# План: готовность MCP-сервера для уверенной работы AI-модели

Дата: 19.09.2026
Решения по развилкам:
- Объём — все этапы A+B+C.
- Англ. имена — алиасы в сущностях (name_en в Definition), индексы на оба имени, дедуп по RU-ключу.
- Вывод имён — RU первично, EN рядом как алиас.

## Диагноз (проверено на реальном 8.3.27.72/shcntx_ru.hbk)

P0:
1. Англ. имена выключены: `mapper.py` (name_ru or name_en) отбрасывает name_en, хотя в данных он есть ~на 100%. search("Add"/"ValueTable"/"FormGroup") → мусор.
2. Запрос «Тип.Метод» не разбирается: TypeMemberSearch режет только по пробелам; "ТаблицаЗначений.Добавить" не даёт нужный член в топе.
3. Результаты не показывают тип-владельца: "Добавить" ×4 неразличимы.
4. `info` требует обязательный type_filter.

P1:
5. Фейковые примеры «НайтиПоСсылке»/«FindByRef» (таких элементов нет) в инструкциях/docstrings/README.
6. Escape ломает шаблонные имена: `СправочникОбъект.\<Имя справочника\>` — модель скопирует `\`.
7. Нет health/готовности; первый semantic/hybrid = ГБ моделей + индекс; default hybrid падает без fallback.

P2:
8. Семантика не знает EN-имён (document_builder индексирует только RU).
9. Нет fuzzy по опечаткам и «did you mean».
10. Докстринги только по-русски.

---

## Этап A — P0: корректность данных для AI

- [ ] A1. Алиасы в сущностях: name_en в MethodDefinition/PropertyDefinition/PlatformTypeDefinition (+ mapper, json_loader).
- [ ] A2. Индексы по обоим именам: HashIndex/StartWithIndex на несколько ключей, find_* матчат по алиасам, дедуп по RU-ключу.
- [ ] A3. Стратегия «Тип.Метод»: split по `.`/`::`/пробелам, точный Type.Member → топ.
- [ ] A4. Owner-тип в выдаче: форматтер + server показывают `ТаблицаЗначений.Добавить (method)`.
- [ ] A5. info: type_filter=None → autodetect method/property/type, при неоднозначности — варианты.
- [ ] A6. document_builder: en-имя и EN-описание в embed-текст.

## Этап B — P1: документация и UX

- [ ] B7. Вычистить фейковые имена из SERVER_INSTRUCTIONS, docstrings, README, CLAUDE.md.
- [ ] B8. Инструмент health/status (версия, источник, готовность семантики) + конфиг warmup.
- [ ] B9. Авто-fallback: hybrid/semantic при недоступных моделях → keyword с пометкой.
- [ ] B10. Фикс escape шаблонных имён (code-span без `\<`).

## Этап C — P2: качество

- [ ] C11. Fuzzy (Damerau-Levenshtein) в keyword + «Did you mean» в info/get_member.
- [ ] C12. Двуязычные описания инструментов + EN-блок в SERVER_INSTRUCTIONS.
- [ ] C13. Интеграционные тесты на реальном HBK + grep-guard от фейковых имён.

## Проверка

- `uv run pytest -q` — все существующие (263) + новые зелёные.
- E2E: search("ValueTable"), search("ТаблицаЗначений.Добавить"), info с шаблонным типом без `\`.