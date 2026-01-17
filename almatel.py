# almatel.py
# v8 - 2026-01-17
# Universal AppDaemon + CLI runner for Almatel balance checker
# - Works as AppDaemon app class: Almatel(hass.Hass)
# - Works as CLI script: python almatel.py --config ... --once/--loop

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
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

APP_LANG = os.getenv("APP_LANG", "ru")

def _is_windows() -> bool:
    return platform.system().lower().startswith("win")

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
    import appdaemon.plugins.hass.hassapi as hass # type: ignore
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
    from selenium.common.exceptions import TimeoutException
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
    timeout: int = 22
    hard_timeout: int = 25
    profile_dir: str | None = None
    disable_images: bool = True

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
        self._last_good: dict[str, Any] | None = None
        self._run_lock = threading.Lock()

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
                timeout=int(sel.get("timeout", 25)),
                hard_timeout=int(sel.get("hard_timeout", 30)),
                profile_dir=(sel.get("profile_dir") or None),
                disable_images=bool(sel.get("disable_images", True)),
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
    @staticmethod
    def _build_options(headless: bool, profile_dir: str | None = None, disable_images: bool = False) -> "Options": # type: ignore
        opts = Options()
        if headless:
            opts.add_argument("--headless=new")

        if profile_dir:
            opts.add_argument(f"--user-data-dir={profile_dir}")
        else:
            opts.add_argument("--incognito")
        try:
            opts.page_load_strategy = "eager"
        except Exception:
            pass

        opts.add_argument("--window-size=1366,968")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-background-networking")
        opts.add_argument("--disable-component-update")
        opts.add_argument("--disable-sync")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--metrics-recording-only")
        opts.add_argument("--safebrowsing-disable-auto-update")
        opts.add_argument("--disable-features=TranslateUI")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-features=IsolateOrigins,site-per-process")

        if disable_images:
            opts.add_argument("--blink-settings=imagesEnabled=false")

        if (APP_LANG or "").lower().startswith("en"):
            opts.add_argument("--lang=en-US")
            opts.add_argument("--accept-lang=en-US,en,ru-RU,ru")
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            )
        else:
            opts.add_argument("--lang=ru-RU")
            opts.add_argument("--accept-lang=ru-RU,ru,en-US,en")
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            )

        opts.add_argument(f"--user-agent={user_agent}")
        try:
            opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
            opts.add_experimental_option("useAutomationExtension", False)
        except Exception:
            pass

        return opts

    def _fetch_balance_data(self) -> dict[str, Any]:
        if not HAVE_SELENIUM:
            self._err("Selenium is not installed, returning dummy data")
            return {"balance": "0", "due_date": None, "days_left": None, "message": "Selenium не установлен"}

        assert self.cfg is not None

        def _timeout_guard(seconds: int):
            if platform.system().lower() != "linux":
                return None
            if threading.current_thread() is not threading.main_thread():
                return None
            try:
                import signal

                def _raise(_signum, _frame):
                    raise TimeoutError(f"Selenium hard timeout after {seconds}s")

                signal.signal(signal.SIGALRM, _raise)
                signal.alarm(max(1, int(seconds)))
                return signal
            except Exception:
                return None

        def one_attempt() -> dict[str, Any]:
            attempt_start = time.monotonic()
            headless = bool(self.cfg.selenium.headless)
            if _is_windows():
                headless = False
            profile_dir = self.cfg.selenium.profile_dir
            if not profile_dir and platform.system().lower() == "linux":
                profile_dir = "/homeassistant/.almatel_chrome_profile"

            if profile_dir:
                try:
                    os.makedirs(profile_dir, exist_ok=True)
                except Exception:
                    profile_dir = None

            disable_images = bool(self.cfg.selenium.disable_images)

            options = self._build_options(headless=headless, profile_dir=profile_dir, disable_images=disable_images)

            if platform.system().lower() == "linux":
                for b in ("/usr/bin/chromium-browser", "/usr/bin/chromium"):
                    if os.path.exists(b):
                        try:
                            options.binary_location = b
                        except Exception:
                            pass
                        break

            driver = None
            devnull_handle = None
            guard = None

            try:
                guard = _timeout_guard(int(self.cfg.selenium.hard_timeout))

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
                    driver.set_page_load_timeout(int(self.cfg.selenium.timeout))
                except Exception:
                    pass
                try:
                    driver.set_script_timeout(int(self.cfg.selenium.timeout))
                except Exception:
                    pass

                wait = WebDriverWait(driver, int(self.cfg.selenium.timeout))

                driver.get(self.url)

                try:
                    quick_wait = WebDriverWait(driver, min(5, int(self.cfg.selenium.timeout)))
                    login_field = quick_wait.until(EC.visibility_of_element_located((By.NAME, "login")))
                    password_field = quick_wait.until(EC.visibility_of_element_located((By.NAME, "password")))

                    login_field.clear()
                    login_field.send_keys(self.cfg.almatel_login)
                    password_field.clear()
                    password_field.send_keys(self.cfg.almatel_password)

                    login_button = quick_wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
                    login_button.click()
                except TimeoutException:
                    self._log("Login form not found quickly — assuming session is already authenticated")

                balance_el = wait.until(
                    EC.visibility_of_element_located(
                        (By.XPATH, "//*[@id='profile-info']/div[3]/div/div[1]/div[1]/div/div[2]/div[2]/div[2]")
                    )
                )
                balance_raw = balance_el.text or "0"
                value_str = balance_raw.replace(" ", "").replace("₽", "").replace(",", ".")
                balance = "{:.2f}".format(float(value_str))

                due_el = wait.until(
                    EC.visibility_of_element_located(
                        (By.XPATH, "//*[@id='profile-info']/div[3]/div/div[1]/div[1]/div/div[2]/div[2]/div[4]")
                    )
                )
                due_date_raw = due_el.text or ""
                due_date_2 = extract_date(due_date_raw)

                if "не определено" in due_date_raw.lower() or due_date_2 is None:
                    due_date = datetime.now().strftime("%d.%m.%Y")
                elif not re.match(r"^\d{2}\.\d{2}\.\d{4}$", due_date_2):
                    due_date = datetime.now().strftime("%d.%m.%Y")
                else:
                    due_date = due_date_2

                msg, days_left = time_to_pay(due_date)

                result = {"balance": balance, "due_date": due_date, "days_left": days_left, "message": msg}
                return result

            finally:
                attempt_time = time.monotonic() - attempt_start
                self._log(f"Selenium attempt finished in {attempt_time:.2f}s")
                try:
                    if guard is not None:
                        guard.alarm(0)
                except Exception:
                    pass

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

        if not self._run_lock.acquire(blocking=False):
            self._err("Previous Almatel selenium run is still in progress, skipping this cycle")
            return {
                "balance": None,
                "due_date": None,
                "days_left": None,
                "message": "Пропуск: предыдущая проверка ещё выполняется",
            }

        try:
            last_err = None
            for attempt in range(1, 3):
                try:
                    return one_attempt()
                except Exception as e:
                    last_err = e
                    txt = str(e)
                    self._err(f"Selenium attempt {attempt}/2 failed: {txt}")
                    time.sleep(2 * attempt)
                    continue

            return {
                "balance": "0",
                "due_date": None,
                "days_left": None,
                "message": f"Ошибка Selenium (2 попытки): {last_err}",
            }
        finally:
            try:
                self._run_lock.release()
            except Exception:
                pass

    def run_check(self):
        assert self.cfg is not None
        start_ts = time.monotonic()
        data = self._fetch_balance_data()
        total_time = time.monotonic() - start_ts
        self.log(f"Almatel check finished in {total_time:.2f}s")
        ok = (data.get("balance") not in (None, "") and data.get("due_date") is not None)
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
        self._ad_run_lock = threading.Lock()

        self._timer_handle = None
        self._watch_handle = None
        self._last_interval_seconds = None
        self._config_mtime = None

        if not self.core.load_config(self.CONFIG_PATH):
            self.log(f"Almatel disabled: config not found or invalid: {self.CONFIG_PATH}")
            return

        self._config_mtime = self._get_config_mtime()

        try:
            self.core.publish_discovery()
        except Exception as e:
            self.error(f"MQTT discovery error: {e}")
            return

        self._schedule_from_config(initial=True)

        self._watch_handle = self.run_every(self._watch_config_cb, "now", 15)

        self.listen_event(
            self.manual_run,
            "call_service",
            domain="input_button",
            service="press",
            entity_id="input_button.manual_almatel_check",
        )

    def _get_config_mtime(self):
        try:
            return Path(self.CONFIG_PATH).stat().st_mtime
        except Exception:
            return None

    def _schedule_from_config(self, initial: bool = False) -> None:
        try:
            interval_seconds = max(60, int(self.core.cfg.update_interval) * 60)
        except Exception:
            interval_seconds = 3600

        if self._last_interval_seconds == interval_seconds and not initial:
            return

        if self._timer_handle is not None:
            try:
                self.cancel_timer(self._timer_handle)
            except Exception:
                pass

        self._timer_handle = self.run_every(self._run_every_cb, "now", interval_seconds)
        self._last_interval_seconds = interval_seconds

        self.log(f"Almatel scheduled every {interval_seconds // 60} min")

    def _watch_config_cb(self, kwargs):
        """Reload config if file changed and reschedule timer if interval changed."""
        try:
            mtime = self._get_config_mtime()
            if mtime is None:
                return

            if self._config_mtime is None:
                self._config_mtime = mtime
                return

            if mtime != self._config_mtime:
                self._config_mtime = mtime

                if not self.core.load_config(self.CONFIG_PATH):
                    self.error("Config changed but failed to reload (keeping previous schedule)")
                    return

                self._schedule_from_config()

        except Exception as e:
            self.error(f"_watch_config_cb failed: {e}")

    def _run_every_cb(self, kwargs):
        self.run_in(self._run_check_worker, 0)

    def _run_check_worker(self, kwargs):
        if not self._ad_run_lock.acquire(blocking=False):
            self.log("Skipping Almatel check: previous worker is still running")
            return
        try:
            self.core.run_check()
        except Exception as e:
            self.error(f"Almatel run_check failed: {e}")
        finally:
            try:
                self._ad_run_lock.release()
            except Exception:
                pass

    def manual_run(self, event_name, data, kwargs):
        try:
            entity = data.get("service_data", {}).get("entity_id")
            if entity == "input_button.manual_almatel_check":
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
