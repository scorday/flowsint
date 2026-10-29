import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import requests.exceptions
from dotenv import load_dotenv

from flowsint_core.core.enricher_base import Enricher
from flowsint_core.core.enricher_metadata import EnricherMetadata
from flowsint_core.core.logger import Logger
from flowsint_enrichers.registry import flowsint_enricher
from flowsint_types.wallet import CryptoWallet, CryptoWalletTransaction

load_dotenv()


def wei_to_eth(wei_str):
    return int(wei_str) / 10**18


@flowsint_enricher
class CryptoWalletAddressToTransactions(Enricher):
    """[ETHERSCAN] Resolve transactions for a wallet address (ETH)."""

    metadata = EnricherMetadata(
        description="Fetches normal Ethereum transactions for a wallet from Etherscan and creates transaction and wallet relationships. The current implementation requests the first 100 transactions in ascending order, so the result is not a complete transaction history.",
        providers=("Etherscan",),
        api_key_requirement="required",
        api_key_notes="Requires ETHERSCAN_API_KEY. ETHERSCAN_API_URL can override the default Etherscan API endpoint.",
    )

    # Define types as class attributes - base class handles schema generation automatically
    InputType = CryptoWallet
    OutputType = CryptoWalletTransaction

    def __init__(
        self,
        sketch_id: Optional[str] = None,
        scan_id: Optional[str] = None,
        vault=None,
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            sketch_id=sketch_id,
            scan_id=scan_id,
            params_schema=self.get_params_schema(),
            vault=vault,
            params=params,
        )

    @classmethod
    def required_params(cls) -> bool:
        return True

    @classmethod
    def icon(cls) -> str | None:
        return "cryptowallet"

    @classmethod
    def get_params_schema(cls) -> List[Dict[str, Any]]:
        """Declare required parameters for this enricher"""
        return [
            {
                "name": "ETHERSCAN_API_KEY",
                "type": "vaultSecret",
                "description": "The Etherscan API key to use for the transaction lookup.",
                "required": True,
            },
            {
                "name": "ETHERSCAN_API_URL",
                "type": "url",
                "description": "The Etherscan API URL to use for the transaction lookup.",
                "required": False,
                "default": "https://api.etherscan.io/v2/api",
            },
        ]

    @classmethod
    def name(cls) -> str:
        return "cryptowallet_to_transactions"

    @classmethod
    def category(cls) -> str:
        return "CryptoWallet"

    @classmethod
    def key(cls) -> str:
        return "address"

    async def scan(self, data: List[InputType]) -> List[OutputType]:
        results: List[OutputType] = []
        api_key = self.get_secret("ETHERSCAN_API_KEY", os.getenv("ETHERSCAN_API_KEY"))
        api_url = self.get_params().get(
            "ETHERSCAN_API_URL", "https://api.etherscan.io/v2/api"
        )
        for d in data:
            try:
                transactions = await self._get_transactions(d.address, api_key, api_url)
                results.append(transactions)
            except Exception as e:
                Logger.error(
                    self.sketch_id,
                    {"message": f"Error resolving transactions for {d.address}: {e}"},
                )
        return results

    async def _get_transactions(
        self, address: str, api_key: str, api_url: str
    ) -> List[CryptoWalletTransaction]:
        transactions = []
        """Get transactions for a wallet address."""
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 100,
            "sort": "asc",
            "apikey": api_key,
        }
        try:
            response = requests.get(api_url, params=params)

            # Raise an exception for HTTP errors (4xx or 5xx status codes)
            response.raise_for_status()

        except requests.exceptions.ConnectionError as e:
            raise ValueError(
                f"An error occurred connecting to {api_url}: Connection failed - {str(e)}"
            )
        except requests.exceptions.Timeout as e:
            raise ValueError(
                f"An error occurred fetching {api_url}: Request timeout - {str(e)}"
            )
        except requests.exceptions.RequestException as e:
            raise ValueError(f"An error occurred fetching {api_url}: {str(e)}")

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError as e:
            raise ValueError(
                f"An error occurred fetching {api_url}: Invalid JSON response - {str(e)}"
            )

        # Check if the API returned an error
        if data.get("status") != "1":
            error_message = data.get("message", "Unknown API error")
            raise ValueError(f"An error occurred fetching {api_url}: {error_message}")

        results = data.get("result", [])
        for tx in results:
            # Properly determine source and target based on transaction data
            source_address = tx["from"]

            if tx["to"] is not None:
                target_address = tx["to"]
            else:
                # Contract creation transaction
                target_address = (
                    tx["contractAddress"] if tx["contractAddress"] else address
                )

            transactions.append(
                CryptoWalletTransaction(
                    source=CryptoWallet(address=source_address),
                    target=CryptoWallet(address=target_address),
                    hash=tx["hash"],
                    value=wei_to_eth(tx["value"]),
                    timestamp=tx["timeStamp"],
                    block_number=tx["blockNumber"],
                    block_hash=tx["blockHash"],
                    nonce=tx["nonce"],
                    transaction_index=tx["transactionIndex"],
                    gas=tx["gas"],
                    gas_price=tx["gasPrice"],
                    gas_used=tx["gasUsed"],
                    cumulative_gas_used=tx["cumulativeGasUsed"],
                    input=tx["input"],
                    contract_address=tx["contractAddress"],
                )
            )
        return transactions

    def postprocess(
        self, results: List[OutputType], original_input: List[InputType]
    ) -> List[OutputType]:
        if not self._graph_service:
            return results

        for transactions in results:
            for tx in transactions:
                if tx.target is None:
                    continue
                source = self._graph_service.create_node_from_flowsint_type(tx.source)
                target = self._graph_service.create_node_from_flowsint_type(tx.target)
                properties = tx.model_dump(
                    mode="json",
                    exclude={"source", "target", "nodeLabel"},
                    exclude_none=True,
                )
                properties.update(
                    {"event_key": tx.hash, "caption": tx.hash, "type": "transaction"}
                )
                self._graph_service.batch_create_edges_by_element_id(
                    [
                        {
                            "from_element_id": source,
                            "to_element_id": target,
                            "rel_label": "TRANSACTION",
                            "properties": properties,
                        }
                    ]
                )

                timestamp_str = (
                    datetime.fromtimestamp(int(tx.timestamp)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if tx.timestamp
                    else "Unknown time"
                )
                self.log_graph_message(
                    f"Transaction on {timestamp_str}: {tx.source.address} -> {tx.target.address}"
                )

        return results


# Make types available at module level for easy access
InputType = CryptoWalletAddressToTransactions.InputType
OutputType = CryptoWalletAddressToTransactions.OutputType
