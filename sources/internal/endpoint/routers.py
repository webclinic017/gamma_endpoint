import asyncio
from datetime import datetime, timezone
import logging
from fastapi import HTTPException, Query, Response, APIRouter, status
from fastapi_cache.decorator import cache

from endpoint.routers.template import (
    router_builder_generalTemplate,
    router_builder_baseTemplate,
)
from sources.common.formulas.fees import convert_feeProtocol
from sources.internal.bins.internal import (
    InternalFeeReturnsOutput,
    InternalFeeYield,
    InternalGrossFeesOutput,
    InternalTimeframe,
    InternalTokens,
)
from sources.mongo.bins.apps.hypervisor import hypervisors_collected_fees
from sources.mongo.bins.apps.prices import get_current_prices
from sources.mongo.bins.helpers import local_database_helper

from sources.common.database.collection_endpoint import database_global, database_local
from sources.common.database.common.collections_common import db_collections_common

from sources.subgraph.bins.enums import Chain, Protocol

from sources.subgraph.bins.config import DEPLOYMENTS
from sources.subgraph.bins.hype_fees.fees_yield import fee_returns_all

from ..bins.fee_internal import get_chain_usd_fees, get_fees, get_gross_fees

# Route builders


def build_routers() -> list:
    routes = []

    routes.append(
        internal_router_builder_main(tags=["Internal endpoints"], prefix="/internal")
    )

    return routes


# Route underlying functions


class internal_router_builder_main(router_builder_baseTemplate):
    # ROUTEs BUILD FUNCTIONS
    def router(self) -> APIRouter:
        router = APIRouter(prefix=self.prefix)

        #
        router.add_api_route(
            path="/{protocol}/{chain}/returns",
            endpoint=self.fee_returns,
            methods=["GET"],
        )

        router.add_api_route(
            path="/{chain}/gross_fees",
            endpoint=self.gross_fees,
            methods=["GET"],
        )

        router.add_api_route(
            path="/{chain}/all_fees",
            endpoint=self.all_chain_usd_fees,
            methods=["GET"],
        )

        router.add_api_route(
            path="/{chain}/weekly_fees",
            endpoint=self.weekly_chain_usd_fees,
            methods=["GET"],
        )

        return router

    # ROUTE FUNCTIONS
    async def fee_returns(
        self, protocol: Protocol, chain: Chain, response: Response
    ) -> dict[str, InternalFeeReturnsOutput]:
        """Returns APR and APY for specific protocol and chain"""
        if (protocol, chain) not in DEPLOYMENTS:
            raise HTTPException(
                status_code=400, detail=f"{protocol} on {chain} not available."
            )

        results = await asyncio.gather(
            fee_returns_all(protocol, chain, 1, return_total=True),
            fee_returns_all(protocol, chain, 7, return_total=True),
            fee_returns_all(protocol, chain, 30, return_total=True),
            return_exceptions=True,
        )

        result_map = {"daily": results[0], "weekly": results[1], "monthly": results[2]}

        output = {}

        valid_results = (
            (
                result_map["monthly"]["lp"]
                if isinstance(result_map["weekly"], Exception)
                else result_map["weekly"]["lp"]
            )
            if isinstance(result_map["daily"], Exception)
            else result_map["daily"]["lp"]
        )

        for hype_address in valid_results:
            output[hype_address] = InternalFeeReturnsOutput(
                symbol=valid_results[hype_address]["symbol"]
            )

            for period_name, period_result in result_map.items():
                if isinstance(period_result, Exception):
                    continue
                status_total = period_result["total"][hype_address]["status"]
                status_lp = period_result["lp"][hype_address]["status"]
                setattr(
                    output[hype_address],
                    period_name,
                    InternalFeeYield(
                        totalApr=period_result["total"][hype_address]["feeApr"],
                        totalApy=period_result["total"][hype_address]["feeApy"],
                        lpApr=period_result["lp"][hype_address]["feeApr"],
                        lpApy=period_result["lp"][hype_address]["feeApy"],
                        status=f"Total:{status_total}, LP: {status_lp}",
                    ),
                )

        return output

    # async def gross_fees(
    #     self,
    #     chain: Chain,
    #     response: Response,
    #     protocol: Protocol | None = None,
    #     start_timestamp: int | None = None,
    #     end_timestamp: int | None = None,
    #     start_block: int | None = None,
    #     end_block: int | None = None,
    # ):
    #     return await get_fees(
    #         chain=chain,
    #         protocol=protocol,
    #         start_timestamp=start_timestamp,
    #         end_timestamp=end_timestamp,
    #         start_block=start_block,
    #         end_block=end_block,
    #     )

    async def gross_fees(
        self,
        chain: Chain,
        response: Response,
        protocol: Protocol | None = None,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
        start_block: int | None = None,
        end_block: int | None = None,
    ) -> dict[str, InternalGrossFeesOutput]:
        """
        Calculates the gross fees aquired (not uncollected) in a period of time for a specific protocol and chain using the protocol fee switch data.

        * When no timeframe is provided, it returns all available data.

        * The **usd** field is calculated using the current (now) price of the token.

        * **protocolFee_X** is the percentage of fees going to the protocol, from 1 to 100.

        """

        if protocol and (protocol, chain) not in DEPLOYMENTS:
            raise HTTPException(
                status_code=400, detail=f"{protocol} on {chain} not available."
            )

        return get_gross_fees(
            chain=chain,
            protocol=protocol,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            start_block=start_block,
            end_block=end_block,
        )

    async def all_chain_usd_fees(
        self,
        chain: Chain,
        response: Response,
        protocol: Protocol | None = None,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
        start_block: int | None = None,
        end_block: int | None = None,
    ) -> dict:
        """
        Returns the total current priced USD fees collected (not uncollected) in a period of time for a specific chain
        It uses the "gross fees" point above as underlying data.

        * When no timeframe is provided, it returns all available data.

        * The **usd** field is calculated using the current (now) price of the token.

        * **collectedFees_perDay** are the daily fees collected in the period.
        """
        if protocol and (protocol, chain) not in DEPLOYMENTS:
            raise HTTPException(
                status_code=400, detail=f"{protocol} on {chain} not available."
            )

        return get_chain_usd_fees(
            chain=chain,
            protocol=protocol,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            start_block=start_block,
            end_block=end_block,
        )

    # async def get_report(
    #     self,
    #     chain: Chain,
    #     response: Response,
    #     protocol: Protocol | None = None,
    #     start_timestamp: int | None = None,
    #     end_timestamp: int | None = None,
    #     start_block: int | None = None,
    #     end_block: int | None = None,
    # ):
    #     find = {"type": "gross_fees"}
    #     if protocol:
    #         find["protocol"] = protocol.database_name
    #     if start_timestamp:
    #         find["timeframe.ini.timestamp"] = {"$gte": start_timestamp}
    #     if end_timestamp:
    #         find["timeframe.end.timestamp"] = {"$lte": end_timestamp}
    #     if start_block:
    #         find["timeframe.ini.block"] = {"$gte": start_block}
    #     if end_block:
    #         find["timeframe.end.block"] = {"$lte": end_block}

    #     # find reports
    #     return await local_database_helper(network=chain).get_items_from_database(
    #         collection_name="reports",
    #         find=find,
    #     )

    # async def get_gross_fees_ramses(
    #     self,
    #     response: Response,
    # ):
    #     return await get_fees(chain=Chain.ARBITRUM, protocol=Protocol.RAMSES)
    #     # return a sorted by period list of gross fees
    #     return sorted(
    #         [
    #             x["data"]
    #             for x in await self.get_report(chain=Chain.ARBITRUM, response=response)
    #         ],
    #         key=lambda x: x["period"],
    #     )

    async def weekly_chain_usd_fees(
        self,
        chain: Chain,
        response: Response,
        week_start_timestamp: int | str = "last",
        protocol: Protocol | None = None,
    ) -> list[dict]:
        """
        Returns the total current priced USD fees collected (not uncollected) in a period of time for a specific chain
        It uses the "gross fees" point above as underlying data.
        **week_start_timestamp**: 'last-2' or timestamp can be provided ( last-2 meaning 3 weeks ago)

        * The **usd** field is calculated using the current (now) price of the token.

        * **collectedFees_perDay** are the daily fees collected in the period.

        """
        week_in_seconds = 604800

        if isinstance(week_start_timestamp, str):
            _now = datetime.now(timezone.utc)
            if week_start_timestamp == "last":
                # calculate last week start timestamp
                week_start_timestamp = (
                    datetime(
                        year=_now.year,
                        month=_now.month,
                        day=_now.day,
                        tzinfo=timezone.utc,
                    ).timestamp()
                    - week_in_seconds
                )
            elif (
                week_start_timestamp.startswith("last")
                and len(week_start_timestamp.split("-")) == 2
            ):
                # calculate last week start timestamp
                week_start_timestamp = datetime(
                    year=_now.year,
                    month=_now.month,
                    day=_now.day,
                    tzinfo=timezone.utc,
                ).timestamp() - (
                    week_in_seconds * (int(week_start_timestamp.split("-")[1]) + 1)
                )
            else:
                raise HTTPException(
                    status_code=400, detail=f"Invalid week start timestamp."
                )

        # get current timestamp
        start_timestamp = week_start_timestamp or int(
            datetime.now(timezone.utc).timestamp()
        )
        end_timestamp = int(datetime.now(timezone.utc).timestamp())

        # weeks in the period
        weeks = int(end_timestamp - start_timestamp) // week_in_seconds

        # create a list of start and end timestamps for each week in the period
        week_timestamps = [
            (
                week,
                start_timestamp + (week_in_seconds * week),
                start_timestamp + (week_in_seconds * (week + 1)) - 1,
            )
            for week in range(weeks)
        ]

        # build output structure for each week
        requests = [
            get_chain_usd_fees(
                chain=chain,
                protocol=protocol,
                start_timestamp=st,
                end_timestamp=et,
                weeknum=weeknum + 1,
            )
            for weeknum, st, et in week_timestamps
        ]

        return await asyncio.gather(*requests)
