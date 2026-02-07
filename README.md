# Almatel - Интеграция для Home Assistant

Кастомная интеграция для мониторинга баланса и срока оплаты интернет провайдера Almatel в Home Assistant.

## 🎯 Особенности

- ✅ Настройка через UI (Config Flow)
- ✅ Автоматическое создание сенсоров
- ✅ Русская локализация
- ✅ Безопасное хранение паролей
- ✅ Интеграция с AppDaemon + Selenium
- ✅ MQTT Discovery
- ✅ Сервис для ручного обновления

## 📊 Создаваемые сенсоры

После установки создается сенсор:

**sensor.almatelad** - Баланс (₽)
c атрибутами:
**due_date** - Срок оплаты (дата)
**days_left** - Дней до оплаты

## 📋 Требования

### Home Assistant
- Home Assistant 2023.1 или выше
- MQTT интеграция (настроенная)

### AppDaemon
- AppDaemon 4.x
- Python Selenium
- Chromium / ChromeDriver
- paho-mqtt

### SSH, SAMBA, HACS

## 🚀 Установка

### Шаг 1: Установка интеграции

**Вручную**:
```bash
cd /config/custom_components/
# Скопируйте папку almatel
```

**Перезагрузите Home Assistant**

### Шаг 2: Настройка интеграции

1. Перейдите в **Настройки** → **Устройства и службы**
2. Нажмите **+ Добавить интеграцию**
3. Найдите **Almatel**
4. Введите данные:
   - Логин Almatel
   - Пароль Almatel
   - MQTT хост (например: 192.168.1.10)
   - MQTT порт (обычно 1883)
   - MQTT пользователь
   - MQTT пароль
   - Интервал обновления (минуты)

5. Нажмите **Отправить**

### Шаг 3: Установка AppDaemon скрипта

1. Скопируйте файл `almatel.py` в папку AppDaemon:
   ```bash
   cp almatel.py /addon_configs/a0d7b954_appdaemon/apps/
   ```

2. Добавьте в `/addon_configs/a0d7b954_appdaemon/apps/apps.yaml`:
   ```yaml
   almatel:
     module: almatel
     class: Almatel
   ```

3. Перезапустите AppDaemon

## 🔧 Настройка после установки

### Изменение интервала обновления

1. Перейдите в **Настройки** → **Устройства и службы**
2. Найдите **Almatel**
3. Нажмите **Настроить**
4. Измените интервал обновления

### Ручное обновление

Используйте сервис:
```yaml
service: almatel.update_balance
```

## 📱 Примеры использования

### Карточка с балансом

```yaml
type: entities
title: Almatel
  - entity: sensor.almatelad
    unit_of_measurement: RUR
    type: custom:multiple-entity-row
    state_header: Текущий баланс
    secondary_info: last-changed
    tap_action:
      action: more-info
    hold_action:
      action: url
      confirmation: true
      url_path: https://almatel.ru/lk/login.php
    double_tap_action:
      action: url
      confirmation: false
      url_path: https://almatel.ru/lk/login.php
    entities:
      - entity: sensor.almatelad
        type: attribute
        attribute: days_left
        name: Дней до оплаты
      - entity: sensor.almatelad
        type: attribute
        attribute: due_date
        name: Срок оплаты (дата)
```

### Уведомление о низком балансе

```yaml
automation:
  - alias: "Almatel: Низкий баланс"
    trigger:
      - platform: numeric_state
        entity_id: sensor.almatelad
        below: 100
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Almatel"
          message: "Баланс ниже 100₽!"
```

## 🛠️ Устранение неполадок

### Сенсоры не создаются

1. Проверьте, что MQTT интеграция работает
2. Проверьте логи Home Assistant
3. Убедитесь, что AppDaemon запущен

### Данные не обновляются

1. Проверьте логи AppDaemon
2. Убедитесь, что Selenium установлен (Это важно!)
3. Проверьте настройки MQTT
4. Проверьте файл `/config/almatel_config.json`

## 🔄 Как это работает

1. **Интеграция** создает файл `/config/almatel_config.json`
2. **AppDaemon** читает файл и запускает Selenium
3. **Selenium** получает данные с сайта Almatel
4. **AppDaemon** публикует данные в MQTT
5. **Интеграция** создает сенсоры из MQTT

## 📄 Лицензия

MIT License
