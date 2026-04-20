from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGIN_URL,
)

_LOGGER = logging.getLogger(__name__)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_money(text: str) -> str | None:
    text = normalize(text).replace(",", ".")
    patterns = [
        r"([+-]?\d+\.\d{1,2})\s*(?:₽|руб\.?|р\.)",
        r"([+-]?\d+)\s*(?:₽|руб\.?|р\.)",
        r"([+-]?\d+\.\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def extract_ip(text: str) -> str | None:
    text = normalize(text)
    match = re.search(r"\b((?:\d{1,3}\.){3}\d{1,3})\b", text)
    if not match:
        return None

    ip = match.group(1)
    parts = ip.split(".")
    if all(0 <= int(part) <= 255 for part in parts):
        return ip

    return None


def collect_candidate_chunks(node: Tag) -> list[str]:
    chunks: list[str] = []

    current_text = normalize(node.get_text(" ", strip=True))
    if current_text:
        chunks.append(current_text)

    for sibling in list(node.next_siblings)[:8]:
        if isinstance(sibling, NavigableString):
            sibling_text = normalize(str(sibling))
        elif isinstance(sibling, Tag):
            sibling_text = normalize(sibling.get_text(" ", strip=True))
        else:
            sibling_text = ""

        if sibling_text:
            chunks.append(sibling_text)

    parent = node.parent
    for _ in range(5):
        if not parent or not isinstance(parent, Tag):
            break

        parent_text = normalize(parent.get_text(" ", strip=True))
        if parent_text:
            chunks.append(parent_text)

        parent = parent.parent

    return chunks


def find_balance(soup: BeautifulSoup) -> str | None:
    labels = [
        "Остаток на счете",
        "Остаток на счёте",
        "Баланс счета",
        "Баланс счёта",
    ]

    seen: set[str] = set()

    for text_node in soup.find_all(string=True):
        text_value = normalize(str(text_node))
        if not text_value:
            continue

        if any(label.lower() in text_value.lower() for label in labels):
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue

            for chunk in collect_candidate_chunks(parent):
                if chunk in seen:
                    continue
                seen.add(chunk)

                money = extract_money(chunk)
                if money:
                    return money

    return None


def find_contract_number(soup: BeautifulSoup) -> str | None:
    text = soup.get_text("\n", strip=True)
    match = re.search(r"Договор\s*№\s*(\d+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def find_period_and_paid_until(soup: BeautifulSoup) -> dict[str, str | None]:
    text = normalize(soup.get_text(" ", strip=True))

    result: dict[str, str | None] = {
        "period_start": None,
        "period_end": None,
        "paid_until": None,
    }

    period_match = re.search(
        r"Открыт\s+период\s+с\s+(\d{2}\.\d{2}\.\d{4})\s+по\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE,
    )
    if period_match:
        result["period_start"] = period_match.group(1)
        result["period_end"] = period_match.group(2)

    paid_until_match = re.search(
        r"Достаточно\s+средств\s+до\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE,
    )
    if paid_until_match:
        result["paid_until"] = paid_until_match.group(1)

    return result


def find_ip_address(soup: BeautifulSoup) -> str | None:
    labels = [
        "Ваш IP-адрес",
        "IP-адрес",
    ]

    seen: set[str] = set()

    for text_node in soup.find_all(string=True):
        text_value = normalize(str(text_node))
        if not text_value:
            continue

        if any(label.lower() in text_value.lower() for label in labels):
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue

            for chunk in collect_candidate_chunks(parent):
                if chunk in seen:
                    continue
                seen.add(chunk)

                ip = extract_ip(chunk)
                if ip:
                    return ip

    return None


def find_tariff_price(soup: BeautifulSoup) -> str | None:
    labels = [
        "Стоимость",
        "Стоимость тарифа",
        "Абонентская плата",
    ]

    seen: set[str] = set()

    for text_node in soup.find_all(string=True):
        text_value = normalize(str(text_node))
        if not text_value:
            continue

        if any(label.lower() == text_value.lower() or label.lower() in text_value.lower() for label in labels):
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue

            for chunk in collect_candidate_chunks(parent):
                if chunk in seen:
                    continue
                seen.add(chunk)

                if "р/мес" in chunk.lower() or "₽/мес" in chunk.lower() or "руб" in chunk.lower():
                    money = extract_money(chunk)
                    if money:
                        return money

    return None


def find_static_ip_price(soup: BeautifulSoup) -> str | None:
    labels = [
        "Статический Реальный IP",
        "Статический реальный IP",
        "Статический IP",
    ]

    seen: set[str] = set()

    for text_node in soup.find_all(string=True):
        text_value = normalize(str(text_node))
        if not text_value:
            continue

        if any(label.lower() in text_value.lower() for label in labels):
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue

            for chunk in collect_candidate_chunks(parent):
                if chunk in seen:
                    continue
                seen.add(chunk)

                if "р/мес" in chunk.lower() or "₽/мес" in chunk.lower():
                    money = extract_money(chunk)
                    if money:
                        return money

    return None


def parse_ru_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        return None


class AlmatelApiClient:
    def __init__(self, login: str, password: str) -> None:
        self._login = login
        self._password = password

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                ),
                "Referer": LOGIN_URL,
            }
        )
        return session

    def _fetch_sync(self) -> dict[str, Any]:
        with self._build_session() as session:
            response = session.get(LOGIN_URL, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            form = soup.find("form")
            if not form:
                raise RuntimeError("Login form not found")

            action = form.get("action") or LOGIN_URL
            post_url = urljoin(LOGIN_URL, action)

            payload = {
                "login": self._login,
                "password": self._password,
            }

            auth_response = session.post(
                post_url,
                data=payload,
                timeout=30,
                allow_redirects=True,
            )
            auth_response.raise_for_status()

            if "/lk/" not in auth_response.url:
                raise RuntimeError("Authentication failed")

            page = BeautifulSoup(auth_response.text, "html.parser")

            balance = find_balance(page)
            contract_number = find_contract_number(page)
            period_info = find_period_and_paid_until(page)
            ip_address = find_ip_address(page)
            tariff_price = find_tariff_price(page)
            static_ip_price = find_static_ip_price(page)

            paid_until = period_info["paid_until"]
            paid_until_date = parse_ru_date(paid_until)

            days_left = None
            message = None

            if paid_until_date:
                today = dt_util.now().date()
                days_left = (paid_until_date - today).days

                if days_left < 0:
                    message = f"Нужно оплатить Almatel. Просрочка {abs(days_left)} дн."
                elif days_left == 0:
                    message = "Нужно оплатить Almatel сегодня."
                else:
                    message = f"Все в порядке! Оплачивать Almatel нужно через {days_left} дн."

            result: dict[str, Any] = {
                "balance": float(balance) if balance is not None else None,
                "contract_number": contract_number,
                "period_start": period_info["period_start"],
                "period_end": period_info["period_end"],
                "paid_until": paid_until,
                "due_date": paid_until,
                "days_left": days_left,
                "message": message,
                "ip_address": ip_address,
                "tariff_price": float(tariff_price) if tariff_price is not None else None,
                "static_ip_price": float(static_ip_price) if static_ip_price is not None else None,
                "last_update": dt_util.now().isoformat(),
            }

            _LOGGER.debug("Fetched Almatel data: %s", result)
            return result

    async def async_fetch(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_sync)

    async def async_validate_login(self) -> None:
        data = await self.async_fetch()
        if data.get("balance") is None:
            raise RuntimeError("No balance returned")


class AlmatelDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.entry = entry

        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        self.client = AlmatelApiClient(
            entry.data[CONF_LOGIN],
            entry.data[CONF_PASSWORD],
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_fetch()
        except requests.HTTPError as err:
            if getattr(err.response, "status_code", None) in (401, 403):
                raise ConfigEntryAuthFailed("Authentication failed") from err
            raise UpdateFailed(f"HTTP error: {err}") from err
        except RuntimeError as err:
            if "Authentication failed" in str(err):
                raise ConfigEntryAuthFailed("Authentication failed") from err
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error: {err}") from err