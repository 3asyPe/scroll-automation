import enum

from .account import Account
from .scroll import Scroll
from .orbiter import Orbiter
from .layerswap import LayerSwap
from .skydrome import Skydrome
from .syncswap import SyncSwap
from .layerbank import LayerBank
from .zerius import Zerius
from .dmail import Dmail
from .omnisea import Omnisea
from .nfts2me import Minter
from .deploy import Deployer
from .routes import Routes
from .tx_checker import check_tx
from .okx import OKX


class MODULES_NAMES(str, enum.Enum):
    okx_deposit = "okx_deposit"
    okx_withdraw = "okx_withdraw"
    bridge_in_scroll = "bridge_in_scroll"
    bridge_out_scroll = "bridge_out_scroll"
    bridge_orbiter = "bridge_orbiter"
    bridge_layerswap = "bridge_layerswap"
    swap_syncswap = "swap_syncswap"
    swap_skydrome = "swap_skydrome"
    deposit_layerbank = "deposit_layerbank"
    withdraw_layerbank = "withdraw_layerbank"
    wrap_eth = "wrap_eth"
    unwrap_eth = "unwrap_eth"
    mint_nft = "mint_nft"
    mint_zerius = "mint_zerius"
    create_omnisea = "create_omnisea"
    deploy_contract = "deploy_contract"
    send_mail = "send_mail"
    tx_checker = "tx_checker"


SWAP_MODULES = {
    MODULES_NAMES.swap_syncswap: {
        "class": SyncSwap,
        "tokens": {
            "ETH": ["USDC", "USDT"],
            "USDC": ["ETH", "USDT"],
            "USDT": ["ETH", "USDC"],
        },
    },
}
