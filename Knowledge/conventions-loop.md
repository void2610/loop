---
type: Conventions
title: loop 固有 OKF オーバーレイ
description: okf-conventions(submodule・読取専用)に loop 固有の type 語彙・2 バンドル分離・種類B 規約・anchor 解決規則を上乗せする。
timestamp: 2026-06-23T07:19:07Z
---

# 概要

`conventions/CONVENTIONS.md`(submodule・読み取り専用)はゲーム向け語彙が中心。loop はツールなので、
**submodule を編集せず**この `conventions-loop.md` で loop 固有の規約を追加宣言する。
規約本体の改善が要るときは中央 `okf-conventions` に投げ、submodule ポインタを進める。

# type 語彙(loop 向け拡張)

| type | 用途 | 区分 |
|---|---|---|
| `System` | 実装システム(`resource:` で `runner.py` / `loopdb.py` / `webapp/` 等を指す) | 種類A |
| `Trap` | 環境の罠・再学習を防ぐ事実(`--max-turns` / `lsof -i` / `tailscale serve` / `proxy_headers`) | 種類A |
| `Invariant` | 壊してはいけない不変条件(削除しない=アーカイブ / DB は派生 / Verifier 別モデル) | 種類A(事実の記述) |
| `Reference` | 外部資料・ダッシュボード・チケットへのポインタ | 種類A |
| `Decision` | なぜそうしたか・信用できるか・どこで壊れるか・学び | **種類B(人間のみ)** |

OKF は未知 type を許容するため、必要に応じて追加してよい(中央登録不要)。

# 2 バンドル分離(public / private)

loop は engine(public code)/ data(private 契約)の 2 repo 構成。知識もこの境界を踏襲する。

- **engine `Knowledge/`(公開)** — エンジンの設計知識・環境の罠・不変条件。**公開してよい知識のみ**。
- **private `Knowledge/private/`(非公開)** — `data/hosts/<host>/Knowledge` への gitignored シンボリックリンク。
  run 横断の学び(`learnings/`)・人間の判断(`decisions/`・種類B)。**public engine に push しない**。

> engine バンドルに data の非公開知識を混入させない(public push の不変条件)。
> 橋渡しリンク `Knowledge/private` は **必ず engine の .gitignore に入れ**、public 履歴に commit しない。

# 種類A/B の死守(書き込みポリシー)

- 種類A(事実: `System`/`Trap`/`Invariant`/`Reference`、`log.md` 追記)は runner / Author が**自動**で読み書きしてよい。
- 種類B(`Decision`)は **人間のみ**。`Decision` 概念は frontmatter に `judgment: human` を必須化する。
- runner の知識書き込み・コミット経路は `judgment: human` を持つファイルと `decisions/` 配下を**物理的に除外**する。
- GUI・runner・API は判断を生成・要約・推奨・自動入力しない(loop 絶対原則 1)。
- 対話 Claude セッションが `Decision`/`decisions/` を自動生成しないのは**規約遵守**(harness 強制ではない)。

# anchor 解決規則(「同一の場所」の実体)

「同一の場所」を cwd 相対ではなく、loop engine checkout を錨にした絶対パス解決として定義する。

- **錨 `$LOOP_HOME`** = loop engine checkout のパス(env で配る。未設定時は `loop.toml` を持つ既知パスにフォールバック)。
- **普遍規則**(cwd に依らず同じ結果):
  - engine 公開バンドル = `$LOOP_HOME/Knowledge`
  - data 非公開バンドル = `$LOOP_HOME/<[data].dir>/Knowledge`(`[data].dir` は `$LOOP_HOME/loop.local.toml` を 1 行読む。未設定なら `data`)
- engine repo を cwd にしたセッションは橋渡しリンク `Knowledge/private` で単一ツリーとして辿れる(利便)。
  対象 repo cwd / worktree / 他 cwd のセッションはリンクを見られないので、上の解決規則で直接 data バンドルへ届く。
- runner も同じ解決(`load_config()` の `[data].dir` マージ)で両バンドルを絶対化し Author/Implementer に渡す。

# 命名・frontmatter・log は submodule の CONVENTIONS.md に従う

kebab-case / `type` 必須 / `timestamp` は ISO 8601 / リンクはバンドル基準絶対パス / log.md は新しい順 1 行追記。
