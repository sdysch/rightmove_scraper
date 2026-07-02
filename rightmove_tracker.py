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
    def __init__(
        self,
        prop_id: str,
        url: str,
        address: str,
        price: int,
        bedrooms: int = 0,
        property_type: str = '',
    ) -> None:
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


def _parse_results(soup: BeautifulSoup) -> dict[str, Property]:
    """Extract property cards from a parsed search page into property_id -> Property."""
    properties: dict[str, Property] = {}
    results = soup.find(id='l-searchResults')
    if not results:
        return properties
    for card in results.find_all('div', class_='propertyCard-details'):
        prop = _parse_card(card)
        if prop:
            properties[prop.id] = prop
    return properties


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

    properties = _parse_results(soup)
    pages = math.ceil(total / 24)

    for page in range(1, pages):
        url = f'{search_url}&index={page * 24}'
        resp = session.get(url)
        soup = BeautifulSoup(resp.content, 'html.parser')
        properties.update(_parse_results(soup))

    return properties


def _supabase_configured() -> bool:
    """Check whether Supabase credentials are present and valid."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return False
    if not SUPABASE_URL.startswith('https://'):
        logger.error('SUPABASE_URL must start with https:// (got %r)', SUPABASE_URL)
        return False
    return True


def _supabase_headers() -> dict[str, str]:
    """Build the authorization headers for Supabase REST API calls."""
    return {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
    }


def load_state() -> dict[str, dict[str, int]]:
    """Load previously seen property data from Supabase.

    Returns a dict mapping property_id to a dict with ``price`` and
    ``first_seen_price``.
    """
    if not _supabase_configured():
        return {}
    try:
        resp = requests.get(
            f'{SUPABASE_URL}/rest/v1/{STATE_TABLE}',
            headers=_supabase_headers(),
            params={'select': 'property_id,price,first_seen_price'},
        )
        resp.raise_for_status()
        return {
            row['property_id']: {
                'price': row['price'],
                'first_seen_price': row['first_seen_price'],
            }
            for row in resp.json()
        }
    except Exception as e:
        logger.error('Failed to load state: %s', e)
        return {}


def save_state(state: dict[str, dict[str, int]], properties: dict[str, Property]) -> None:
    """Upsert current property data and metadata to Supabase.

    *state* maps property_id to a dict with ``price`` and ``first_seen_price``.
    """
    if not _supabase_configured():
        logger.warning('Supabase not configured, skipping state save')
        return
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            'property_id': pid,
            'price': s['price'],
            'first_seen_price': s['first_seen_price'],
            'address': properties[pid].address,
            'url': properties[pid].url,
            'bedrooms': properties[pid].bedrooms,
            'property_type': properties[pid].property_type,
            'updated_at': now,
        }
        for pid, s in state.items()
    ]
    try:
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
    except Exception as e:
        logger.error('Failed to save state: %s', e)


def send_telegram_messages(token: str, chat_id: str, messages: list[str]) -> None:
    """Send a list of HTML-formatted messages via the Telegram bot API."""
    for msg in messages:
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception('Failed to send Telegram message')


def format_price(price: int) -> str:
    """Format an integer price as a pound-formatted string (e.g. 250000 -> \u00a3250,000)."""
    return f'\u00a3{price:,}'


def _prop_tag(prop: Property) -> str:
    """Return human-readable tag like '3 bed Semi-Detached'."""
    parts = []
    if prop.bedrooms:
        parts.append(f'{prop.bedrooms} bed')
    if prop.property_type:
        parts.append(prop.property_type)
    return f' \u2014 {" ".join(parts)}' if parts else ''


def _chunk_message(header: str, lines: list[str], max_len: int) -> list[str]:
    """Split lines into one or more messages under max_len, each prefixed with header."""
    chunks = []
    current = header

    for line in lines:
        candidate = current + line
        if len(candidate) > max_len and current != header:
            chunks.append(current)
            current = header + line
        elif len(candidate) > max_len:
            chunks.append(candidate)
            current = header
        else:
            current = candidate

    if current != header:
        chunks.append(current)

    return chunks


def _build_summary_messages(
    new_properties: list[Property],
    reduced_properties: list[tuple[Property, int]],
) -> list[str]:
    """Build summary notification messages, splitting if over Telegram's 4096 char limit."""
    messages = []
    max_len = 4096

    if new_properties:
        header = f'\U0001f195 <b>New Properties ({len(new_properties)})</b>'
        lines = [
            (f'\n\u2022 <b>{p.address}</b>{_prop_tag(p)}\n  {format_price(p.price)}\n  {p.url}')
            for p in new_properties
        ]
        messages.extend(_chunk_message(header, lines, max_len))

    if reduced_properties:
        header = f'\U0001f4b0 <b>Price Reductions ({len(reduced_properties)})</b>'
        lines = []
        for p, old_price in reduced_properties:
            drop = old_price - p.price
            lines.append(
                f'\n\u2022 <b>{p.address}</b>{_prop_tag(p)}\n'
                f'  {format_price(p.price)} (was {format_price(old_price)}, '
                f'down {format_price(drop)})\n'
                f'  {p.url}'
            )
        messages.extend(_chunk_message(header, lines, max_len))

    return messages


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
        logger.warning('No properties found \u2014 state preserved for next run')
        return

    is_first_run = not old_state
    new_properties: list[Property] = []
    reduced_properties: list[tuple[Property, int]] = []
    new_state: dict[str, dict[str, int]] = {}

    for prop_id, prop in current_properties.items():
        if prop_id in old_state:
            first_seen_price = old_state[prop_id]['first_seen_price']
        else:
            first_seen_price = prop.price

        new_state[prop_id] = {
            'price': prop.price,
            'first_seen_price': first_seen_price,
        }

        if prop_id not in old_state:
            new_properties.append(prop)
        elif old_state[prop_id]['price'] > prop.price:
            reduced_properties.append((prop, old_state[prop_id]['price']))

    messages = _build_summary_messages(new_properties, reduced_properties)
    date_str = datetime.now(timezone.utc).strftime('%d %b %Y')
    print(datetime.now(timezone.utc))
    print(datetime.now(timezone.utc).hour)
    is_last_run = datetime.now(timezone.utc).hour == 19

    if is_first_run:
        logger.info('First run \u2014 saving baseline state, no notifications sent')
    elif messages and telegram_token and telegram_chat_id:
        send_telegram_messages(telegram_token, telegram_chat_id, messages)
    elif is_last_run and telegram_token and telegram_chat_id:
        date_str = datetime.now(timezone.utc).strftime('%d %b %Y')
        logging.info('Sending end of day summary digest')
        send_telegram_messages(
            telegram_token,
            telegram_chat_id,
            [
                f'\U0001f4ca <b>Daily Digest \u2014 {date_str}</b>\n'
                f'No changes detected.\n'
                f'Total tracked: {len(current_properties)} properties'
            ],
        )

    save_state(new_state, current_properties)

    logger.info('Scraped %d properties, %d notifications', len(current_properties), len(messages))


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s',
    )
    main()
