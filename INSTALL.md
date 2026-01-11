# 🚀 Быстрая установка Almatel Integration

## Шаг 1: Копирование интеграции

```bash
# Скопируйте папку custom_components/almatel в /config/custom_components/
cp -r custom_components/almatel /config/custom_components/
```

## Шаг 2: Перезагрузка Home Assistant

Перезагрузите Home Assistant

## Шаг 3: Добавление интеграции

1. **Настройки** → **Устройства и службы** → **+ Добавить интеграцию**
2. Найдите **Almatel Balance**
3. Введите данные:
   - **Логин Almatel**: ваш логин
   - **Пароль Almatel**: ваш пароль
   - **MQTT хост**: IP вашего MQTT брокера (например, 192.168.1.10)
   - **MQTT порт**: 1883
   - **MQTT пользователь**: имя пользователя MQTT
   - **MQTT пароль**: пароль MQTT
   - **Интервал обновления**: 60 минут

## Шаг 4: Настройка AppDaemon

### 4.1 Копирование скрипта

```bash
cp almatel_appdaemon.py /config/appdaemon/apps/
```

### 4.2 Редактирование apps.yaml

Добавьте в `/config/appdaemon/apps/apps.yaml`:

```yaml
almatel_checker:
  module: almatel_appdaemon
  class: Almatel
```

### 4.3 Перезапуск AppDaemon

```bash
# В терминале или через Supervisor
ha appdaemon restart
```

## Шаг 5: Проверка

### Проверьте, что создались сенсоры:
- `sensor.almatel_balance`
- `sensor.almatel_due_date`
- `sensor.almatel_days_left`

### Проверьте логи:
- Home Assistant: **Настройки** → **Система** → **Логи**
- AppDaemon: `/config/appdaemon/appdaemon.log`

## ✅ Готово!

Теперь сенсоры будут обновляться автоматически каждые 60 минут (или другой интервал, который вы указали).

## 🔧 Ручное обновление

Вызовите сервис:
```yaml
service: almatel.update_balance
```

Или создайте кнопку в Lovelace:
```yaml
type: button
tap_action:
  action: call-service
  service: almatel.update_balance
name: Обновить Almatel
icon: mdi:refresh
```

## ❓ Проблемы?

1. Проверьте логи Home Assistant
2. Проверьте логи AppDaemon
3. Убедитесь, что MQTT работает
4. Проверьте файл `/config/almatel_config.json`
