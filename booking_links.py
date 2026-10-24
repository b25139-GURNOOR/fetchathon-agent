"""Builds ready-to-click booking/search links. No API keys, no scraping.
Real booking (login + payment) always happens on the provider's own site."""
from datetime import date, timedelta
from urllib.parse import quote_plus

# destinations with no railway station: tell the user which station to use instead
RAIL_TIPS = {
    "manali": "Manali has no railway station. Book a train to Chandigarh (CDG) or Kiratpur Sahib, then a bus. Or just take the direct Delhi-Manali bus.",
    "shimla": "Shimla has a narrow-gauge station, but most people take a train to Kalka (KLK) and continue by toy train or bus.",
    "rishikesh": "Nearest main stations: Haridwar (HW) or Yog Nagri Rishikesh (YNRK).",
}


def _slug(s: str) -> str:
    return "-".join(s.strip().lower().split())


def build_links(origin: str, dest: str, start_iso: str = "", days: int = 3, travellers: int = 1):
    start = None
    try:
        start = date.fromisoformat(start_iso) if start_iso else None
    except ValueError:
        pass
    nights = max(1, days - 1)

    flights_q = f"Flights from {origin} to {dest}" + (f" on {start.isoformat()}" if start else "")
    links = [
        ("🚌 Buses (RedBus)", f"https://www.redbus.in/bus-tickets/{_slug(origin)}-to-{_slug(dest)}"),
        ("🚆 Trains (IRCTC)", "https://www.irctc.co.in/nget/train-search"),
        ("✈️ Flights (Google Flights)", "https://www.google.com/travel/flights?q=" + quote_plus(flights_q)),
    ]
    stay = f"https://www.booking.com/searchresults.html?ss={quote_plus(dest)}&group_adults={travellers}&no_rooms={max(1, (travellers + 1) // 2)}"
    if start:
        stay += f"&checkin={start.isoformat()}&checkout={(start + timedelta(days=nights)).isoformat()}"
    links.append(("🏨 Stays (Booking.com)", stay))
    links.append(("🗺️ Route (Google Maps)",
                  f"https://www.google.com/maps/dir/?api=1&origin={quote_plus(origin)}&destination={quote_plus(dest)}"))
    return links, RAIL_TIPS.get(dest.strip().lower(), "")
