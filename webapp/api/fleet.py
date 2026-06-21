"""Fleet 情報(複数 PC で 1 つの GUI から全 PC を扱う面)。

各 PC は自分自身の設定だけを返す(自分から見た peers + self_name)。
frontend は起動時にこれを取得し、各 peer の Next URL(/api/* を中継)へ並列 fetch する。
[fleet] 設定が空でも、自 host を 1 件の peer として返す(クライアント側の「Fleet OFF/ON」分岐を消す)。

[fleet] 設定例(loop.local.toml に書く):

    [fleet]
    self = "shuyamacbook-pro"
    peers = [
      { name = "shuyamacbook-pro", url = "http://shuyamacbook-pro.taila217e5.ts.net:3000" },
      { name = "other-mac",        url = "http://other-mac.taila217e5.ts.net:3000" },
    ]
"""

from __future__ import annotations

from fastapi import APIRouter

from .. import schemas
from ..util import runner

router = APIRouter(tags=["fleet"])


@router.get("/fleet/peers", response_model=schemas.FleetInfo)
def fleet_peers() -> schemas.FleetInfo:
    cfg = runner.load_config()
    fleet = cfg.get("fleet", {}) or {}
    self_name = fleet.get("self") or "local"
    raw_peers = fleet.get("peers", []) or []
    peers: list[schemas.FleetPeer] = []
    for p in raw_peers:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        url = p.get("url")
        if not name or not url:
            continue
        peers.append(schemas.FleetPeer(
            name=str(name), url=str(url).rstrip("/"),
            is_self=(name == self_name),
        ))
    # 設定が空でも自 host を 1 件の peer として返す(クライアントの分岐を消す)
    if not peers:
        peers = [schemas.FleetPeer(name=self_name, url="http://127.0.0.1:3000", is_self=True)]
    return schemas.FleetInfo(self_name=self_name, peers=peers)
