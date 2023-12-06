from loguru import logger

from utils.gas_checker import check_gas
from utils.helpers import retry
from .account import Account
from config import ORBITER_CONTRACT


class Orbiter(Account):
    def __init__(self, account_id: int, private_key: str, proxy: str, chain: str) -> None:
        super().__init__(account_id=account_id, private_key=private_key, proxy=proxy, chain=chain)

        self.bridge_codes = {
            "ethereum": "9001",
            "arbitrum": "9002",
            "polygon": "9006",
            "optimism": "9007",
            "zksync": "9014",
            "nova": "9016",
            "zkevm": "9017",
            "scroll": "9019",
            "base": "9021",
            "linea": "9023",
            "zora": "9030",
        }

    async def bridge(
            self,
            destination_chain: str,
            min_amount: float,
            max_amount: float,
            decimal: int,
            all_amount: bool,
            min_percent: int,
            max_percent: int
    ):  
        try:
            amount_wei, amount, balance = await self.get_amount(
                from_token="ETH",
                min_amount=min_amount,
                max_amount=max_amount,
                decimal=decimal,
                all_amount=all_amount,
                min_percent=min_percent,
                max_percent=max_percent,
                fee_cost_wei=self.w3.to_wei(0.0001, "ether")
            )

            if ORBITER_CONTRACT == "":
                logger.error(f"[{self.account_id}][{self.address}] Don't have orbiter contract")
                return

            if amount < 0.005 or amount > 5:
                logger.error(
                    f"[{self.account_id}][{self.address}] Limit range amount for bridge 0.005 – 5 ETH | {amount} ETH"
                )
            else:
                logger.info(
                    f"[{self.account_id}][{self.address}] Bridge {self.chain} –> {destination_chain} | {amount} ETH"
                )

                amount_to_bridge = str(amount_wei).replace(str(amount_wei)[-4:], self.bridge_codes[destination_chain])

                tx_data = await self.get_tx_data(int(amount_to_bridge))
                tx_data.update({"to": self.w3.to_checksum_address(ORBITER_CONTRACT)})

                balance = await self.w3.eth.get_balance(self.address)

                if tx_data["value"] >= balance:
                    logger.error(f"[{self.account_id}][{self.address}] Insufficient funds!")
                else:
                    signed_txn = await self.sign(tx_data)

                    txn_hash = await self.send_raw_transaction(signed_txn)

                    await self.wait_until_tx_finished(txn_hash.hex())
                return True
        except Exception as e:
            logger.error(
                f"[{self.account_id}][{self.address}] Orbiter Bridge Error | {e}"
            )

        return False