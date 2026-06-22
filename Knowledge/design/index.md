# Design

loop engine の絶対原則・不変条件・設計判断(公開可のもの)。

* [絶対原則・不変条件](/design/invariants.md) - 種類A/B / ファイルが真実 / 削除しない=アーカイブ / Verifier 別モデル / 死角を作らない。
* [2 repo 分離(engine / data)](/design/two-repo-split.md) - 公開コードと非公開契約の境界。知識バンドルもこれを踏襲。

> no-repo 撤去と実データの矛盾(data 固有の判断・種類B)は非公開バンドル [/private/decisions/no-repo-doc-data-conflict.md](/private/decisions/no-repo-doc-data-conflict.md) にある。
