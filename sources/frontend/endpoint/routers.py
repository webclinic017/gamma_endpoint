import asyncio
from datetime import datetime, timezone
import logging
from fastapi import HTTPException, Query, Response, APIRouter, status
from fastapi_cache.decorator import cache

from endpoint.config.cache import (
    DAILY_CACHE_TIMEOUT,
)
from endpoint.routers.template import (
    router_builder_generalTemplate,
    router_builder_baseTemplate,
)
from sources.frontend.bins.revenue_stats import get_revenue_stats

from sources.subgraph.bins.enums import Chain, Protocol


# Route builders


def build_routers() -> list:
    routes = []

    routes.append(
        frontend_revenueStatus_router_builder_main(
            tags=["Revenue status"], prefix="/frontend"
        )
    )

    return routes


# Route underlying functions


class frontend_revenueStatus_router_builder_main(router_builder_baseTemplate):
    # ROUTEs BUILD FUNCTIONS
    def router(self) -> APIRouter:
        router = APIRouter(prefix=self.prefix)

        #
        router.add_api_route(
            path="/revenue_status/main_charts",
            endpoint=self.revenue_status,
            methods=["GET"],
        )

        return router

    # ROUTE FUNCTIONS
    @cache(expire=DAILY_CACHE_TIMEOUT)
    async def revenue_status(
        self,
        response: Response,
        chain: Chain | None = None,
        protocol: Protocol | None = None,
        from_timestamp: int | None = None,
        yearly: bool = False,
    ) -> list[dict]:
        """Returns Gamma's fees aquired by hypervisors, calculated volume of swaps on those same hypervisors and their revenue (Gamma service fees).

        * **total_revenue** are all tokens transfered to Gamma's fee accounts from hypervisors and other sources (line veNFT). USD token prices are from the date the transfer happened.
        * **total_fees** are all fees aquired by the hypervisors.  USD token prices are from the date it happened but can contain some posterior prices (week).
        * **total_volume** is calculated using **total_fees**.

        ### Query parameters
        * **chain** Chain to filter by.
        * **protocol** Protocol to filter by.
        * **from_timestamp** Limit returned data from timestamp to now.
        * **yearly** group result by year.

        """

        return await get_revenue_stats(
            chain=chain, protocol=protocol, yearly=yearly, ini_timestamp=from_timestamp
        )
