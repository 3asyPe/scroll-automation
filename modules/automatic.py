import enum
import random
from copy import deepcopy

from loguru import logger
from web3 import Web3
from config import ZKSYNC_TOKENS
from modules import *
from utils.sleeping import sleep


class AutomaticModules(str, enum.Enum):
    swaps = "swaps"
    add_liquidity = "add_liquidity"
    mint_nft = "mint_nft"
    wrap_unwrap_eth = "wrap_unwrap_eth"
    send_email = "send_email"
    deploy = "deploy"
    layerbank = "layerbank"
    omnisea = "omnisea"
    mint_zerius = "mint_zerius"
    bridge_in = "bridge_in"
    bridge_out = "bridge_out"


class Automatic(Account):
    class ModuleEntry:
        def __init__(self, module, config):
            self.module_name = module
            self.config = config

    def __init__(
        self,
        account_id,
        private_key,
        proxy,
        okx_address,
        modules: list,
        config: dict,
        modules_config: dict,
    ):
        """
        modules - list of modules to get config for and run
        config - dict with settings and with configs for modules
        modules_config - config for modules
        """
        super().__init__(
            account_id=account_id, private_key=private_key, chain="scroll", proxy=proxy
        )

        self.account_id = account_id
        self.private_key = private_key
        self.proxy = proxy
        self.okx_address = okx_address
        self.config = deepcopy(config)
        self.modules_config = deepcopy(modules_config)

        self.modules_entries = []

        self.bridge_in = None
        self.brdge_out = None

        self._configure(modules)

        self.modules_mapping = {
            AutomaticModules.swaps: self.swaps,
            AutomaticModules.send_email: self.send_email,
            AutomaticModules.wrap_unwrap_eth: self.wrap_unwrap_eth,
            AutomaticModules.mint_nft: self.mint_nft,
            AutomaticModules.deploy: self.deploy_and_mint,
            AutomaticModules.layerbank: self.layerbank,
            AutomaticModules.omnisea: self.create_omnisea,
            AutomaticModules.mint_zerius: self.mint_zerius,
        }

        self.made_first_transaction = False

    def run(self):
        if self.config["deposit_enabled"]:
            if self.config["okx_withdraw_enabled"]:
                self.okx_withdraw()

            if self.config[AutomaticModules.bridge_in]["bridge_in_enabled"]:
                self.bridge_in()

        self.run_modules()

        if self.config["swap_all_tokens_to_eth_before_withdraw"]:
            self.swap_all_tokens_to_eth()

        if self.config["withdraw_enabled"]:
            if self.config[AutomaticModules.bridge_out]["bridge_out_enabled"]:
                self.bridge_out()

            if self.config["okx_deposit_enabled"]:
                self.okx_deposit()

    def run_modules(self):
        while len(self.modules_entries) > 0:
            module_entry = random.choice(self.modules_entries)

            if module_entry.module_name in self.modules_mapping:
                performed_transactions = self.modules_mapping[module_entry.module_name](
                    module_entry.config
                )
                self._remove_module_entries(
                    module_entry.module_name, performed_transactions
                )
            else:
                logger.error(f"Not supported module - {module_entry.module_name}")
                self._remove_module_entries(module_entry.module_name, 1, all=True)

    def run_module(
        self,
        module,
        module_name,
        module_transaction_id,
        kwargs,
        max_retries=None,
        fail_after_retries=False,
    ):
        logger.info(
            f"[{self.account_id}][{self.address}] | Performing {module_name} #{module_transaction_id}"
        )

        retries = 0
        max_retries = max_retries if max_retries is not None else self.config["retries"]

        if self.made_first_transaction or self.config["sleep_at_start"]:
            sleep(
                account_id=self.account_id,
                address=self.address,
                sleep_from=self.config["sleep_min"],
                sleep_to=self.config["sleep_max"],
            )

        done = False
        while not done and retries <= max_retries:
            # try:
            done = module(**kwargs)
            # except Exception as e:
            #     logger.error(
            #         f"[{self.account_id}][{self.address}] | {module_name} raised exception | {e}"
            #     )

            if not done:
                retries += 1
                logger.error(
                    f"[{self.account_id}][{self.address}] | {module_name} failed. Retrying #{retries}"
                )

                sleep(
                    account_id=self.account_id,
                    address=self.address,
                    sleep_from=self.config["retry_delay_min"],
                    sleep_to=self.config["retry_delay_max"],
                )

        self.made_first_transaction = True

        if not done and fail_after_retries:
            raise ValueError(f"{module_name} failed after {retries} retries")

        return done or self.config["skip_if_failed"]

    def swap_all_tokens_to_eth(self):
        config = self.config[AutomaticModules.swaps]

        logger.info(f"[{self.account_id}][{self.address}] | Swapping all tokens to ETH")

        balances = self.get_balances(config)

        for token in balances.values():
            if (
                token["symbol"] == "ETH"
                or not token["balance"]
                > self.config[f"min_balance_{token['symbol'].lower()}"]
            ):
                continue

            src_token = token
            dst_token = balances["ETH"]
            swap_module = self.choose_swap_module(
                config=config, src_token=src_token, dst_token=dst_token
            )
            amount = self.choose_swap_amount(config=config, src_token=src_token)
            return swap_module["class"](
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).swap(
                from_token=src_token["symbol"],
                to_token=dst_token["symbol"],
                min_amount=amount if amount != "all" else 0,
                max_amount=amount if amount != "all" else 0,
                decimal=src_token["decimal"],
                slippage=self.modules_config[swap_module["name"]]["slippage"],
                all_amount=amount == "all",
            )

    def swaps(self, config):
        quantity = self.choose_number_of_swaps(config=config)
        config["current_max_quantity"] = quantity

        performed_quantity = 0

        for _ in range(quantity):
            fail_after_retries = False
            if (
                config["performed_quantity"] == 0
                and config["raise_error_if_first_swap_from_eth_failed"]
            ):
                fail_after_retries = True

            done = self.run_module(
                module=self.swap,
                module_name="Swap",
                module_transaction_id=config["performed_quantity"] + 1,
                kwargs={"config": config},
                fail_after_retries=fail_after_retries,
            )

            if not done:
                logger.info(
                    f"[{self.account_id}][{self.address}] | Swap #{config['performed_quantity'] + 1} failed. Skipping"
                )
            else:
                performed_quantity += 1
                config["performed_quantity"] += 1

        return performed_quantity

    def deploy_and_mint(self, config):
        if self.run_module(
            module=Deployer(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
                chain="zksync",
            ).deploy_token,
            module_name="Deploy and mint",
            module_transaction_id=config["performed_quantity"] + 1,
            kwargs={},
        ):
            config["performed_quantity"] += 1
            return 1

        return 0
    
    def layerbank(self, config):
        performed_quantity = 0

        if config.get("withdrawn", True):
            try:
                self.run_module(
                    module=LayerBank(
                        account_id=self.account_id,
                        private_key=self.private_key,
                        proxy=self.proxy,
                    ).deposit,
                    module_name="LayerBank deposit",
                    module_transaction_id=round(config["performed_quantity"] / 2) + 1,
                    kwargs={
                        "min_amount": 1,
                        "max_amount": 1,
                        "decimal": 6,
                        "all_amount": True,
                        "sleep_from": 1,
                        "sleep_to": 1,
                        "make_withdraw": False,
                        "min_percent": self.modules_config[MODULES_NAMES.layerbank]["min_percent"],
                        "max_percent": self.modules_config[MODULES_NAMES.layerbank]["max_percent"],
                    },
                    fail_after_retries=True,
                )
                performed_quantity += 1
            except Exception:
                logger.error(
                    f"[{self.account_id}][{self.address}] | LayerBank deposit Failed. Skipping Withdraw"
                )

                if self.config["skip_if_failed"]:
                    config["performed_quantity"] += 2
                    return 2
                return 0

        done = self.run_module(
            module=LayerBank(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).withdraw,
            module_name="LayerBank withdraw",
            module_transaction_id=round(config["performed_quantity"] / 2) + 1,
            kwargs={},
        )

        if done:
            performed_quantity += 1
            config["withdrawn"] = True
        else:
            config["withdrawn"] = False

        config["performed_quantity"] += performed_quantity

        return performed_quantity

    def create_omnisea(self, config):
        if self.run_module(
            module=Omnisea(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).create,
            module_name="Create OmniSea NFT Collection",
            module_transaction_id=config["performed_quantity"] + 1,
            kwargs={},
        ):
            config["performed_quantity"] += 1
            return 1

        return 0

    def mint_zerius(self, config):
        if self.run_module(
            module=Zerius(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).mint,
            module_name="Mint NFT",
            module_transaction_id=config["performed_quantity"] + 1,
            kwargs=self.modules_config[MODULES_NAMES.mint_nft],
        ):
            config["performed_quantity"] += 1
            return 1

        return 0

    def mint_nft(self, config):
        if self.run_module(
            module=Minter(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).mint_nft,
            module_name="Mint NFT",
            module_transaction_id=config["performed_quantity"] + 1,
            kwargs=self.modules_config[MODULES_NAMES.mint_nft],
        ):
            config["performed_quantity"] += 1
            return 1

        return 0

    def send_email(self, config):
        if self.run_module(
            module=Dmail(
                account_id=self.account_id,
                private_key=self.private_key,
                proxy=self.proxy,
            ).send_mail,
            module_name="Send Dmail",
            module_transaction_id=config["performed_quantity"] + 1,
            kwargs={},
        ):
            config["performed_quantity"] += 1
            return 1

        return 0

    def wrap_unwrap_eth(self, config):
        scroll_client = Scroll(
            account_id=self.account_id,
            private_key=self.private_key,
            proxy=self.proxy,
            chain="scroll",
        )

        performed_quantity = 0

        if config.get("unwraped", True):
            try:
                self.run_module(
                    scroll_client.wrap_eth,
                    module_name="Wrap ETH",
                    module_transaction_id=round(config["performed_quantity"] / 2) + 1,
                    kwargs={
                        "min_amount": 1,
                        "max_amount": 1,
                        "decimal": 4,
                        "all_amount": True,
                        "min_percent": self.modules_config[MODULES_NAMES.wrap_eth]["min_percent"],
                        "max_percent": self.modules_config[MODULES_NAMES.wrap_eth]["max_percent"],
                    },
                    fail_after_retries=True,
                )
                performed_quantity += 1
            except Exception:
                logger.error(
                    f"[{self.account_id}][{self.address}] | Wrap ETH failed. Skipping Unwrap"
                )

                if self.config["skip_if_failed"]:
                    config["performed_quantity"] += 2
                    return 2
                return 0

        done = self.run_module(
            scroll_client.unwrap_eth,
            module_name="Unwrap ETH",
            module_transaction_id=round(config["performed_quantity"] / 2) + 1,
            kwargs={
                "min_amount": 1,
                "max_amount": 1,
                "decimal": 4,
                "all_amount": True,
                "min_percent": self.modules_config[MODULES_NAMES.unwrap_eth]["min_percent"],
                "max_percent": self.modules_config[MODULES_NAMES.unwrap_eth]["max_percent"],
            },
        )

        if done:
            performed_quantity += 1
            config["unwraped"] = True
        else:
            config["unwraped"] = False

        config["performed_quantity"] += performed_quantity

        return performed_quantity

    def swap(self, config):
        balances = self.get_balances(config)

        src_token = self.choose_src_token(balances=balances, config=config)
        logger.debug(f"src_token={src_token}")
        dst_token = self.choose_dst_token(
            src_token=src_token, balances=balances, config=config
        )
        logger.debug(f"dst_token={dst_token}")
        swap_module = self.choose_swap_module(
            config=config, src_token=src_token, dst_token=dst_token
        )
        logger.debug(f"swap_module={swap_module}")
        amount = self.choose_swap_amount(
            config=config,
            src_token=src_token,
        )
        logger.debug(f"amount={amount}")

        return swap_module["class"](
            account_id=self.account_id,
            private_key=self.private_key,
            proxy=self.proxy,
        ).swap(
            from_token=src_token["symbol"],
            to_token=dst_token["symbol"],
            min_amount=amount if amount != "all" else 0,
            max_amount=amount if amount != "all" else 0,
            decimal=src_token["decimal"],
            slippage=self.modules_config[swap_module["name"]]["slippage"],
            all_amount=amount == "all",
        )

    def choose_swap_amount(self, config, src_token):
        if src_token["symbol"] == "ETH":
            if src_token["balance"] <= self.config["min_balance_eth"]:
                raise ValueError(
                    f"Not enough ETH to swap | balance={src_token['balance']} | min_balance_eth={self.config['min_balance_eth']}"
                )

            return min(
                float(src_token["balance"]) - self.config["min_balance_eth"],
                round(
                    random.uniform(config["min_amount"], config["max_amount"]),
                    src_token["decimal"],
                ),
            )

        return "all"

    def choose_swap_module(self, config, src_token, dst_token):
        modules = []
        for module_name in config["services"]:
            module = SWAP_MODULES[module_name]
            if (
                src_token["symbol"] in module["tokens"]
                and dst_token["symbol"] in module["tokens"][src_token["symbol"]]
            ):
                module["name"] = module_name
                modules.append(module)

        return random.choice(modules)

    def choose_number_of_swaps(self, config):
        maximum = config["max_quantity"] - config["performed_quantity"]
        quantity = maximum - 1

        # exlude case when quantity == maximum - 1
        while quantity == maximum - 1:
            quantity = random.randint(2, maximum)

        return quantity

    def choose_src_token(self, balances, config) -> dict:
        balances = balances.copy()

        eth = balances.pop("ETH")
        if config["first_swap_from_eth"] and config["performed_quantity"] == 0:
            return eth

        tokens = sorted(balances.values(), key=lambda x: x["balance_wei"], reverse=True)
        chosen_token = None
        for token in tokens:
            if (
                token["balance"]
                >= self.config[f"min_balance_{token['symbol'].lower()}"]
            ):
                chosen_token = token
                break

        if chosen_token is None:
            chosen_token = eth

        return chosen_token

    def choose_dst_token(self, balances: dict, src_token, config) -> dict:
        balances = balances.copy()

        if config["performed_quantity"] == config["current_max_quantity"] - 1:
            if src_token["symbol"] != "ETH":
                return balances["ETH"]

        dst_tokens = set()

        for module_name in config["services"]:
            module = SWAP_MODULES[module_name]
            if src_token["symbol"] in module["tokens"]:
                dst_tokens.update(module["tokens"][src_token["symbol"]])

        token = random.choice(list(dst_tokens))

        return balances[token]

    def get_balances(self, config):
        swappable_tokens = self.get_swappable_tokens(config=config)
        tokens = {k: v for k, v in ZKSYNC_TOKENS.items() if k in swappable_tokens}

        balances = super().get_balances(tokens=tokens)

        return balances

    def okx_deposit(self):
        okx_client = OKX(
            account_id=self.account_id,
            private_key=self.private_key,
            proxy=self.proxy,
            chain=self.config[AutomaticModules.bridge_out]["bridge_out_chain"],
            credentials=self.modules_config[MODULES_NAMES.okx_deposit]["credentials"],
        )
        if self.config[AutomaticModules.bridge_out]["bridge_out_chain"] == "zksync":
            min_amount_left = self.config["min_amount_leave_on_zksync"]
            max_amount_left = self.config["max_amount_leave_on_zksync"]
        else:
            min_amount_left = 0
            max_amount_left = 0

        if not okx_client.deposit(
            address=self.okx_address,
            min_amount_left=min_amount_left,
            max_amount_left=max_amount_left,
        ):
            raise ValueError("OKX deposit failed")

        return True

    def okx_withdraw(self):
        okx_client = OKX(
            account_id=self.account_id,
            private_key=self.private_key,
            proxy=self.proxy,
            chain=self.config[AutomaticModules.bridge_in]["bridge_in_chain"],
            credentials=self.modules_config[MODULES_NAMES.okx_withdraw]["credentials"],
        )
        if not okx_client.withdraw(
            min_amount=self.modules_config[MODULES_NAMES.okx_withdraw]["min_amount"],
            max_amount=self.modules_config[MODULES_NAMES.okx_withdraw]["max_amount"],
            token="ETH",
            transfer_from_subaccounts=self.modules_config[MODULES_NAMES.okx_withdraw][
                "transfer_from_subaccounts"
            ],
        ):
            raise ValueError("OKX withdraw failed")

        return True

    def native_bridge_in(self):
        config = self.modules_config[MODULES_NAMES.bridge_in_scroll]

        scroll = Scroll(self.account_id, self.private_key, self.proxy, "ethereum")
        if not scroll.deposit(
            min_amount=config["min_amount"],
            max_amount=config["max_amount"],
            decimal=config["decimal"],
            all_amount=config["all_amount"],
            min_percent=self.modules_config[MODULES_NAMES.bridge_in_scroll]["min_percent"],
            max_percent=self.modules_config[MODULES_NAMES.bridge_in_scroll]["max_percent"],
        ):
            raise ValueError("Native bridge in failed")

        return True

    def native_bridge_out(self):
        config = self.modules_config[MODULES_NAMES.bridge_out_scroll]

        amount = self.get_amount_to_bridge_out()

        scroll = Scroll(self.account_id, self.private_key, self.proxy, "scroll")
        if not scroll.withdraw(
            min_amount=amount,
            max_amount=amount,
            decimal=5,
            all_amount=False,
            min_percent=self.modules_config[MODULES_NAMES.bridge_out_scroll]["min_percent"],
            max_percent=self.modules_config[MODULES_NAMES.bridge_out_scroll]["max_percent"],
        ):
            raise ValueError("Native bridge out failed")

        return True

    def orbiter_bridge_in(self):
        config = self.modules_config[MODULES_NAMES.bridge_orbiter]

        orbiter = Orbiter(
            account_id=self.account_id,
            private_key=self.private_key,
            chain=self.config[AutomaticModules.bridge_in]["bridge_in_chain"],
            proxy=self.proxy,
        )
        if not orbiter.bridge(
            destination_chain="scroll",
            min_bridge=config["min_amount"],
            max_bridge=config["max_amount"],
            decimal=config["decimal"],
            all_amount=config["all_amount"],
            min_percent=self.modules_config[MODULES_NAMES.bridge_orbiter]["min_percent"],
            max_percent=self.modules_config[MODULES_NAMES.bridge_orbiter]["max_percent"],
        ):
            raise ValueError("Orbiter bridge in failed")

        return True

    def orbiter_bridge_out(self):
        config = self.modules_config[MODULES_NAMES.bridge_orbiter]

        amount = self.get_amount_to_bridge_out()

        orbiter = Orbiter(
            account_id=self.account_id,
            private_key=self.private_key,
            chain="zksync",
            proxy=self.proxy,
        )
        if not orbiter.bridge(
            destination_chain=self.config[AutomaticModules.bridge_out][
                "bridge_out_chain"
            ],
            min_bridge=amount,
            max_bridge=amount,
            decimal=5,
            all_amount=False,
            min_percent=0,
            max_percent=0,
        ):
            raise ValueError("Orbiter bridge out failed")

        return True

    def get_amount_to_bridge_out(self):
        balance_wei = self.w3.eth.get_balance(self.address)
        balance = float(Web3.from_wei(balance_wei, "ether"))

        amount_to_leave = round(
            random.uniform(
                self.config["min_amount_leave_on_scroll"],
                self.config["max_amount_leave_on_scroll"],
            ),
            5,
        )

        if balance <= amount_to_leave:
            raise ValueError(
                f"Not enough ETH to bridge out | balance={balance} | min_balance_eth={self.config['min_balance_eth']}"
            )

        return balance - amount_to_leave

    def get_swappable_tokens(self, config):
        tokens = set()
        for module_name in config["services"]:
            module = SWAP_MODULES[module_name]
            for token in module["tokens"].keys():
                tokens.add(token)
        return tokens

    def _remove_module_entries(self, module_name, quantity, all=False):
        removed = 0

        self.modules_entries = [
            module_entry
            for module_entry in self.modules_entries
            if module_entry.module_name != module_name
            or ((removed := removed + 1) > quantity and not all)
        ]

    def _configure(self, modules):
        if self.config[AutomaticModules.bridge_in]["bridge_in_service"] == "native":
            self.bridge_in = self.native_bridge_in
        elif self.config[AutomaticModules.bridge_in]["bridge_in_service"] == "orbiter":
            self.bridge_in = self.orbiter_bridge_in
        else:
            raise ValueError(
                f"Unknown bridge_in_service: {self.config[AutomaticModules.bridge_in]['bridge_in_service']}"
            )

        if self.config[AutomaticModules.bridge_out]["bridge_out_service"] == "native":
            self.bridge_out = self.native_bridge_out
        elif (
            self.config[AutomaticModules.bridge_out]["bridge_out_service"] == "orbiter"
        ):
            self.bridge_out = self.orbiter_bridge_out
        else:
            raise ValueError(
                f"Unknown bridge_out_service: {self.config[AutomaticModules.bridge_out]['bridge_out_service']}"
            )

        for module_name in modules:
            quantity = random.randint(
                self.config[module_name]["min_quantity"],
                self.config[module_name]["max_quantity"],
            )

            if module_name in (
                AutomaticModules.wrap_unwrap_eth,
            ):
                quantity *= 2

            config = self.config[module_name]
            config["total_quantity"] = quantity
            config["performed_quantity"] = 0

            entry = self.ModuleEntry(module_name, config)

            for _ in range(quantity):
                self.modules_entries.append(entry)
