"""On-chain anchoring via web3.py against the IncidentAnchor contract
(Anvil in dev, Sepolia optional for demo). Only 32-byte Merkle roots ever
touch the chain — never metrics or alert content."""

import logging

from web3 import AsyncHTTPProvider, AsyncWeb3

from vigil.core.config import get_settings

log = logging.getLogger(__name__)

INCIDENT_ANCHOR_ABI = [
    {
        "type": "function",
        "name": "anchor",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "root", "type": "bytes32"},
            {"name": "firstEventId", "type": "uint64"},
            {"name": "lastEventId", "type": "uint64"},
        ],
        "outputs": [{"name": "batchId", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "getBatch",
        "stateMutability": "view",
        "inputs": [{"name": "id", "type": "uint256"}],
        "outputs": [
            {"name": "root", "type": "bytes32"},
            {"name": "firstEventId", "type": "uint64"},
            {"name": "lastEventId", "type": "uint64"},
            {"name": "timestamp", "type": "uint256"},
        ],
    },
    {
        "type": "function",
        "name": "batchCount",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "event",
        "name": "Anchored",
        "inputs": [
            {"name": "batchId", "type": "uint256", "indexed": True},
            {"name": "root", "type": "bytes32", "indexed": False},
            {"name": "firstEventId", "type": "uint64", "indexed": False},
            {"name": "lastEventId", "type": "uint64", "indexed": False},
            {"name": "timestamp", "type": "uint256", "indexed": False},
        ],
        "anonymous": False,
    },
]


class ChainClient:
    def __init__(self, rpc_url: str | None = None, contract_address: str | None = None,
                 private_key: str | None = None) -> None:
        s = get_settings()
        self.w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url or s.chain_rpc_url))
        self.account = self.w3.eth.account.from_key(private_key or s.ledger_private_key)
        self.contract = self.w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(contract_address or s.ledger_contract_address),
            abi=INCIDENT_ANCHOR_ABI,
        )

    async def anchor(self, root: bytes, first_event_id: int, last_event_id: int) -> dict:
        """Submit anchor tx, wait for receipt, return {tx_hash, block_number, chain_batch_id}."""
        tx = await self.contract.functions.anchor(root, first_event_id, last_event_id).build_transaction(
            {
                "from": self.account.address,
                "nonce": await self.w3.eth.get_transaction_count(self.account.address),
                "chainId": await self.w3.eth.chain_id,
            }
        )
        signed = self.account.sign_transaction(tx)
        tx_hash = await self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = await self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        if receipt["status"] != 1:
            raise RuntimeError(f"anchor tx reverted: {tx_hash.hex()}")
        logs = self.contract.events.Anchored().process_receipt(receipt)
        chain_batch_id = int(logs[0]["args"]["batchId"]) if logs else None
        return {
            "tx_hash": tx_hash.hex() if tx_hash.hex().startswith("0x") else "0x" + tx_hash.hex(),
            "block_number": receipt["blockNumber"],
            "chain_batch_id": chain_batch_id,
        }

    async def get_root(self, chain_batch_id: int) -> bytes:
        batch = await self.contract.functions.getBatch(chain_batch_id).call()
        return bytes(batch[0])


def get_chain_client() -> ChainClient | None:
    s = get_settings()
    if not (s.ledger_enabled and s.ledger_private_key and s.ledger_contract_address):
        return None
    try:
        return ChainClient()
    except Exception:
        log.exception("chain client init failed — anchoring disabled")
        return None
