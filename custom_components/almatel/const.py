"""Constants for the Almatel integration."""

DOMAIN = "almatel"

# Configuration keys
CONF_ALMATEL_LOGIN = "almatel_username"
CONF_ALMATEL_PASSWORD = "almatel_password"
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USER = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_UPDATE_INTERVAL = "update_interval"

# Aliases for compatibility
CONF_ALMATEL_USERNAME = CONF_ALMATEL_LOGIN
CONF_MQTT_USERNAME = CONF_MQTT_USER

# Default values
DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_UPDATE_INTERVAL = 3600  # 1 час в секундах

# MQTT topics
MQTT_STATE_TOPIC = "custom_sensors/almatel/state"
MQTT_ATTR_TOPIC = "custom_sensors/almatel/attributes"
MQTT_CONFIG_TOPIC = "homeassistant/sensor/almatel/config"
MQTT_COMMAND_TOPIC = "custom_sensors/almatel/command"

# Service names
SERVICE_UPDATE = "update_balance"
SERVICE_UPDATE_BALANCE = SERVICE_UPDATE  # Alias

# Sensor attributes
ATTR_DUE_DATE = "due_date"
ATTR_DAYS_LEFT = "days_left"
ATTR_MESSAGE = "message"
ATTR_LAST_UPDATE = "last_update"
