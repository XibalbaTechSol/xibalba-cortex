"""
Off-chain bridge: signs and submits a real ERC-4337 UserOperation so a declared
agent intent gets evaluated by `IntegrityKernel.preCheck` (and its registered
`AdapterRegistry` adapter) before the corresponding tool call executes.

Python port of `contracts/script/SubmitKernelBridgeUserOp.s.sol`
(~/.claude/plans/iridescent-stirring-kettle.md, Phase C) -- that Foundry script proved the
mechanism and construction details against a real local devnet; this module is the version
`runtime_claude_pre_tool_call` (`claude_adapter.py`) actually calls. Same disclosed gap applies
here as there: `IntegrityKernel`'s registered adapter is checked against `msg.value` of the
outer `execute()` call, not the amount encoded in `executionCalldata` -- for the standard
"account spends its own balance" pattern used here, the adapter always sees `amount=0` and
trivially approves. The KERNEL's own native per-op/cumulative budget check is unaffected (it
measures a real balance delta in `postCheck`). Callers of this module must not present the
adapter's ALLOW as a genuine amount-based decision -- see `kernel_decision["adapter_note"]`.

Talks to whatever `IntegrityKernel`/`IntegrityAccount`/`AdapterRegistry`/EntryPoint testbed is
recorded in `deployments.local.kernel-bridge.json` (local-devnet-only, EXPERIMENTAL, NOT
AUDITED -- see that file's own `disclosure` field). Never used against a real network.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from eth_account import Account
from web3 import Web3

_ENTRYPOINT_ABI = [
    {
        "name": "getNonce",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "sender", "type": "address"}, {"name": "key", "type": "uint192"}],
        "outputs": [{"name": "nonce", "type": "uint256"}],
    },
    {
        "name": "getUserOpHash",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {
                "name": "userOp",
                "type": "tuple",
                "components": [
                    {"name": "sender", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "initCode", "type": "bytes"},
                    {"name": "callData", "type": "bytes"},
                    {"name": "accountGasLimits", "type": "bytes32"},
                    {"name": "preVerificationGas", "type": "uint256"},
                    {"name": "gasFees", "type": "bytes32"},
                    {"name": "paymasterAndData", "type": "bytes"},
                    {"name": "signature", "type": "bytes"},
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "handleOps",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {
                "name": "ops",
                "type": "tuple[]",
                "components": [
                    {"name": "sender", "type": "address"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "initCode", "type": "bytes"},
                    {"name": "callData", "type": "bytes"},
                    {"name": "accountGasLimits", "type": "bytes32"},
                    {"name": "preVerificationGas", "type": "uint256"},
                    {"name": "gasFees", "type": "bytes32"},
                    {"name": "paymasterAndData", "type": "bytes"},
                    {"name": "signature", "type": "bytes"},
                ],
            },
            {"name": "beneficiary", "type": "address"},
        ],
        "outputs": [],
    },
]

# ABI fragment for the single event we read back off the receipt to learn the real
# ALLOW/DENY outcome -- `UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)`.
def _topic_hex(sig: str) -> str:
    return "0x" + Web3.keccak(text=sig).hex().removeprefix("0x")


_USER_OP_EVENT_TOPIC = _topic_hex("UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)")
_USER_OP_REVERT_TOPIC = _topic_hex("UserOperationRevertReason(bytes32,address,uint256,bytes)")

# execute(bytes32,bytes) selector.
_EXECUTE_SELECTOR = Web3.keccak(text="execute(bytes32,bytes)")[:4]


@dataclass
class KernelDecision:
    user_op_hash: str
    success: bool
    actual_gas_cost: int
    revert_reason_hex: Optional[str]
    adapter_note: str = (
        "SpendBudgetAdapter checked amount=0 (known gap: preCheck forwards the outer "
        "execute() call's msg.value, not the encoded transfer amount -- see "
        "contracts/script/SubmitKernelBridgeUserOp.s.sol's NatSpec). Only the kernel's own "
        "native per-op/cumulative budget check (via real postCheck balance-delta measurement) "
        "is a genuine amount-based decision here."
    )

    def to_dict(self) -> dict:
        return {
            "user_op_hash": self.user_op_hash,
            "success": self.success,
            "actual_gas_cost": self.actual_gas_cost,
            "revert_reason_hex": self.revert_reason_hex,
            "adapter_note": self.adapter_note,
        }


def _load_deployments(deployments_path: Path) -> dict:
    return json.loads(deployments_path.read_text())


def submit_kernel_intent(
    *,
    recipient: str,
    value_wei: int,
    rpc_url: str = "http://127.0.0.1:8545",
    deployments_path: Optional[Path] = None,
    private_key: Optional[str] = None,
) -> KernelDecision:
    """Signs and submits one real UserOperation: a plain native-value transfer of
    `value_wei` to `recipient`, routed through the kernel-bridge testbed's
    `IntegrityAccount.execute()` so `IntegrityKernel.preCheck`/`postCheck` and the registered
    adapter genuinely fire. Returns the real on-chain ALLOW/DENY result, read off the
    `UserOperationEvent`/`UserOperationRevertReason` log -- never fabricated.
    """
    deployments_path = deployments_path or Path(
        os.environ.get(
            "XIBALBA_KERNEL_BRIDGE_DEPLOYMENTS",
            Path(__file__).resolve().parents[4] / "integrity-core" / "deployments.local.kernel-bridge.json",
        )
    )
    deployments = _load_deployments(deployments_path)

    private_key = private_key or os.environ["XIBALBA_KERNEL_BRIDGE_PRIVATE_KEY"]
    signer = Account.from_key(private_key)

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
    entry_point = w3.eth.contract(address=Web3.to_checksum_address(deployments["entryPoint"]), abi=_ENTRYPOINT_ABI)
    account_address = Web3.to_checksum_address(deployments["IntegrityAccount"])
    recipient_address = Web3.to_checksum_address(recipient)

    execution_calldata = Web3.to_bytes(hexstr=recipient_address) + value_wei.to_bytes(32, "big")
    inner_call_data = w3.codec.encode(["bytes32", "bytes"], [b"\x00" * 32, execution_calldata])
    call_data = _EXECUTE_SELECTOR + inner_call_data

    nonce = entry_point.functions.getNonce(account_address, 0).call()

    account_gas_limits = (1_000_000).to_bytes(16, "big") + (1_000_000).to_bytes(16, "big")
    gas_fees = int(1e9).to_bytes(16, "big") + int(10e9).to_bytes(16, "big")

    user_op = (
        account_address,
        nonce,
        b"",
        call_data,
        account_gas_limits,
        100_000,
        gas_fees,
        b"",
        b"",
    )

    user_op_hash = entry_point.functions.getUserOpHash(user_op).call()
    signature = Account._sign_hash(user_op_hash, private_key=signer.key).signature
    signed_user_op = user_op[:-1] + (bytes(signature),)

    unsigned_tx = entry_point.functions.handleOps([signed_user_op], signer.address).build_transaction(
        {
            "from": signer.address,
            "nonce": w3.eth.get_transaction_count(signer.address),
            "chainId": w3.eth.chain_id,
        }
    )
    signed_tx = Account.sign_transaction(unsigned_tx, private_key=signer.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    success = True
    actual_gas_cost = 0
    revert_reason_hex: Optional[str] = None
    for log in receipt["logs"]:
        topic0 = "0x" + log["topics"][0].hex().removeprefix("0x")
        if topic0 == _USER_OP_EVENT_TOPIC:
            # Non-indexed fields only -- userOpHash/sender/paymaster are indexed (topics[1:]),
            # so `data` is (nonce, success, actualGasCost, actualGasUsed).
            _nonce, success, actual_gas_cost, _actual_gas_used = w3.codec.decode(
                ["uint256", "bool", "uint256", "uint256"], log["data"]
            )
        elif topic0 == _USER_OP_REVERT_TOPIC:
            _nonce, reason = w3.codec.decode(["uint256", "bytes"], log["data"])
            revert_reason_hex = reason.hex()

    return KernelDecision(
        user_op_hash="0x" + bytes(user_op_hash).hex(),
        success=success,
        actual_gas_cost=actual_gas_cost,
        revert_reason_hex=revert_reason_hex,
    )
