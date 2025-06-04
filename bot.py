import os
import time
import json
import logging
from typing import List
import requests

try:
    import openai
except ImportError:
    openai = None


logging.basicConfig(level=logging.INFO)

DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

POSTED_DEALS_FILE = os.getenv('POSTED_DEALS_FILE', 'posted_deals.json')
RESET_CACHE_ON_STARTUP = os.getenv('RESET_CACHE_ON_STARTUP', 'false').lower() in ('1', 'true', 'yes')
CACHE_RESET_HOURS = float(os.getenv('CACHE_RESET_HOURS', '0'))

def load_cache() -> dict:
    if not os.path.exists(POSTED_DEALS_FILE):
        return {'Steam': set(), 'Epic': set()}
    try:
        with open(POSTED_DEALS_FILE, 'r') as f:
            data = json.load(f)
        return {
            'Steam': set(str(x) for x in data.get('Steam', [])),
            'Epic': set(str(x) for x in data.get('Epic', []))
        }
    except Exception as e:
        logging.error('Failed to load deal cache: %s', e)
        return {'Steam': set(), 'Epic': set()}


def save_cache(cache: dict):
    try:
        with open(POSTED_DEALS_FILE, 'w') as f:
            json.dump({'Steam': list(cache['Steam']), 'Epic': list(cache['Epic'])}, f)
    except Exception as e:
        logging.error('Failed to save deal cache: %s', e)


def reset_cache() -> dict:
    cache = {'Steam': set(), 'Epic': set()}
    save_cache(cache)
    logging.info('Deal cache has been reset')
    return cache


POSTED_DEALS = load_cache()
if RESET_CACHE_ON_STARTUP:
    POSTED_DEALS = reset_cache()

STEAM_SPECIALS_URL = 'https://store.steampowered.com/api/featuredcategories'
STEAM_APPDETAILS_URL = 'https://store.steampowered.com/api/appdetails'
STEAM_APPREVIEWS_URL = 'https://store.steampowered.com/appreviews/{app_id}?json=1&language=all&purchase_type=all'

EPIC_DEALS_URL = 'https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US'


def summarize_text(text: str) -> str:
    """Generate a short summary for the given text."""
    if OPENAI_API_KEY and openai:
        openai.api_key = OPENAI_API_KEY
        try:
            resp = openai.ChatCompletion.create(
                model='gpt-3.5-turbo',
                messages=[
                    {
                        'role': 'system',
                        'content': 'You are a helpful assistant that summarizes video games.'
                    },
                    {
                        'role': 'user',
                        'content': f'Summarize this game description in two sentences: {text}'
                    }
                ],
                temperature=0.7,
                max_tokens=100,
            )
            return resp['choices'][0]['message']['content'].strip()
        except Exception as e:
            logging.error('OpenAI API failed: %s', e)
    # Fallback: simple first sentence summary
    sentences = text.replace('\n', ' ').split('.')
    return '. '.join(sentences[:2]).strip() + '.'


def post_to_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        logging.warning('DISCORD_WEBHOOK_URL not set; skipping Discord notification.')
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={'content': message})
        if resp.status_code >= 300:
            logging.error('Failed to post to Discord: %s %s', resp.status_code, resp.text)
    except Exception as e:
        logging.error('Error posting to Discord: %s', e)


def fetch_steam_deals() -> List[dict]:
    logging.info('Fetching Steam specials')
    deals = []
    try:
        resp = requests.get(STEAM_SPECIALS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('specials', {}).get('items', [])
        for item in items:
            if item.get('discount_percent', 0) >= 50 or item.get('final_price', 1) == 0:
                deals.append({
                    'store': 'Steam',
                    'id': item.get('id'),
                    'name': item.get('name'),
                    'discount_percent': item.get('discount_percent'),
                    'final_price': item.get('final_price', 0) / 100.0,
                    'currency': item.get('currency', 'USD'),
                })
    except requests.HTTPError as e:
        logging.error('HTTP error fetching Steam deals: %s', e)
    except Exception as e:
        logging.error('Failed to fetch Steam deals: %s', e)
    return deals


def fetch_steam_details(app_id: int) -> dict:
    try:
        params = {'appids': app_id, 'l': 'en'}
        resp = requests.get(STEAM_APPDETAILS_URL, params=params, timeout=30)
        resp.raise_for_status()
        detail = resp.json()
        data = detail[str(app_id)]['data']
        description = data.get('short_description') or ''
    except requests.HTTPError as e:
        logging.error('HTTP error fetching details for %s: %s', app_id, e)
        description = ''
    except Exception as e:
        logging.error('Failed to fetch details for %s: %s', app_id, e)
        description = ''
    try:
        resp = requests.get(STEAM_APPREVIEWS_URL.format(app_id=app_id), timeout=30)
        resp.raise_for_status()
        reviews = resp.json()
        rating = reviews.get('query_summary', {}).get('review_score_desc', 'Unknown')
    except requests.HTTPError as e:
        logging.error('HTTP error fetching reviews for %s: %s', app_id, e)
        rating = 'Unknown'
    except Exception as e:
        logging.error('Failed to fetch reviews for %s: %s', app_id, e)
        rating = 'Unknown'
    return {'description': description, 'rating': rating}


def fetch_epic_deals() -> List[dict]:
    logging.info('Fetching Epic Games deals')
    deals = []
    try:
        resp = requests.get(EPIC_DEALS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        elements = data.get('data', {}).get('Catalog', {}).get('searchStore', {}).get('elements', [])
        for el in elements:
            price_info = el.get('price', {}).get('totalPrice', {})
            original = price_info.get('originalPrice', 0)
            discount = price_info.get('discountPrice', original)
            if original and (discount / original) <= 0.5 or discount == 0:
                deals.append({
                    'store': 'Epic',
                    'id': el.get('id'),
                    'name': el.get('title'),
                    'discount_percent': int(100 - (discount * 100 // original)) if original else 100,
                    'final_price': discount / 100.0,
                    'currency': price_info.get('currencyCode', 'USD'),
                    'description': el.get('description', '')
                })
    except requests.HTTPError as e:
        logging.error('HTTP error fetching Epic deals: %s', e)
    except Exception as e:
        logging.error('Failed to fetch Epic deals: %s', e)
    return deals


def process_steam_deals():
    for deal in fetch_steam_deals():
        deal_id = str(deal['id'])
        if deal_id in POSTED_DEALS['Steam']:
            continue
        details = fetch_steam_details(deal['id'])
        summary = summarize_text(details['description'])
        message = (f"**{deal['name']}** on Steam - {deal['discount_percent']}% off\n"
                   f"Price: {deal['final_price']} {deal['currency']}\n"
                   f"Rating: {details['rating']}\n"
                   f"Summary: {summary}")
        post_to_discord(message)
        POSTED_DEALS['Steam'].add(deal_id)


def process_epic_deals():
    for deal in fetch_epic_deals():
        deal_id = str(deal['id'])
        if deal_id in POSTED_DEALS['Epic']:
            continue
        summary = summarize_text(deal.get('description', ''))
        message = (f"**{deal['name']}** on Epic Games - {deal['discount_percent']}% off\n"
                   f"Price: {deal['final_price']} {deal['currency']}\n"
                   f"Rating: N/A\n"
                   f"Summary: {summary}")
        post_to_discord(message)
        POSTED_DEALS['Epic'].add(deal_id)


def run_once():
    process_steam_deals()
    process_epic_deals()
    save_cache(POSTED_DEALS)


def main():
    interval = int(os.getenv('CHECK_INTERVAL_HOURS', '8'))
    logging.info('Starting deal bot - interval %s hours', interval)
    last_reset = time.time()
    while True:
        run_once()
        if CACHE_RESET_HOURS > 0 and time.time() - last_reset >= CACHE_RESET_HOURS * 3600:
            global POSTED_DEALS
            POSTED_DEALS = reset_cache()
            last_reset = time.time()
        logging.info('Sleeping for %s hours', interval)
        time.sleep(interval * 3600)


if __name__ == '__main__':
    main()
