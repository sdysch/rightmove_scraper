from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from rightmove_tracker import (
    BASE_URL,
    Property,
    _find_total_results,
    _parse_card,
    fetch_properties,
    format_price,
    load_state,
    save_state,
    send_telegram_messages,
)


class TestFormatPrice:
    def test_whole_thousands(self) -> None:
        assert format_price(250000) == '\u00a3250,000'

    def test_with_pence(self) -> None:
        assert format_price(250500) == '\u00a3250,500'

    def test_small_value(self) -> None:
        assert format_price(50000) == '\u00a350,000'

    def test_zero(self) -> None:
        assert format_price(0) == '\u00a30'

    def test_million(self) -> None:
        assert format_price(1_250_000) == '\u00a31,250,000'


class TestFindTotalResults:
    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, 'html.parser')

    def test_finds_count_in_div(self) -> None:
        html = '<div class="ResultsCount_resultsCount__Kqeah"><p><span>42</span> results</p></div>'
        assert _find_total_results(self._soup(html)) == 42

    def test_finds_count_without_space(self) -> None:
        html = '<div>21results</div>'
        assert _find_total_results(self._soup(html)) == 21

    def test_finds_count_with_commas(self) -> None:
        html = '<div><span>1,234</span> results</div>'
        assert _find_total_results(self._soup(html)) == 1234

    def test_returns_zero_when_no_match(self) -> None:
        html = '<div>no results here</div>'
        assert _find_total_results(self._soup(html)) == 0

    def test_ignores_non_matching_tags(self) -> None:
        html = '<script>42 results</script>'
        assert _find_total_results(self._soup(html)) == 0

    def test_singular_result(self) -> None:
        html = '<div>1 result</div>'
        assert _find_total_results(self._soup(html)) == 1


class TestParseCard:
    CARD_HTML = """
<div class="propertyCard-details">
  <a class="propertyCard-link" href="/properties/12345678#/?channel=RES_BUY"></a>
  <div data-testid="property-price">
    <div class="PropertyPrice_priceContainer___2Q7E">
      <div class="PropertyPrice_price__VL65t">£425,000</div>
    </div>
  </div>
  <div data-testid="property-address">
    <address class="PropertyAddress_address__LYRPq">123 Test Street, Testville</address>
  </div>
  <div data-testid="property-information">
    <span class="PropertyInformation_propertyType__u8e76">Semi-Detached</span>
    <div class="PropertyInformation_bedContainer___rN7d">3</div>
    <div class="PropertyInformation_bathContainer__ut8VY">1</div>
  </div>
</div>
"""

    def _card(self, html: str = CARD_HTML) -> BeautifulSoup:
        return BeautifulSoup(html, 'html.parser')

    def test_parses_full_card(self) -> None:
        soup = self._card()
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        prop = _parse_card(card)
        assert prop is not None
        assert prop.id == '12345678'
        assert prop.url == f'{BASE_URL}/properties/12345678#/?channel=RES_BUY'
        assert prop.address == '123 Test Street, Testville'
        assert prop.price == 425000
        assert prop.bedrooms == 3
        assert prop.property_type == 'Semi-Detached'

    def test_offers_over_price(self) -> None:
        html = """
<div class="propertyCard-details">
  <a class="propertyCard-link" href="/properties/87654321#/?channel=RES_BUY"></a>
  <div data-testid="property-price">
    <div>Offers Over £350,000</div>
  </div>
  <div data-testid="property-address">
    <address>456 Another Road</address>
  </div>
  <div data-testid="property-information">
    <span>Detached</span>
    <div>4</div>
  </div>
</div>
"""
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        prop = _parse_card(card)
        assert prop is not None
        assert prop.price == 350000

    def test_featured_with_prefixed_text(self) -> None:
        html = """
<div class="propertyCard-details">
  <a class="propertyCard-link" href="/properties/11111111#/?channel=RES_BUY"></a>
  <div data-testid="property-price">
    <a>FEATURED NEW HOME- MOVE IN THIS SUMMER£412,995</a>
  </div>
  <div data-testid="property-address">
    <address>Featured Road, Townsville</address>
  </div>
  <div data-testid="property-information">
    <span>Detached</span>
    <div>4</div>
  </div>
</div>
"""
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        prop = _parse_card(card)
        assert prop is not None
        assert prop.price == 412995

    def test_missing_link_returns_none(self) -> None:
        html = '<div class="propertyCard-details"><div>no link</div></div>'
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        assert _parse_card(card) is None

    def test_missing_price_returns_none(self) -> None:
        html = """
<div class="propertyCard-details">
  <a class="propertyCard-link" href="/properties/99999999#/"></a>
  <div data-testid="property-price">POA</div>
  <div data-testid="property-address"><address>Nowhere</address></div>
  <div data-testid="property-information"><span>Flat</span><div>1</div></div>
</div>
"""
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        assert _parse_card(card) is None

    def test_missing_bedrooms_defaults_to_zero(self) -> None:
        html = """
<div class="propertyCard-details">
  <a class="propertyCard-link" href="/properties/55555555#/"></a>
  <div data-testid="property-price">£200,000</div>
  <div data-testid="property-address"><address>Studio Flat Lane</address></div>
  <div data-testid="property-information">
    <span>Flat</span>
  </div>
</div>
"""
        soup = BeautifulSoup(html, 'html.parser')
        card = soup.find('div', class_='propertyCard-details')
        assert card is not None
        prop = _parse_card(card)
        assert prop is not None
        assert prop.bedrooms == 0
        assert prop.property_type == 'Flat'


class TestFetchProperties:
    @patch('rightmove_tracker.requests.Session')
    def test_single_page(self, mock_session: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.content = (
            '<html><body>'
            '<div class="ResultsCount_resultsCount__Kqeah"><p><span>1</span> result</p></div>'
            '<div id="l-searchResults">'
            '<div class="propertyCard-details">'
            '<a class="propertyCard-link" href="/properties/11111111#/"></a>'
            '<div data-testid="property-price">\u00a3300,000</div>'
            '<div data-testid="property-address"><address>One Property Road</address></div>'
            '<div data-testid="property-information"><span>Detached</span><div>3</div></div>'
            '</div></div></body></html>'
        ).encode()
        mock_session.return_value.get.return_value = mock_resp
        props = fetch_properties('https://rightmove.co.uk/search?foo=bar')
        assert len(props) == 1
        assert '11111111' in props
        assert props['11111111'].price == 300000

    @patch('rightmove_tracker.requests.Session')
    def test_no_results(self, mock_session: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.content = b'<html><body><div>0 results</div></body></html>'
        mock_session.return_value.get.return_value = mock_resp
        props = fetch_properties('https://rightmove.co.uk/search?foo=bar')
        assert props == {}

    @patch('rightmove_tracker.requests.Session')
    def test_no_count_element(self, mock_session: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.content = b'<html><body><div>nothing here</div></body></html>'
        mock_session.return_value.get.return_value = mock_resp
        props = fetch_properties('https://rightmove.co.uk/search?foo=bar')
        assert props == {}

    @patch('rightmove_tracker.requests.Session')
    def test_missing_results_section(self, mock_session: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.content = b"""
<html><body>
  <div class="ResultsCount_resultsCount__Kqeah"><p><span>5</span> results</p></div>
</body></html>
"""
        mock_session.return_value.get.return_value = mock_resp
        props = fetch_properties('https://rightmove.co.uk/search?foo=bar')
        assert props == {}


class TestLoadState:
    @patch('rightmove_tracker.requests.get')
    def test_returns_prices(self, mock_get: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {'property_id': '111', 'price': 250000, 'first_seen_price': 250000},
            {'property_id': '222', 'price': 300000, 'first_seen_price': 320000},
        ]
        mock_get.return_value = mock_resp
        with patch('rightmove_tracker.SUPABASE_URL', 'https://db.supabase.co'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                state = load_state()
        assert state == {
            '111': {'price': 250000, 'first_seen_price': 250000},
            '222': {'price': 300000, 'first_seen_price': 320000},
        }

    @patch('rightmove_tracker.requests.get')
    def test_http_error_returns_empty(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = Exception('Connection error')
        with patch('rightmove_tracker.SUPABASE_URL', 'https://db.supabase.co'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                state = load_state()
        assert state == {}

    def test_no_credentials_returns_empty(self) -> None:
        with patch('rightmove_tracker.SUPABASE_URL', ''):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', ''):
                state = load_state()
        assert state == {}

    def test_empty_credentials_returns_empty(self) -> None:
        with patch('rightmove_tracker.SUPABASE_URL', ''):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                state = load_state()
        assert state == {}

    def test_bad_url_scheme_returns_empty(self) -> None:
        with patch('rightmove_tracker.SUPABASE_URL', 'my_url'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                state = load_state()
        assert state == {}


class TestSaveState:
    def _make_props(self) -> dict[str, Property]:
        return {
            '111': Property('111', 'https://rm.co.uk/p/111', 'Addr 1', 250000, 3, 'Detached'),
            '222': Property('222', 'https://rm.co.uk/p/222', 'Addr 2', 300000, 4, 'Semi-Detached'),
        }

    @patch('rightmove_tracker.requests.post')
    def test_sends_rows(self, mock_post: MagicMock) -> None:
        mock_post.return_value.ok = True
        props = self._make_props()
        state = {
            '111': {'price': 250000, 'first_seen_price': 250000},
            '222': {'price': 300000, 'first_seen_price': 320000},
        }
        with patch('rightmove_tracker.SUPABASE_URL', 'https://db.supabase.co'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                save_state(state, props)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == 'https://db.supabase.co/rest/v1/property_state'
        rows = kwargs['json']
        assert len(rows) == 2
        assert rows[0]['property_id'] == '111'
        assert rows[0]['price'] == 250000
        assert rows[0]['first_seen_price'] == 250000
        assert rows[0]['address'] == 'Addr 1'
        assert rows[0]['bedrooms'] == 3
        assert rows[0]['property_type'] == 'Detached'
        assert 'updated_at' in rows[0]

    @patch('rightmove_tracker.requests.post')
    def test_logs_error_on_failure(
        self, mock_post: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = 'Internal Server Error'
        mock_post.return_value = mock_resp
        props = self._make_props()
        with patch('rightmove_tracker.SUPABASE_URL', 'https://db.supabase.co'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                save_state({'111': {'price': 250000, 'first_seen_price': 250000}}, props)
        assert 'Failed to save state' in caplog.text
        assert '500' in caplog.text

    def test_skips_when_not_configured(self, caplog: pytest.LogCaptureFixture) -> None:
        props = self._make_props()
        with patch('rightmove_tracker.SUPABASE_URL', ''):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', ''):
                save_state({'111': {'price': 250000, 'first_seen_price': 250000}}, props)
        assert 'Supabase not configured' in caplog.text

    @patch('rightmove_tracker.requests.post')
    def test_connection_error(self, mock_post: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        mock_post.side_effect = ConnectionError('DNS resolution failed')
        props = self._make_props()
        with patch('rightmove_tracker.SUPABASE_URL', 'https://db.supabase.co'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                save_state({'111': {'price': 250000, 'first_seen_price': 250000}}, props)
        assert 'Failed to save state' in caplog.text
        assert 'DNS resolution failed' in caplog.text

    def test_bad_url_scheme_skips(self, caplog: pytest.LogCaptureFixture) -> None:
        props = self._make_props()
        with patch('rightmove_tracker.SUPABASE_URL', 'my_url'):
            with patch('rightmove_tracker.SUPABASE_SERVICE_KEY', 'test-key'):
                save_state({'111': {'price': 250000, 'first_seen_price': 250000}}, props)
        assert 'Supabase not configured' in caplog.text


class TestSendTelegramMessages:
    @patch('rightmove_tracker.requests.post')
    def test_sends_each_message(self, mock_post: MagicMock) -> None:
        send_telegram_messages('token123', 'chat456', ['msg1', 'msg2'])
        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            args, kwargs = call
            assert args[0] == 'https://api.telegram.org/bottoken123/sendMessage'
            assert kwargs['json']['chat_id'] == 'chat456'
            assert kwargs['json']['parse_mode'] == 'HTML'

    @patch('rightmove_tracker.requests.post')
    def test_sends_single_message(self, mock_post: MagicMock) -> None:
        send_telegram_messages('tok', 'cid', ['hello'])
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs['json']['text'] == 'hello'


class TestProperty:
    def test_defaults(self) -> None:
        p = Property('123', 'https://rm.co.uk/p/123', 'Addr', 250000)
        assert p.bedrooms == 0
        assert p.property_type == ''

    def test_all_fields(self) -> None:
        p = Property('123', 'https://rm.co.uk/p/123', 'Addr', 250000, 3, 'Detached')
        assert p.id == '123'
        assert p.price == 250000
        assert p.bedrooms == 3
        assert p.property_type == 'Detached'
