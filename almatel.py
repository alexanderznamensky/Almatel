# almatel.py
# v6 - 2026-01-14
# Universal AppDaemon + CLI runner for Almatel balance checker
# - Works as AppDaemon app class: Almatel(hass.Hass)
# - Works as CLI script: python almatel.py --config ... --once/--loop
#
# Key points:
# - update_interval is stored in MINUTES (default 60), converted to seconds only for scheduling/sleep.
# - MQTT Discovery is published so Home Assistant creates exactly one entity: sensor.almatelad
#   with attributes: due_date, days_left, message

from __future__ import annotations

import platform
import os
import subprocess
import argparse
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

def extract_date(input_str):
    match = re.search(r'\d{2}\.\d{2}\.\d{4}', input_str)
    return match.group(0) if match else None

def day(num):
    last_two = num % 100
    last_digit = num % 10

    if last_two in range(11, 20) or last_digit == 0 or last_digit >= 5:
        return "дней"
    elif last_digit == 1:
        return "день"
    else:
        return "дня"

def time_to_pay(due_date: str):
    due = datetime.strptime(due_date, "%d.%m.%Y")

    target = int(due.timestamp() + 10800)
    now = int(time.time())

    num_days = (target - now) // 86400 + 1
    days = day(num_days)

    if num_days == 0:
        msg = "Сегодня срок оплаты Almatel!"
    elif 0 < num_days <= 5:
        msg = f"Через {num_days} {days} нужно оплатить Almatel!"
    elif num_days < 0:
        msg = "Просрочена оплата Almatel!!!"
    else:
        msg = f"Все в порядке!\nОплачивать Almatel нужно через {num_days} {days}."
    return msg, num_days


# ----------------------------
# AppDaemon optional import
# ----------------------------
try:
    import appdaemon.plugins.hass.hassapi as hass
    HAVE_APPDAEMON = True
except Exception:
    HAVE_APPDAEMON = False

    class _BaseStub:
        def log(self, msg):
            print(f"[LOG] {msg}")

        def error(self, msg):
            print(f"[ERROR] {msg}")

        def run_every(self, *args, **kwargs):
            pass

        def run_in(self, *args, **kwargs):
            pass

        def listen_event(self, *args, **kwargs):
            pass

    class _HassModuleStub:
        Hass = _BaseStub

    hass = _HassModuleStub()

# ----------------------------
# Optional deps
# ----------------------------
try:
    import paho.mqtt.client as mqtt
except Exception:
    mqtt = None

# ----------------------------
# Selenium imports
# ----------------------------
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    HAVE_SELENIUM = True
except Exception:
    HAVE_SELENIUM = False
    webdriver = None
    Options = None
    Service = None

# ----------------------------
# Config models
# ----------------------------
@dataclass
class SeleniumConfig:
    chromedriver_path: str | None = None
    headless: bool = True
    timeout: int = 20

@dataclass
class AlmatelConfig:
    almatel_login: str
    almatel_password: str

    mqtt_host: str
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_pass: str = ""

    update_interval: int = 60
    selenium: SeleniumConfig = field(default_factory=SeleniumConfig)


class AlmatelCore:
    """All logic that can run both in AppDaemon and CLI."""
    url = "https://almatel.ru/lk/login.php"

    mqtt_state_topic = "custom_sensors/almatel/state"
    mqtt_attr_topic = "custom_sensors/almatel/attributes"

    mqtt_discovery_prefix = "homeassistant"
    mqtt_node_id = "almatel"
    mqtt_object_id = "almatelad"

    def __init__(self, logger=None, error_logger=None):
        self._logger = logger
        self._error_logger = error_logger

    def _log(self, msg: str) -> None:
        if callable(self._logger):
            self._logger(msg)
        else:
            print(msg)

    def _err(self, msg: str) -> None:
        if callable(self._error_logger):
            self._error_logger(msg)
        elif callable(self._logger):
            self._logger(f"ERROR: {msg}")
        else:
            print(f"ERROR: {msg}")

    def log(self, msg: str) -> None:
        self._log(msg)

    def error(self, msg: str) -> None:
        self._err(msg)

    # ----------------------------
    # Config
    # ----------------------------
    def load_config(self, config_path: str = "/homeassistant/almatel_config.json") -> bool:
        config_file = Path(config_path)

        if not config_file.exists():
            self._err(f"Config file not found: {config_file}")
            self._err(f"You need to make a copy of the file from the Home Assiststant directory:")
            self._err(f"/config/almatel_config.json and place the file next to almatel.py")
            return False

        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception as e:
            self._err(f"Failed to parse config: {e}")
            return False

        sel = data.get("selenium", {}) or {}

        update_interval_minutes = int(data.get("update_interval", 60))

        if update_interval_minutes >= 3600:
            self._log(f"Warning: update_interval={update_interval_minutes} looks like seconds, converting to minutes")
            update_interval_minutes = update_interval_minutes // 60

        self.cfg = AlmatelConfig(
            almatel_login=data["almatel"]["login"],
            almatel_password=data["almatel"]["password"],
            mqtt_host=data["mqtt"]["host"],
            mqtt_port=int(data["mqtt"].get("port", 1883)),
            mqtt_user=data["mqtt"].get("user", ""),
            mqtt_pass=data["mqtt"].get("password", ""),
            update_interval=update_interval_minutes,
            selenium=SeleniumConfig(
                chromedriver_path=sel.get("chromedriver_path"),
                headless=bool(sel.get("headless", True)),
                timeout=int(sel.get("timeout", 20)),
            ),
        )
        return True

    # ----------------------------
    # MQTT
    # ----------------------------
    def _mqtt_connect(self):
        if mqtt is None:
            raise RuntimeError("paho-mqtt is not installed")

        assert self.cfg is not None, "Config is not loaded"

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        if self.cfg.mqtt_user:
            client.username_pw_set(self.cfg.mqtt_user, self.cfg.mqtt_pass)
        client.connect(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=60)
        return client

    def _discovery_topic(self) -> str:
        return f"{self.mqtt_discovery_prefix}/sensor/{self.mqtt_node_id}/{self.mqtt_object_id}/config"

    def publish_discovery(self):
        payload = {
            "name": "Almatel Баланс",
            "object_id": self.mqtt_object_id,
            "unique_id": f"{self.mqtt_node_id}_{self.mqtt_object_id}",
            "state_topic": self.mqtt_state_topic,
            "json_attributes_topic": self.mqtt_attr_topic,
            "unit_of_measurement": "RUB",
            "icon": "mdi:cash",
            "state_class": "measurement",
            "value_template": "{{ value }}",
            "availability_topic": "custom_sensors/almatel/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": {
                "identifiers": ["almatel"],
                "name": "Almatel Личный Кабинет",
                "manufacturer": "Almatel",
                "model": "Balance WebChecker v2"
            }
        }

        client = self._mqtt_connect()
        client.publish(self._discovery_topic(), json.dumps(payload, ensure_ascii=False), retain=True)
        client.publish("custom_sensors/almatel/availability", "online", retain=True)
        client.disconnect()

    def publish_state(self, state: str, attrs: dict):
        client = self._mqtt_connect()
        client.publish(self.mqtt_state_topic, state, retain=True)
        client.publish(self.mqtt_attr_topic, json.dumps(attrs, ensure_ascii=False), retain=True)
        client.publish("custom_sensors/almatel/availability", "online", retain=True)
        client.disconnect()

    # ----------------------------
    # Selenium parsing logic
    # ----------------------------
    def _fetch_balance_data(self) -> dict[str, Any]:
        if not HAVE_SELENIUM:
            self._err("Selenium is not installed, returning dummy data")
            return {"balance": "0", "due_date": None, "days_left": None, "message": "Selenium не установлен"}

        assert self.cfg is not None

        def one_attempt() -> dict[str, Any]:
            options = Options()

            if self.cfg.selenium.headless:
                options.add_argument("--headless=new")

            if platform.system().lower() == "linux":
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")

                for b in ("/usr/bin/chromium-browser", "/usr/bin/chromium"):
                    if os.path.exists(b):
                        try:
                            options.binary_location = b
                        except Exception:
                            pass
                        break

            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-background-timer-throttling")
            options.add_argument("--disable-backgrounding-occluded-windows")
            options.add_argument("--disable-renderer-backgrounding")
            options.add_argument("--disable-features=Translate,BackForwardCache")

            driver = None
            devnull_handle = None

            try:
                driver_path = (self.cfg.selenium.chromedriver_path or "").strip()

                if not driver_path and platform.system().lower() == "linux":
                    default_driver = "/usr/lib/chromium/chromedriver"
                    if os.path.exists(default_driver):
                        driver_path = default_driver

                if driver_path:
                    if not os.path.exists(driver_path):
                        raise RuntimeError(f"chromedriver not found at: {driver_path}")
                    service = Service(executable_path=driver_path)
                else:
                    service = Service()

                try:
                    service.log_output = subprocess.DEVNULL
                except Exception:
                    try:
                        devnull_handle = open(os.devnull, "w")
                        service.log_output = devnull_handle
                    except Exception:
                        pass

                driver = webdriver.Chrome(service=service, options=options)

                try:
                    driver.set_page_load_timeout(max(60, self.cfg.selenium.timeout))
                except Exception:
                    pass
                try:
                    driver.set_script_timeout(max(60, self.cfg.selenium.timeout))
                except Exception:
                    pass

                wait = WebDriverWait(driver, max(60, self.cfg.selenium.timeout))

                driver.get(self.url)

                login_field = wait.until(EC.visibility_of_element_located((By.NAME, "login")))
                password_field = wait.until(EC.visibility_of_element_located((By.NAME, "password")))

                login_field.clear()
                login_field.send_keys(self.cfg.almatel_login)
                password_field.clear()
                password_field.send_keys(self.cfg.almatel_password)

                login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
                login_button.click()

                # Баланс
                balance_el = wait.until(
                    EC.visibility_of_element_located(
                        (By.XPATH, "//*[@id='profile-info']/div[3]/div/div[1]/div[1]/div/div[2]/div[2]/div[2]")
                    )
                )
                balance_raw = balance_el.text or "0"
                value_str = balance_raw.replace(" ", "").replace("₽", "").replace(",", ".")
                balance = "{:.2f}".format(float(value_str))

                # Дата оплаты
                due_el = wait.until(
                    EC.visibility_of_element_located(
                        (By.XPATH, "//*[@id='profile-info']/div[3]/div/div[1]/div[1]/div/div[2]/div[2]/div[4]")
                    )
                )
                due_date_raw = due_el.text or ""
                due_date_2 = extract_date(due_date_raw)

                if "не определено" in due_date_raw.lower() or due_date_2 is None:
                    self._log("The deadline has not been set. Funds are insufficient.")
                    due_date = datetime.now().strftime("%d.%m.%Y")
                elif not re.match(r"^\d{2}\.\d{2}\.\d{4}$", due_date_2):
                    self._log("Invalid date format, using current")
                    due_date = datetime.now().strftime("%d.%m.%Y")
                else:
                    due_date = due_date_2

                msg, days_left = time_to_pay(due_date)

                return {"balance": balance, "due_date": due_date, "days_left": days_left, "message": msg}

            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                if devnull_handle:
                    try:
                        devnull_handle.close()
                    except Exception:
                        pass


        last_err = None
        for attempt in range(1, 4):
            try:
                return one_attempt()
            except Exception as e:
                last_err = e
                txt = str(e)
                self._err(f"Selenium attempt {attempt}/3 failed: {txt}")
                time.sleep(2 * attempt)

                continue

        return {"balance": "0", "due_date": None, "days_left": None, "message": f"Ошибка Selenium (3 попытки): {last_err}"}


    def run_check(self):
        assert self.cfg is not None

        data = self._fetch_balance_data()

        ok = (
            data.get("balance") not in (None, "")
            and data.get("due_date") is not None
        )

        if ok:
            self._last_good = data
        else:
            if self._last_good:
                data = dict(self._last_good)
                data["message"] = f"Не удалось обновить (использую прошлые данные). {data.get('message','')}"

        state = str(data.get("balance", "0"))
        attrs = {
            "due_date": data.get("due_date"),
            "days_left": data.get("days_left"),
            "message": data.get("message", ""),
        }

        self.publish_state(state, attrs)
        self.log(f"MQTT published: Almatel balance: {state}. Due date: {attrs['due_date']}. Days left: {attrs['days_left']}.")

# ----------------------------
# AppDaemon wrapper
# ----------------------------
class Almatel(hass.Hass):
    CONFIG_PATH = "/homeassistant/almatel_config.json"

    def initialize(self):
        self.core = AlmatelCore(logger=self.log, error_logger=self.error)

        if not self.core.load_config(self.CONFIG_PATH):
            self.log(f"Almatel disabled: config not found or invalid: {self.CONFIG_PATH}")
            return

        try:
            self.core.publish_discovery()
        except Exception as e:
            self.error(f"MQTT discovery error: {e}")
            return

        try:
            interval_seconds = max(60, int(self.core.cfg.update_interval) * 60)
        except Exception:
            interval_seconds = 3600

        self.run_every(self._run_every_cb, "now", interval_seconds)
        self.listen_event(self.manual_run, "call_service", domain="input_button", service="press", entity_id="input_button.manual_almatel_check")

    def _run_every_cb(self, kwargs):
        self.run_in(self._run_check_worker, 0)

    def _run_check_worker(self, kwargs):
        try:
            self.core.run_check()
        except Exception as e:
            self.error(f"Almatel run_check failed: {e}")

    def manual_run(self, event_name, data, kwargs):
        try:
            entity = data.get("service_data", {}).get("entity_id")
            if entity == "input_button.manual_almatel_check":
                self.log("Manual Almatel check triggered")
                self.run_in(self._run_check_worker, 0)
        except Exception as e:
            self.error(f"manual_run failed: {e}")

def manual_run(self, event_name, data, kwargs):
    try:
        entity = data.get("service_data", {}).get("entity_id")

        if entity == "input_button.manual_almatel_check" or (
            isinstance(entity, list) and "input_button.manual_almatel_check" in entity
        ):
            self.log("Manual Almatel check triggered")
            self.run_in(self._run_check_worker, 0)

    except Exception as e:
        self.error(f"manual_run failed: {e}")


# ----------------------------
# CLI runner
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Almatel checker (CLI mode)")
    parser.add_argument("--config", default="almatel_config.json", help="Path to config json")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--loop", action="store_true", help="Run forever with interval from config")
    parser.add_argument("--interval", type=int, default=None, help="Override interval (minutes) in loop mode")
    args = parser.parse_args()

    def _log(msg: str):
        print(msg)

    def _err(msg: str):
        print(f"[ERROR] {msg}")

    core = AlmatelCore(logger=_log, error_logger=_err)

    if not core.load_config(args.config):
        print(f"[ERROR] Config not found, exiting.")
        return 2

    try:
        core.publish_discovery()
    except Exception as e:
        _err(f"Failed to publish discovery: {e}")

    if args.once or (not args.loop):
        core.run_check()
        return 0

    interval_min = args.interval if args.interval is not None else int(core.cfg.update_interval)
    _log(f"Loop mode. Interval={interval_min} minutes ({interval_min * 60} seconds)")

    while True:
        try:
            core.run_check()
        except Exception as e:
            _err(f"run_check failed: {e}")
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    raise SystemExit(main())
