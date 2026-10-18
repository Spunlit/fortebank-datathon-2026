# Лицензии — инструменты первого аудита

## Раунд 9: независимый embedding baseline

Выбран `google/siglip-base-patch16-224`, revision
`7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed`. Официальная опубликованная
[карточка](https://huggingface.co/google/siglip-base-patch16-224/blob/7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed/README.md)
указывает `license: apache-2.0`. Карточку подготовила Hugging Face, что явно
отмечено в ней. Метаданные репозитория сохранены в `reports/embedding_source.json`,
сама карточка — в `.cache/models/siglip-base-patch16-224/README.md`.
Текст Apache-2.0 из [исходного проекта Google](https://github.com/google-research/big_vision/blob/main/LICENSE)
сохранён в `reports/public_sources/siglip_license.txt`. Использование, включая
коммерческое, допускается при соблюдении условий Apache-2.0 и уведомлений.
Веса загружены без квантизации: 812 672 320 байт, SHA-256 совпал с LFS источника;
`reports/embedding_download.json`. Runtime — ранее проверенные transformers и PyTorch.

`numpy==2.5.3`, уже установленный: основной LICENSE прочитан локально в
`.venv/Lib/site-packages/numpy-2.5.3.dist-info/licenses/LICENSE.txt`.
Metadata: `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`;
основной проект BSD-3-Clause, bundled OpenBLAS и прочие компоненты имеют отдельные
уведомления в том же файле. Новых Python-зависимостей в этом раунде не установлено.

CLIP OpenAI рассмотрен, но веса не скачаны и не использованы: опубликованная
карточка не содержала явной отдельной лицензии весов. Это не утверждение о запрете
использования; выбран предусмотренный планом SigLIP с явным указанием лицензии.

## Раунд 8: локальный HTTP-сервис

До установки скачаны wheel в `.cache/service-wheels`, прочитаны вложенные LICENSE
и metadata. Тексты лицензий, пути и SHA-256 wheel сохранены в
`reports/service_license_evidence.json`; фактическая установка — `reports/service_install.json`.
Версии закреплены в `requirements-service.txt`. Прямые и перечисленные транзитивные
лицензии допускают коммерческое использование с соблюдением уведомлений и условий.

| Компоненты | Версии | Лицензия |
|---|---|---|
| fastapi | 0.115.12 | MIT |
| uvicorn / starlette | 0.34.2 / 0.46.2 | BSD-3-Clause |
| python-multipart | 0.0.20 | Apache-2.0 |
| pydantic / pydantic-core | 2.14.1 / 2.50.1 | MIT |
| annotated-types / typing-inspection | 0.8.0 / 0.4.4 | MIT |
| anyio / h11 | 4.15.1 / 0.16.0 | MIT |
| click / idna | 8.5.0 / 3.20 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |

`pip check` после установки: exit 0, `No broken requirements found`.
GPU/model/PyAV/Pillow имеют отдельные условия, описанные ниже; новых весов в этом раунде нет.

В раунде 4 загружены выбранные веса Qwen3-VL-4B-Instruct и выполнен offline inference. Сведения ниже включают историю проверок и не являются полным аудитом лицензий будущего распространяемого сервиса.

| Компонент | Версия | Проверенное локальное свидетельство |
|---|---|---|
| PyAV | 19.0.1 | Metadata: BSD-3-Clause; прочитан `.venv/Lib/site-packages/av-19.0.1.dist-info/licenses/LICENSE.txt` |
| openpyxl | 3.1.5 | Metadata установленного wheel: MIT |
| et-xmlfile | 2.0.0 | Metadata установленного wheel: MIT |
| FFmpeg DLL в wheel PyAV: avcodec, avformat, avutil | ABI 63 / 63 / 61 | Реальный вызов `avcodec_license`, `avformat_license`, `avutil_license`: `LGPL version 3 or later` |

Лицензии BSD/MIT и LGPL допускают коммерческое использование при соблюдении условий. Перед распространением сборки сохранить уведомления и выполнить применимые требования LGPL; транзитивный состав конечного продукта пока не проверен. Wheel PyAV нельзя описывать как целиком BSD: связанные FFmpeg-библиотеки имеют отдельную лицензию.

Общие первоисточники: https://github.com/PyAV-Org/PyAV ; https://ffmpeg.org/legal.html ; https://openpyxl.readthedocs.io/ . Версии выше установлены фактическим запуском pip; для воспроизведения используется `requirements-audit.txt`.

## CUDA preflight

Для проверки выбран официальный `torch==2.7.1+cu128`, Windows x64 / CPython 3.13, индекс https://download.pytorch.org/whl/cu128. Поддержка Blackwell в ветке 2.7/CUDA 12.8 описана в [релизе PyTorch](https://pytorch.org/blog/pytorch-2-7/); реальную совместимость этой Windows-сборки устанавливает GPU-тест, не статья.

Открыт [LICENSE исходников PyTorch v2.7.1](https://raw.githubusercontent.com/pytorch/pytorch/v2.7.1/LICENSE): BSD-3-Clause, использование и распространение допускаются с сохранением уведомлений и соблюдением условий. Это относится к исходникам PyTorch. CUDA/cuDNN и другие бинарные зависимости имеют отдельные условия; весь CUDA wheel нельзя называть целиком BSD или open source. Проверка лицензий итогового распространяемого сервиса остаётся отдельной задачей. Веса модели и runtime квантизации этим не проверены.

Установка завершилась с exit 0; точные версии, URL и хеши wheel записаны pip в `reports/torch_install.json`. `reports/gpu_package_licenses.json` сохраняет поля лицензий установленных Python-пакетов. Там пустое поле означает отсутствие значения в metadata, а не отсутствие лицензии. Дополнительно прочитаны локальные тексты Jinja2 и setuptools:

| Компонент | Версия | Свидетельство |
|---|---|---|
| torch | 2.7.1+cu128 | metadata BSD-3-Clause; исходный LICENSE; bundled LICENSE содержит отдельные лицензии зависимостей |
| sympy / mpmath | 1.14.0 / 1.3.0 | metadata: BSD (точный вариант не уточнён) |
| typing_extensions | 4.16.0 | metadata: PSF-2.0 |
| filelock | 3.32.3 | metadata: MIT |
| fsspec | 2026.7.0 | metadata: BSD-3-Clause |
| Jinja2 | 3.1.6 | локальный `jinja2-3.1.6.dist-info/licenses/LICENSE.txt`: BSD-3-Clause |
| MarkupSafe | 3.0.3 | metadata: BSD-3-Clause |
| networkx | 3.6.1 | metadata: BSD-3-Clause |
| setuptools | 78.1.0 | локальный `setuptools-78.1.0.dist-info/licenses/LICENSE`: MIT |

Это инвентаризация среды preflight, не полный аудит всех транзитивных бинарных компонентов для распространения.

## Раунд 3: кандидат Qwen3-VL + NF4

Прочитаны локальные LICENSE установленных wheel; пути и SHA-256 записаны в `reports/runtime_license_evidence.json`.

| Компонент | Версия | Проверенное свидетельство |
|---|---|---|
| transformers | 4.57.6 | `transformers-4.57.6.dist-info/licenses/LICENSE`: Apache-2.0 |
| accelerate | 1.12.0 | `accelerate-1.12.0.dist-info/licenses/LICENSE`: Apache-2.0 |
| bitsandbytes, локальная NF4-квантизация | 0.48.2 | `bitsandbytes-0.48.2.dist-info/licenses/LICENSE`: MIT; ранее сохранён официальный исходный LICENSE в `reports/public_sources/bnb_license.txt` |
| Pillow | 12.0.0 | `pillow-12.0.0.dist-info/licenses/LICENSE`: основной проект MIT-CMU; файл также содержит отдельные уведомления бинарных зависимостей |
| Qwen/Qwen3-VL-4B-Instruct | revision `ebb281ec70b05090aa6165b016eac8ec08e71b17` | Сохранённая официальная карточка `reports/public_sources/qwen_readme.txt` объявляет `license: apache-2.0`; веса не загружены |

Для NF4 предполагается локальная квантизация исходных весов: сторонние квантизованные веса не выбраны. Лицензии верхнего уровня зафиксированы; полный состав зависимостей и условия распространения бинарной сборки этим не проверены. Техническая совместимость NF4 подтверждена только синтетическими вычислениями (`reports/quantization_check.json`).

## Раунд 4: извлечение публичного PDF

`pypdf==6.1.1`: BSD-3-Clause, прочитан локальный `.venv/Lib/site-packages/pypdf-6.1.1.dist-info/licenses/LICENSE`. Используется только для извлечения текста публичного документа НБК; не входит в inference. Установка записана в `reports/pypdf_install.log`.

`torchvision==0.22.1+cu128`: BSD-3-Clause, прочитан локальный `.venv/Lib/site-packages/torchvision-0.22.1+cu128.dist-info/LICENSE`. Официальный wheel из `https://download.pytorch.org/whl/cu128`; версия совместима с установленным torch 2.7.1+cu128, `pip check` выполнен. Нужен AutoVideoProcessor при создании Qwen3VLProcessor, даже для обработки набора изображений. Метаданные/хеш wheel: `reports/torchvision_install.json`; бинарные CUDA-зависимости имеют отдельные условия, как отмечено выше.

Выбранные веса Qwen, той же закреплённой revision и с `license: apache-2.0` в официальной карточке, теперь загружены полностью. SHA-256 обоих шардов совпал с официальными LFS-метаданными: `reports/model_download_ranges.json`. NF4 создаётся локально из этих исходных весов, отдельные сторонние квантизованные веса не используются. Реальный offline inference завершён; это подтверждает работоспособность, но не сохранение качества при квантизации.
