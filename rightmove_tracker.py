import logging
import math
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL = 'https://www.rightmove.co.uk'
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
STATE_TABLE = 'property_state'


class Property:
    def __init__(self, prop_id: str, url: str, address: str, price: int,
                 bedrooms: int = 0, property_type: str = '') -> None:
        """A single property listing scraped from Rightmove."""
        self.id = prop_id
        self.url = url
        self.address = address
        self.price = price
        self.bedrooms = bedrooms
        self.property_type = property_type


def _find_total_results(soup: BeautifulSoup) -> int:
    """Extract the total number of matching properties from the search page."""
    for el in soup.find_all(['div', 'span', 'p', 'h1', 'h2', 'h3']):
        text = el.get_text(strip=True)
        m = re.match(r'^(\d[\d,]*)\s*results?$', text, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(',', ''))
    return 0


def _parse_card(card: Tag) -> Property | None:
    """Parse a single property card HTML element into a Property object."""
    try:
        link_el = card.find('a', class_='propertyCard-link')
        if not link_el:
            return None
        href = link_el['href']
        full_url = BASE_URL + href if href.startswith('/') else href
        id_match = re.search(r'/properties/(\d+)', href)
        if not id_match:
            return None
        prop_id = id_match.group(1)

        price_el = card.find(lambda tag: tag.get('data-testid') == 'property-price')
        price_text = price_el.get_text(strip=True) if price_el else ''
        price_match = re.search(r'\u00a3([\d,]+)', price_text)
        if not price_match:
            return None
        price = int(price_match.group(1).replace(',', ''))

        addr_el = card.find(lambda tag: tag.get('data-testid') == 'property-address')
        address = addr_el.get_text(strip=True) if addr_el else ''

        bedrooms = 0
        property_type = ''
        info_el = card.find(lambda tag: tag.get('data-testid') == 'property-information')
        if info_el:
            for child in info_el.find_all(recursive=False):
                classes = ' '.join(child.get('class', []))
                text = child.get_text(strip=True)
                if child.name == 'span':
                    property_type = text
                elif 'bed' in classes.lower():
                    try:
                        bedrooms = int(text)
                    except ValueError:
                        pass

        return Property(prop_id, full_url, address, price, bedrooms, property_type)
    except Exception:
        return None


def fetch_properties(search_url: str) -> dict[str, Property]:
    """Scrape all pages of a Rightmove search and return property_id -> Property."""
    session = requests.Session()
    session.headers['User-Agent'] = (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    resp = session.get(search_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, 'html.parser')

    total = _find_total_results(soup)
    if total == 0:
        return {}

    pages = math.ceil(total / 24)
    properties: dict[str, Property] = {}

    for page in range(pages):
        url = f'{search_url}&index={page * 24}'
        resp = session.get(url)
        soup = BeautifulSoup(resp.content, 'html.parser')
        results = soup.find(id='l-searchResults')
        if not results:
            continue
        cards = results.find_all('div', class_='propertyCard-details')
        for card in cards:
            prop = _parse_card(card)
            if prop:
                properties[prop.id] = prop

    return properties


def _supabase_headers() -> dict[str, str]:
    """Build the authorization headers for Supabase REST API calls."""
    return {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
    }


def load_state() -> dict[str, int]:
    """Load previously seen property prices from Supabase."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {}
    try:
        resp = requests.get(
            f'{SUPABASE_URL}/rest/v1/{STATE_TABLE}',
            headers=_supabase_headers(),
            params={'select': 'property_id,price'},
        )
        resp.raise_for_status()
        return {row['property_id']: row['price'] for row in resp.json()}
    except Exception as e:
        logger.error('Failed to load state: %s', e)
        return {}


def save_state(state: dict[str, int], properties: dict[str, Property]) -> None:
    """Upsert current property prices and metadata to Supabase."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.warning('Supabase not configured, skipping state save')
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            'property_id': pid,
            'price': price,
            'address': properties[pid].address,
            'url': properties[pid].url,
            'bedrooms': properties[pid].bedrooms,
            'property_type': properties[pid].property_type,
            'updated_at': now,
        }
        for pid, price in state.items()
    ]
    resp = requests.post(
        f'{SUPABASE_URL}/rest/v1/{STATE_TABLE}',
        json=rows,
        headers={
            **_supabase_headers(),
            'Content-Type': 'application/json',
            'Prefer': 'resolution=merge-duplicates',
        },
    )
    if not resp.ok:
        logger.error('Failed to save state: %s %s', resp.status_code, resp.text)


def send_telegram_messages(token: str, chat_id: str, messages: list[str]) -> None:
    """Send a list of HTML-formatted messages via the Telegram bot API."""
    for msg in messages:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'},
        )


def format_price(price: int) -> str:
    """Format an integer price as a pound-formatted string (e.g. 250000 -> \u00a3250,000)."""
    return f'\u00a3{price:,}'


def main() -> None:
    """Entry point: load state, scrape Rightmove, compare, notify, save."""
    search_url = os.environ.get('SEARCH_URL')
    telegram_token = os.environ.get('TELEGRAM_TOKEN')
    telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not search_url:
        logger.error('SEARCH_URL environment variable not set')
        return

    old_state = load_state()
    current_properties = fetch_properties(search_url)

    if not current_properties:
        logger.warning('No properties found — state preserved for next run')
        return

    is_first_run = not old_state
    messages: list[str] = []
    new_state: dict[str, int] = {}

    for prop_id, prop in current_properties.items():
        new_state[prop_id] = prop.price

        summary_parts = []
        if prop.bedrooms:
            summary_parts.append(f'{prop.bedrooms} bed')
        if prop.property_type:
            summary_parts.append(prop.property_type)
        summary = f' — {" ".join(summary_parts)}' if summary_parts else ''

        if prop_id not in old_state:
            messages.append(
                f'\U0001f195 <b>New Property</b>\n'
                f'{prop.address}{summary}\n'
                f'{format_price(prop.price)}\n'
                f'{prop.url}'
            )
        elif old_state[prop_id] > prop.price:
            drop = old_state[prop_id] - prop.price
            messages.append(
                f'\U0001f4b0 <b>Price Reduced</b>\n'
                f'{prop.address}{summary}\n'
                f'{format_price(prop.price)} (was {format_price(old_state[prop_id])}, '
                f'down {format_price(drop)})\n'
                f'{prop.url}'
            )

    if is_first_run:
        logger.info('First run — saving baseline state, no notifications sent')
    elif messages and telegram_token and telegram_chat_id:
        send_telegram_messages(telegram_token, telegram_chat_id, messages)

    save_state(new_state, current_properties)

    logger.info('Scraped %d properties, %d notifications',
                len(current_properties), len(messages))


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s',
    )
    main()
