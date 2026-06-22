# loop 記憶システム改善仕様 — OKF 知識バンドルの導入

> loop の「記憶」を [OKF (Open Knowledge Format) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) の
> 知識バンドルに統一し、**loop runner が回すセッション(worktree)でも、loop engine repo を開いた通常セッションでも、
> さらに対象 repo を直接弄る通常セッションでも、同じ解決規則・同じ規約で知識を読み書きできる**ようにするための設計仕様。
> color-recollection の `Knowledge/` バンドルと `okf-conventions`(中央集権規約)を参照元とし、
> loop 固有の事情(2 repo 分離・種類A/B・worktree 実行・複数 PC)に合わせて拡張する。

---

## 1. 背景 — なぜ統一が要るか

loop の「記憶」は現状 **3 つの面に分断**されており、セッション形態によって見える記憶が変わる。

| 面 | 置き場所 | 弱点 |
|---|---|---|
| グローバル auto-memory | `~/.claude/projects/<cwd-path-hash>/memory/`(`MEMORY.md` + 個別 `.md`) | **cwd パスにバインド**(実測: project ごとに別ディレクトリが切られる)。loop runner が回す役は対象 repo の worktree(別パス)で動くため、この memory を参照できない/別 bundle になる → **セッション形態で記憶が割れる** |
| engine 設計知識 | `CLAUDE.md` / `docs/`(長文の散文) | 「環境の罠」「絶対原則」が長文に埋もれ、概念単位で引けない・diff の単位が粗い |
| run の判断 | `data/hosts/<host>/runs/*/review-notes.md`(種類B) | OKF とは別形式。run の学びと engine 知識が別規約で、横断検索・リンクができない |

OKF は知識を **YAML frontmatter 付き Markdown のディレクトリツリー**で表現する最小規約で、repo 内に置けば
git で diff・共有でき、概念単位(1 ファイル = 1 概念)で引ける。これは loop の
**「ファイルが真実(file-based contract)」原則そのもの**であり、思想的に完全に整合する。

**狙い**: 記憶を projects 束縛の auto-memory への依存から外し、**OKF バンドルを唯一の知識源**にする。
ただし「同一の場所」を **cwd 相対パスで実現できるのは限られたセッションだけ** であることを正面から扱う(§6)。
対象 repo の worktree や、loop engine 以外の cwd から開いた通常セッションは cwd 相対では届かないため、
**loop engine checkout を錨(anchor)にした絶対パス解決規則**を「同一の場所」の実体とする。

---

## 2. 目標 / 非目標

**目標**
- loop に関わる全セッションが、**同一の 2 バンドル(engine 公開 / data 非公開)を同一規約・同一解決規則で**読み書きする。
  - 「同一規約」= `conventions/`(OKF + loop オーバーレイ)。
  - 「同一解決規則」= §6.3 の anchor(`$LOOP_HOME`)起点の決定論的パス解決。cwd に依らず同じ 2 バンドルに着地する。
- 知識を概念(1 ファイル = 1 概念)に分解し、diff・横断リンク・progressive disclosure を可能にする。
- 既存の不変条件(2 repo 分離 / 種類A・B / file-based contract / DB は派生)を一切壊さない。

**非目標**
- 知識を SQLite/DuckDB の一次データにすること(知識はファイルが真実。索引が要るなら派生として後付け)。
- 判断(種類B)の自動生成。GUI・runner は判断を生成・要約・推奨しない原則を維持する。
- color-recollection 等、既存 OKF プロジェクトの構成変更(本仕様は loop へ後から重ねる)。
- **対象 repo の知識バンドルへの混入**。loop の学び・判断を対象 repo(color-recollection 等)の `Knowledge/` に書き込まない(§6.4 で却下した理由)。

---

## 3. 設計判断(決定事項)

質問で止めず、loop の文書化済み不変条件と実コードを根拠に以下を**決定**する。

### D1. OKF v0.1 + 共有 `okf-conventions` submodule を採用する
void2610 の全プロジェクトで規約は中央集権(`okf-conventions`)・知識は各 repo 所有、という既存方針に loop も乗る。
`Knowledge/conventions/` は **読み取り専用 submodule**(実在: `github.com/void2610/okf-conventions.git`、color-recollection が既に使用)。
規約改善は中央 repo で行い、submodule ポインタを進める。

### D2. 2 repo 分離に従い、知識バンドルを **2 面**に置く
loop は engine(public code)/ data(private 契約)の 2 repo 構成。知識もこの境界を踏襲する。

- **engine `Knowledge/`(公開)** — エンジンの設計知識・環境の罠・不変条件・運用ノウハウ。
  現状 `CLAUDE.md` / `docs/` に散在しているものを概念化する。**公開してよい知識のみ**。
- **data `Knowledge/`(非公開)** — run 横断の学び・判断(種類B)。`review-notes.md` の知見をここへ概念として蓄積・リンクする。
  **data の内容は public engine に push しない**不変条件をそのまま継承する。

> 根拠: 「2 repo を取り違えない / data を含む履歴を public に push しない」(CLAUDE.md §6)。
> 公開してよい一般知識(罠・不変条件)と、run 固有の非公開判断を物理的に分けることで誤混入を構造的に防ぐ。

### D3. 種類A/B の境界を OKF の type にマッピングする
loop の絶対原則「種類A は全自動 / 種類B(判断)は絶対に自動化しない」を OKF 上でも死守する。

| 区分 | OKF での扱い | 誰が書くか |
|---|---|---|
| 種類A(事実) | `System`(コード紐づき概念)・`Trap`(環境の罠)・`Invariant`・`Reference`、`log.md` 追記 | runner / Author が**自動**で読み書き可 |
| 種類B(判断) | `Decision`(なぜそうしたか・信用できるか・どこで壊れるか・学び) | **人間のみ**。GUI・runner は生成/要約/推奨しない |

`Decision` 概念は frontmatter に `judgment: human` を必須化し、runner の書き込み経路から除外する(§7)。

### D4. auto-memory は「移行 + 薄い入口」に縮退する(ただしソフトな規約)
projects 束縛の auto-memory を**プロジェクト知識の一次置き場にしない**。
既存の memory ファイル(`loop-refactor-2026-06` / `no-repo-doc-data-conflict` / `just-app-tailscale-path`)は
`Knowledge/` の概念へ移行する(§9)。auto-memory に残すのは「複数プロジェクト横断の純粋にユーザー個人な事実」だけ。

> **注意(ハード機構ではない)**: auto-memory は Claude Code harness の機能で、`MEMORY.md` は cwd に関係なく
> 自動ロードされ、harness は書き込みも促し続ける。**harness 側に書き込みを止めるスイッチは無い**ため、
> この縮退は構造的措置ではなく **規約遵守(global CLAUDE.md に「loop 知識は OKF バンドルへ」と明記)頼み**である。
> 実体は運用規約だと理解した上で運用する。

### D5. 読み取りの入口を **global CLAUDE.md** に一本化する(anchor の周知)
入口は cwd に関係なくロードされる **global `~/.claude/CLAUDE.md`** に置く。これが唯一、loop engine 以外の
cwd(対象 repo 等)から開いた通常セッションにも届く入口になり得るため。

- global CLAUDE.md に OKF snippet(`OKF:START`〜`OKF:END`)を追記し、次の 3 つを明示する:
  1. anchor `$LOOP_HOME`(loop engine checkout)と §6.3 の解決規則(2 バンドルの絶対パスの出し方)。
  2. 「`Knowledge/` を読み書きする前に `<engine>/Knowledge/conventions/CONVENTIONS.md` を読め」。
  3. 「Claude は `Decision`/`decisions/` を自動生成しない(種類B = 人間)」。
- **run セッション**: runner が Author に解決済みの 2 バンドルパス + `index.md` を起点とする progressive disclosure を行わせる(§6.1)。

> 旧版は snippet を *engine の* `CLAUDE.md` に置いていたが、それは engine repo を開いたときしかロードされない。
> 対象 repo セッション(§6 の (b))を入口に乗せるには global に置くのが必須。engine CLAUDE.md には
> 同じ規則を再掲してもよいが、正本は global とする。

---

## 4. ディレクトリ構成

```
engine(public)/
├── CLAUDE.md                       # 任意: global の OKF snippet を再掲(正本は global ~/.claude/CLAUDE.md)
├── .gitignore                      # `Knowledge/private` を ignore(data 知識を public に混入させない)
└── Knowledge/                      # 公開知識バンドル
    ├── index.md                    # 目次 + okf_version: "0.1"。/private/ へリンク
    ├── log.md                      # 更新履歴(新しい順)
    ├── conventions/                # submodule -> okf-conventions(読み取り専用)
    ├── conventions-loop.md         # loop 固有オーバーレイ(submodule を編集せず追加規約を持つ・§8)
    ├── systems/                    # 実装と紐づく概念(resource: で runner.py 等を指す)
    ├── traps/                      # 環境の罠(--max-turns / lsof / tailscale / proxy_headers 等)
    ├── design/                     # 設計判断・不変条件(公開可のもの)
    └── private  ─────────────┐    # gitignored シンボリックリンク(§6.4・engine セッションの単一ツリー化の利便)
                              │
data(private / gitignored)/    │
└── hosts/<host>/             │
    └── Knowledge/  ◀────────┘    # 非公開知識バンドル(private はここを指す)
        ├── index.md
        ├── log.md
        ├── decisions/              # 種類B: run を読んだ人間の判断(judgment: human)
        └── learnings/              # run 横断の学び(review-notes から蓄積)
```

> **バンドル名は `Knowledge/`(チルダ無し)**。color-recollection も実体は `Knowledge/`(`.gitmodules` の
> submodule *名* に旧称 `Knowledge~/conventions` が残るが `path = Knowledge/conventions`)。loop は非 Unity なので
> import 除外の `~` は不要で、cr の現状とも一致する。
>
> **要点**: 非公開バンドルは host 固有・gitignored の data repo にある。engine バンドル直下の
> gitignored シンボリックリンク `Knowledge/private` がそこを指すのは、**engine repo を cwd にしたセッションが
> 単一の `Knowledge/` ツリーだけで public/private 双方を辿れる利便**のため(§6.4)。
> **対象 repo cwd / 他 cwd のセッションはこの symlink を見られない**ので、それらは §6.3 の anchor 解決規則で
> 直接 data バンドルへ届く。symlink は必須依存ではない。git 上は 2 repo のまま分離される。

---

## 5. type 語彙(loop 向け拡張)

`okf-conventions` の `CONVENTIONS.md` はゲーム向け語彙(`Character`/`Location`/`Faction`…)が中心。
loop はツールなので、submodule を編集せず `conventions-loop.md`(§8 のオーバーレイ)で以下を追加宣言する。

| type | 用途 | 区分 |
|---|---|---|
| `System` | 実装システム(`resource:` で `runner.py` / `loopdb.py` / `webapp/` 等を指す) | 種類A |
| `Trap` | 環境の罠・再学習を防ぐ事実(`--max-turns` / `lsof -i` / `tailscale serve` / `proxy_headers`) | 種類A |
| `Invariant` | 壊してはいけない不変条件(削除しない=アーカイブ / DB は派生 / Verifier 別モデル) | 種類A(事実の記述) |
| `Reference` | 外部資料・ダッシュボード・チケットへのポインタ | 種類A |
| `Decision` | なぜそうしたか・信用できるか・学び(**人間のみ**) | 種類B |

OKF は未知 type を許容するため、必要に応じて追加してよい(中央登録不要)。

---

## 6. 読み取りの統一(配線)— セッションは cwd で 3 つに分かれる

「同一の知識」を実現する手段は **セッションの cwd** によって変わる。cwd 相対で届くのは限られたケースだけで、
それ以外は **anchor 解決規則**(§6.3)で同じ 2 バンドルに着地させる。

| セッション | cwd | engine 公開知識への到達 | data 非公開知識への到達 |
|---|---|---|---|
| (a) engine repo の通常セッション | engine root | `./Knowledge`(cwd 相対) | `Knowledge/private` symlink or anchor 規則 |
| (b) 対象 repo の通常セッション(loop 非経由) | 対象 repo の checkout | anchor 規則(loop 知識が要るときのみ) | **anchor 規則のみ**(symlink 不可) |
| (c) runner 駆動の run | 対象 repo の worktree | runner が解決済み絶対パスを Author に渡す | 同左 |

> **(b) が本仕様の主眼**。対象 repo に関する過去 run の学び(data 側 `learnings/`)を、loop を経由しない
> 通常セッションからも同じ場所として読めるようにする。対象 repo の cwd からは symlink も engine CLAUDE.md も
> 効かないため、§6.3 の anchor 解決規則 + §D5 の global CLAUDE.md 入口の 2 点が必須になる。

### 6.1 run セッション(Author 起点の progressive disclosure)
- runner が §6.3 の規則で **engine / data 両バンドルの絶対パス**を解決し、Author に渡す。
  worktree の cwd は対象 repo の checkout なので、engine の `Knowledge/` は **cwd 相対では届かない**
  (= §10 の通り「worktree に自動で付いてくる」のではなく、runner が明示的に絶対パスを渡すから届く)。
- Author は repo 調査フェーズで `index.md` を読み、タスクに関連する概念だけを辿る。
  読んだ概念の `resource:`(コードパス)を Implementer 向けプラン(`tasks/plans/<id>.md`)に引き継ぐ。
- data 側は種類B の判断を含むので、Author には「読むだけ・判断を真似しない」を明示する。

### 6.2 loop.toml の宣言
```toml
[knowledge]
# 知識バンドルのルート(複数可)。runner が Author/Implementer に読ませる入口。
# 相対パスは loop engine root(= $LOOP_HOME)基準で絶対化する。
# data 側は _data_dir()(local 設定マージ)経由で host を解決し、マシン間で衝突しない。
bundles = ["Knowledge", "<data-dir>/Knowledge"]   # <data-dir> は [data].dir を runner が展開
```
- 未指定なら `["Knowledge"]` にフォールバック(後方互換)。
- runner は `load_config()` でこれを読み、ROOT 基準で絶対化して Author へ渡す(§6.1)。

### 6.3 anchor 解決規則(この仕様の肝・cwd 非依存・決定論)
「同一の場所」を **cwd 相対ではなく、loop engine checkout を錨にした絶対パス解決**として定義する。
これは runner が既に `_data_dir()` でやっている解決(`load_config()` で `loop.local.toml [data].dir` をマージ)を、
**data だけ・runner 限定 から、両バンドル・任意 cwd へ一般化**したものである。

- **錨 `$LOOP_HOME`** = loop engine checkout のパス。**nix-darwin で宣言的に env としてエクスポート**し、
  どのセッション(どの cwd)でも参照できるようにする(ユーザーの宣言的パッケージ管理方針に沿う)。
- **普遍規則**(cwd に依らず同じ結果):
  - engine 公開バンドル = `$LOOP_HOME/Knowledge`
  - data 非公開バンドル = `$LOOP_HOME/<[data].dir>/Knowledge`(`[data].dir` は `$LOOP_HOME/loop.local.toml` を 1 行読む。未設定なら `data`)
- この規則を §D5 の global CLAUDE.md snippet に明記する。**runner も通常セッションも、engine repo にいても対象 repo にいても、同じ 2 行の lookup で同じ 2 バンドルに着地する**。symlink もコードも不要。

### 6.4 2 repo をまたぐ読み書き — symlink は (a) の利便、anchor が普遍解
非公開バンドルは engine から gitignore された別 repo・host 固有の可変パスにある。到達手段は 2 段に分ける。

**(a) anchor 解決規則(普遍・必須・runner 非依存)** = §6.3。**全セッションの正規経路**。
リンクの有無に関係なく、`$LOOP_HOME` 起点で 2 バンドルを一意に解決できる。

**(b) 橋渡しリンク(engine repo セッションの単一エントリ点・利便)**
engine バンドル直下に gitignored シンボリックリンク `Knowledge/private -> <data-dir>/Knowledge` を張る。
- これにより **engine repo を cwd にしたセッションが、単一の `Knowledge/` だけを入口にして** public/private 双方を辿れる(root `index.md` が `/private/index.md` へリンク)。
- リンクは **setup 時に生成**(`just knowledge-link`)。host 固有 data-dir を解決して `ln -sfn`。`just app` 起動の不変条件処理にも組み込む。
- リンク自体は **engine の .gitignore に入れ、public 履歴に絶対入れない**(2 repo 分離)。
- **対象 repo cwd / worktree / 他 cwd のセッションはこのリンクを見られない**。それらは (a) の anchor 規則で直接 data バンドルへ届く。**リンクは必須依存ではない**。

> **対象 repo へのミラーは行わない(非目標)**。「対象 repo の `Knowledge/learnings/` に loop の学びを書けば cwd 相対で
> 届く」案は却下する。理由: ① 対象 repo の契約を不変に保つ原則に反する ② 種類B(判断)が公開され得る対象 repo に
> 漏れ 2 repo 分離を崩す ③ 対象 repo 本来の知識(cr ならゲーム lore)と混ざる。**学びは data 側に置いたまま
> anchor 経由で読む**のが正しい。

**(c) 書き込みの行き先と確定(git 境界の維持 + 明示コミット)**

書き込み先の実体は、symlink 経由でも anchor 解決でも **物理的に data repo 内**(`<data-dir>/Knowledge/...`)に着地する。
よって engine の `git status` には現れず、public/private の git 境界は維持される。

> **重要(実コードに照らした事実)**: 既存の `auto_commit` は知識を**拾わない**。`auto_commit(repo, paths, msg)`
> (`runner.py:560`)は **渡された `paths` だけを `git add` する**(`-A` ではない)。全 15 箇所の呼び出しは
> `runs/` / `tasks/` / `review-notes.md` 等の契約ファイルのみを渡し、`Knowledge/` を渡す箇所は皆無。さらに
> `auto_commit` は**全て DATA 宛て**で、engine 宛ての呼び出しは存在しない。→ **知識への書き込みを確定させる
> 経路が現状ゼロ**で、放置すると working tree に未コミットで残る(種類A の「コミットまで自動」が知識面で穴になる)。

経路別に確定段を設ける:

- **runner 駆動の知識更新(種類A・自動)**: 知識専用の明示コミット段を新設する(§7 ガード下)。
  - **private(data)側**: 書き込み先を **実パス `<data-dir>/Knowledge/...` に `Path.resolve()` で解決してから**
    `auto_commit(DATA, [<解決済みパス>], msg)` に渡す(symlink パスのままだと `p.relative_to(DATA)` が失敗する)。
    既存の `_DATA_COMMIT_LOCK`(RLock = 再入可能なので resolve 後の再取得でデッドロックしない)・`loop.db` 非混入はそのまま効く。
  - **engine(public)側**: engine-root 宛て `auto_commit(<engine-root>, [Knowledge/...], msg)` を**新設**し、
    msg は `knowledge:` 接頭辞でコード履歴と分離。**push は §6 の 2 repo 分離チェックに従い自動 push しない**。
  - 呼び出し位置は run 終了処理(`_finalize_run` 近傍、`runner.py:1418`)。その run が触れた知識パスを集めて呼ぶ。
    `Decision` / `decisions/` 配下は §7 ガードで private 側コミット対象から除外する。

- **loop外セッションの知識更新(人間 / 対話 Claude)**: **§6.4c の runner コミット段には乗らない**。
  人間または対話セッションが知識を書いたら、**2 repo 分離を守って手で commit する**(engine 宛てか data 宛てか判定)。
  事故防止のため `just knowledge-commit <path>...` を用意し、`resolve()` してパスの所属 repo を判定 → 正しい repo に
  `knowledge:` 接頭辞で commit(engine は自動 push しない)するヘルパを 1 つ持たせる。種類B(`Decision`)は人間が書くので
  このヘルパでも commit してよい(runner ガードと違い、人間経路には種類B 制約をかけない)。

書き込みの種類A/B ガード(§7)は **パスではなく `decisions/` 配下と `judgment: human` で判定**するため、
symlink 経由でも anchor 経由でも同じく効く。

### 6.5 Fleet(複数 PC)の限界
filesystem 解決(§6.3)は **このホストの data バンドルにしか届かない**。peer(例: m1server)の `learnings/` は
このマシンのディスクに無いため、**loop外の素のセッションからは読めない**。クロスホストで読むなら稼働中 backend の
`/api` + peer プロキシ経由(= ファイル真実の上の API レンズ)しかない。**単一ディスク運用では非問題**なので、
本仕様の FS 解決は self host の 2 バンドルに限定し、**クロスホスト読みは FS 解決の対象外**と明記する。

---

## 7. 書き込みポリシー(種類A/B の死守)

| 経路 | 書ける概念 | 禁止 |
|---|---|---|
| runner / Author(種類A・自動) | `System` / `Trap` / `Invariant` / `Reference` の**事実更新**、各バンドルの `log.md` 追記、`timestamp` 更新 | `Decision` の生成・既存 `Decision` の書き換え |
| 人間(種類B・対話セッション含む) | すべて。特に `data/.../decisions/` の判断 | — |

実装上のガード(runner 経路のみ。人間経路には課さない):
- `Decision` 概念は frontmatter に `judgment: human` を必須化。
- runner の知識書き込みヘルパは `judgment: human` を持つファイル、および `decisions/` 配下を**書き込み・コミット対象から除外**する(誤って判断を生成しても物理的に弾く)。
- GUI は従来どおり `## 判断`/judgment フォームを空で出す。OKF 化後も判断の入力面は人間専用のまま。
- **対話 Claude セッションが種類B を自動生成しない**のは §D4 同様 **ソフトな規約**(global CLAUDE.md で縛る)。harness レベルの強制ではない。

> 根拠: 絶対原則 1(GUI・runner・API は判断を生成・要約・推奨・自動入力しない)。
> 事実要約(systems/traps の更新と log 追記)までは種類A として自動化してよい。

---

## 8. conventions submodule の扱い(編集禁止 + オーバーレイ)

- `Knowledge/conventions/` は `okf-conventions` の submodule で**読み取り専用**。loop からは編集しない。
- loop 固有の追加語彙・規約は `Knowledge/conventions-loop.md`(engine 所有・編集可)に置く。
  ここに §5 の type 表と、「2 バンドル(public/private)分離」「種類B は `judgment: human`」「anchor 解決規則」を明記する。
- 規約本体の改善が要るときは中央 `okf-conventions` に投げ、submodule ポインタを進める(全プロジェクト一括反映)。

---

## 9. auto-memory からの移行

現在 `~/.claude/projects/-Users-shuya-Documents-GitHub-loop/memory/` にある概念を以下へ移す。

| 既存 memory | 移行先 | type |
|---|---|---|
| `just-app-tailscale-path` | `Knowledge/traps/just-app-tailscale-path.md` | `Trap` |
| `no-repo-doc-data-conflict` | `Knowledge/design/no-repo-doc-data-conflict.md`(矛盾の判断含む) | `Decision`(公開可なら engine design、判断性が強ければ data 側) |
| `loop-refactor-2026-06` | `data/.../Knowledge/learnings/loop-refactor-2026-06.md` | `Decision`/`Reference` |

- `MEMORY.md` インデックスは縮退し、loop 固有の行は OKF バンドルへ移したうえで「`$LOOP_HOME/Knowledge/index.md` を見よ」のポインタに置換。
- auto-memory に残すのは複数プロジェクト横断の純ユーザー事実のみ。
- 移行は**事実(Trap/System)は自動でよい**が、判断(Decision)を含むものは人間が確認して配置する(種類B)。

---

## 10. worktree / serial repo での可搬性

> **訂正(旧版の誤り)**: 旧版は「`Knowledge/` は repo の一部なので worktree チェックアウトに自動で付いてくる」と
> していたが、これは誤り。runner の worktree は **対象 repo の checkout**(`cwd=str(wt)`、`runner.py:624`)であり、
> **engine の `Knowledge/` は固定絶対パス(`$LOOP_HOME/Knowledge`)に在って worktree には付いてこない**。
> engine 知識が Author に届くのは「repo の一部だから」ではなく、runner が §6.3 の規則で**絶対パスに解決して
> プロンプトで渡すから**である。「自動で付いてくる」が成り立つのは *対象 repo 自身の* `Knowledge`(本仕様の対象外)だけ。

- worktree run でも serial-mode run でも、runner は §6.3 の anchor 解決規則で engine / data 両バンドルを
  絶対パスで解決し Author に渡す。**cwd(worktree か repo 本体か)に依らず同じ 2 バンドルに着地**する。
- **橋渡しリンク `Knowledge/private` は gitignored かつ engine バンドル直下なので、対象 repo の worktree には現れない**。
  runner 経路は (a) の解決規則だけで完結し、リンクに依存しない。
- serial-mode repo(Unity 等)でも同様。`enter_serial`/`leave_serial` の前後で runner が解決するパスは不変。

---

## 11. 適合性(これだけは守る)

OKF v0.1 + `CONVENTIONS.md` の適合性に、loop の不変条件を上乗せする。

1. 全非予約 `.md` がパース可能な YAML frontmatter を持ち、空でない `type` がある。
2. `index.md` / `log.md` は OKF 規約の形式に従う。
3. `Decision` 概念は `judgment: human` を持ち、runner の書き込み経路から除外される。
4. engine バンドルに **data の非公開知識を混入させない**(public push の不変条件)。
   橋渡しリンク `Knowledge/private` は **必ず engine の .gitignore に入れ**、public 履歴に commit しない。
5. **「同一の場所」= anchor 解決規則(§6.3)**。cwd に依らず `$LOOP_HOME` 起点で 2 バンドルを一意に解決する。
   symlink は engine repo セッションの利便であって**必須依存にしない**(リンク欠如時は解決規則にフォールバックできること)。
6. `loop.db` 同様、知識バンドルから派生索引を作る場合も **ファイルが真実**で、索引は再生成可能であること。

その他はソフト指針。欠損フィールド・未知 type・壊れリンク・index 欠如で処理を止めない(consumer は寛容)。

---

## 12. 実装タスク(段階導入)

1. **engine に `Knowledge/` を scaffold** — `okf-add.sh` 相当で `conventions` submodule + index/log + `conventions-loop.md`。
2. **anchor `$LOOP_HOME` を宣言** — nix-darwin で env を宣言的にエクスポート(全 cwd から参照可に)。
3. **global `~/.claude/CLAUDE.md` に OKF snippet 追記**(`OKF:START`〜`END`)— anchor + §6.3 解決規則 + conventions 先読み + 種類B 禁止を明記(§D5)。engine CLAUDE.md には任意で再掲。
4. **散文知識の概念化** — `CLAUDE.md §4 環境の罠` → `traps/*`、`§1 絶対原則` → `design/invariants/*`、主要モジュール → `systems/*`。
5. **data に `Knowledge/` を scaffold**(host ごと)+ `decisions/` `learnings/`。
6. **橋渡しリンク + 解決規則**(§6.3/§6.4) — `Knowledge/private` を engine `.gitignore` に追加し、
   `just knowledge-link`(host 固有 data-dir を解決して `ln -sfn`)を新設。`just app` の起動不変条件処理にも組み込む。
7. **loop.toml `[knowledge]` 追加** + `runner.load_config()` で解決、ROOT 基準で絶対化して Author へ受け渡し。
8. **runner 書き込みガード** — `judgment: human` / `decisions/` を除外する事実専用ヘルパ。
9. **知識コミット段(§6.4c)** — 既存 `auto_commit` は知識を拾わないため新設する。private は symlink/解決パスを
   `resolve()` してから `auto_commit(DATA, …)`、engine は engine-root 宛て `auto_commit` を新設し `knowledge:`
   接頭辞で確定(engine は自動 push しない)。`_finalize_run` 近傍で run が触れた知識パスを集めて呼ぶ。
10. **`just knowledge-commit` 新設** — loop外セッションの知識更新を 2 repo 分離を守って commit するヘルパ(§6.4c)。
11. **auto-memory 移行**(§9)。
12. **検証** — (a) **対象 repo cwd の通常セッション**が anchor 解決規則だけで data 概念を読めること、
   (b) worktree run が解決規則だけで同じ概念に届くこと、(c) `Decision` が runner から書けないこと、
   (d) `Knowledge/private` が engine の `git status`/履歴に一切出ないこと、
   (e) **run が触れた知識が §6.4c のコミット段で実際に commit され、未コミットで残らないこと**、
   (f) symlink を消しても anchor 解決規則で両バンドルに届くこと、を実 run / 実セッションで確認。

---

## 13. 未解決 / 今後

- **索引(任意)**: 概念数が増えたら `loop.db` に knowledge テーブルを派生として持たせ、Web で横断検索する案。あくまで派生(再生成可能)。
- **Fleet クロスホスト読み(§6.5)**: peer の `learnings/` を loop外セッションから読むには backend API + peer プロキシが要る。filesystem 解決の対象外。必要になったら `/api/knowledge`(peer 中継対応)を検討。`learnings/` 自体は data private repo で全 host に伝播するので、各 host で `git pull` 済みなら self ディスクに揃う点は留意(同期タイミング依存)。
- **`no-repo-doc-data-conflict` の解消**: 移行のついでに、docs の no-repo 撤去と実データの矛盾(既知の未解決)を `Decision` として明文化するか判断する(種類B = 人間)。
- **anchor の発見性**: `$LOOP_HOME` を env で配るのが第一候補だが、未設定環境向けに「`loop.toml` を持つ既知パス」を marker とするフォールバックも検討余地(別 PC・CI 等)。
