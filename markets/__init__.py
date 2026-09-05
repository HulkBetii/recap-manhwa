from __future__ import annotations

from typing import Dict, List, Optional
from markets.base_market import BaseMarketProfile

_MARKET_REGISTRY: Dict[str, BaseMarketProfile] = {}


def register_market(profile: BaseMarketProfile) -> None:
    _MARKET_REGISTRY[profile.id] = profile


def get_market(market_id: Optional[str]) -> Optional[BaseMarketProfile]:
    if not market_id:
        return None
    return _MARKET_REGISTRY.get(market_id.strip().lower())


def list_markets() -> List[dict]:
    return [market.to_dict() for market in _MARKET_REGISTRY.values()]


# Auto-load market submodules
def _init_default_markets():
    try:
        from markets.korea_apocalypse import KOREA_APOCALYPSE_MARKET
        register_market(KOREA_APOCALYPSE_MARKET)
    except ImportError:
        pass

    try:
        from markets.japan_isekai_territory import JAPAN_ISEKAI_TERRITORY_MARKET
        register_market(JAPAN_ISEKAI_TERRITORY_MARKET)
    except ImportError:
        pass

_init_default_markets()
