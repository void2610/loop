# CLAUDE.md — loop リポジトリ作業ガイド

> このファイルは、**ユーザーと議論しながら loop(Loop Engineering 計測配管)を改善していく Claude Code 自身**への申し送りである。
> 並列サブエージェント向けの指示ではない。グローバル `~/.claude/CLAUDE.md`(コメント規約・日本語・ユーザーは専門家)に**上乗せ**する、このリポジトリ固有の知識・原則・罠をまとめる。
> 設計の網羅ドキュメントは [docs/](./docs/)、設計メモ(非公開)は `data/plans/` にある。ここは「作業する前に思い出すべきこと」。

---

## 0. まず把握

- これは **Claude Code を headless で回すループの計測・統制層**。実行系(`claude -p` / `git worktree`)はネイティブに委ね、突き合わせ層(run 記録・証拠・3役 Sub-agents・SQLite/DuckDB・Web UI)を自作している。
- **2 リポジトリ構成**: このリポジトリ(engine)は**コードだけの公開 repo**。契約データ(目標契約・run 記録・証拠・判断・設計メモ)は **`data/` 配下の別 private git repo**。engine は `data/` を `.gitignore` する。runner / API の auto-commit は `data/` 側へ行く。
- リモート: engine = `void2610/loop`(public)/ data = `void2610/loop-data`(private)。両方 `main`。

---

## 1. 絶対原則(壊すな)

1. **種類A は全自動 / 種類B(判断)は絶対に自動化しない。**
   - 種類A = dispatch・実行・証拠収集・コミット・インデックス・表示。
   - 種類B = 人間が run を読んで「信用できるか/どこで壊れるか/次に自動検証へ入れるべきチェック/学び」を書く。
   - **GUI・runner・API は判断を生成・要約・推奨・自動入力しない。** 事実要約(runner が作る)と証拠表示まで。`## 判断` セクション・judgment フォームは常に空で出す。
2. **ファイルが真実(file-based contract)。** `data/tasks/*.md`(目標契約)+ `data/runs/<id>.md`(run 記録)+ 証拠 + `review-notes.md` + git。`loop.db`(SQLite)は**派生**で `just reindex` で完全再生成できる(`rm loop.db && reindex` で壊れないこと=不変条件)。DuckDB は分析レンズ。Web は契約ファイルを編集する面で独自ストアを持たない。
3. **削除しない=アーカイブ。** ログは資産。タスク/run は `archived` フラグで UI から隠すだけ(`set_task_archived` / `set_run_archived`)。**削除エンドポイント・削除ボタンを復活させない。**
4. **Verifier は Implementer と別モデル必須。** 同一だと起動時警告。read-only 役(Explorer/Verifier)と生成は変更系ツールを禁止(下記§4)。
5. **検証の死角を作らない。** 自動で pass/fail と言い切れない時は `handoff`(人間へ)。"done" は自己申告であって証明ではない — 変更は実際に動かして証拠で示す。

---

## 2. リポジトリ構成

```
engine(このリポジトリ / public):
  loop.toml            [loop]/[agents]/[repo]/[repos]/[data]
  runner.py            一本道ランナー: Implementer/Verifier / revise / 生成(gen) / status / archive(種類A)
  loopdb.py            SQLite インデックス層(MD 派生・再生成可能)
  webapp/
    main.py            ASGI 組み立て(痩せた層)。/api(JSON+SSE)のみ
    api/*.py           JSON API(router 自動収集)。runs / tasks / monitor / stats / dispatch / meta
    auth.py schemas.py util.py
  web/                 Next.js(App Router)+ TS + Tailwind + shadcn/ui = 唯一の UI
  stats.py + queries/  DuckDB 分析
  .claude/skills/      SKILL.md / task-author(プロンプト→目標契約の生成スキル)
  docs/                公開ドキュメント

data/(別 private repo / engine からは .gitignore):
  tasks/<id>.md  tasks/plans/<id>.md(Author 生成の実装プラン)  runs/<id>.md + runs/<id>/  review-notes.md  plans/(設計メモ)  loop.db
```

> **実行機構(現行)**: 全役は **`RoleSession`(`claude -p --input-format/--output-format stream-json` の永続双方向セッション)**で動く。one-shot(`-p <prompt>`)と `--resume` 再 spawn は撤去。追加指示(revise / 人間介入)はすべて `send()` で**同一セッションへ user メッセージ注入**に一本化。`run_role` はその単発ラッパ(Verifier 等)。
> **人間介入(awaiting)= 責務分離**: ①**実装中**の方針疑問/権限不足は Implementer が `NEEDS_HUMAN:` 合図でターンを区切る → `_drive_implementer` が **Verifier より前に** `await_human` で人間へ(主経路)。②**実装後**の結果/テスト欠陥は Verifier の責務で `revise` 自動修正(人間不要)。③ Verifier の handoff / revise 上限超過は**最後の安全網**としてだけ人間へ。いずれも `runs/<id>/inbox.jsonl` 待ち(`intervention_timeout_seconds`、超過で handoff)。Web の `/runs/<id>/live` が `intervention` を出し `POST /api/runs/<id>/message` で同一セッションへ注入。**GUI は事実表示のみ・選択肢/判断を生成しない**。
> **Verifier は inbox の人間回答も受け取る**(`_inbox_human_input`)。人間の承認/指示は「実装者の自己申告」ではなく**人間(種類B)の権威**なので、「人間承認が要る/ポリシー決定」系の基準はこれに照らして判定する(承認の証跡が worktree に無くても誤 handoff しない)。実装が承認内容と一致するかは引き続き diff/ファイルで検証。
> **run の役割フロー(現行)**: `Author プラン → Implementer(自己テストまで)→ 決定論ゲート → Verifier 監査 →(revise / 人間介入は同一セッションへ send)→ [promote: pass のみ]`。
> - **promote 段(`promote_on_pass`、既定 false)**: run=pass の成果を PR 化し、**GitHub CI + Copilot レビュー**が green になるまで Implementer を差し戻して回す(種類A)。green でも **`pass` にせず `awaiting-merge`** で確定(真の完了は人間の PR マージ後)。**merge は人間(自動 merge しない)**。上限超過は handoff。
> - **真の完了 = PR マージ**: `check_pr_merge`(Web `GET /api/runs/<id>/pr` / CLI `runner.py merges`)が gh で PR 状態を見て、**マージ済みなら verdict を `pass` へ昇格**。Runs 一覧は `awaiting-merge` を「PR マージ待ち」カードで強調(PR 状態 + PR リンク)。証拠は `promote.roundN.json` / `promote.json`、PR URL は run MD の `pr_url`。
> - **Author = Explorer 統合**: 生成時に repo を read-only 調査し詳細プランを `tasks/plans/<id>.md` に出力。run 時はこのプランを Implementer に渡す(run 時 Explorer は廃止。プラン無しの手動タスクはプラン無しで Implementer 直行)。repo は常に在る前提(no-repo 分岐は撤去)。
> - **revise ループ**: Verifier は `pass/fail/revise/handoff`。`revise` は `required_changes` を付けて Implementer に差し戻し、**同一セッションを `--resume` で継続**(前文脈保持)。回数上限 `loop.implementer_revise_rounds`(既定 2)。上限超過でも pass にせず handoff(死角を作らない)。決定論ゲートは床のまま(`test=fail → fail`、空通りテストは Verifier が revise/handoff)。
> - **repo 単位の serial / parallel(worktree 不向き repo 向け)**: `[repos]` の値を `{ path, mode = "serial" }` にすると、その repo は **worktree を作らず repo 本体で 1 本ずつ作業**する(`runner.repo_mode` / `enter_serial` / `leave_serial`)。Unity 等、worktree にチェックアウトすると Library 等(gitignore)が無く再 import が走り共有 `.git` のメタも揺れる repo 用。**runner だけがこの違いを意識**し、タスク生成・記憶・契約ファイルは不変。成果は `loop/<id>` ブランチに残し、run 後は **元ブランチへ checkout で戻す(本体を汚さない)**。中途半端な変更も `loop/<id>` に退避コミット(削除しない)。**同一 serial repo の run は `_serial_lock` で同時 1 本に直列化**(他 repo / 並列 repo とは並行・同一プロセス内 ロック)。既定は文字列指定どおり `parallel`(worktree 並列・後方互換)。serial repo は run 開始時クリーンを想定。

---

## 3. Web UI

- **Next.js(`web/`)= 唯一の UI**。`/runs` `/tasks` `/dashboard` ほか。UI 改善はここ。
- **legacy Jinja は撤去済み**(`webapp/legacy.py` / `webapp/templates/` を削除、`/legacy/*` 廃止。2026-06-17)。FastAPI は `/api/*` のみ供給。`/`(:8765 直叩き)は Next フロントへリダイレクト。
- FastAPI は `/api/*`(JSON + SSE)を出し、Next が `next.config.ts` の rewrite で `/api/*` を `:8765` の uvicorn へプロキシ(単一オリジン)。SSE はブラウザ→FastAPI 直 + CORS。

---

## 4. 環境の罠(再学習を防ぐ・必読)

このセッションで実地に確かめた、`--help` や直感に反する事実:

- **`--max-turns` は実在する**が `claude --help` に出ない(バイナリに `--max-turns <turns>`)。停止条件は turn + `--max-budget-usd` + wall-clock(`threading.Timer`)の 3 段。
- **グローバル `~/.claude/settings.json` が `Bash(*)` / `Write` / `defaultMode: auto` を許可している。** そのため headless の `--allowedTools` は**実質スコープにならない**(settings の allow が勝つ)。read-only を強制したい役(Explorer/Verifier/タスク生成)は **`--disallowedTools Write Edit MultiEdit NotebookEdit Bash`** を付ける(`runner.WRITE_TOOLS` / `read_only=True`)。この上書きが無いと生成が「依頼を実際に実行」しようとして read-only 拒否で turn を空回りし、遅くなる/副産物ファイルが出る。
- **`--json-schema` の構造化出力は `result.structured_output` に入る**(`result` 本文は散文)。`json.loads(result["result"])` ではない。
- **実行は `--input-format stream-json --output-format stream-json --verbose` の双方向**(`RoleSession`)。プロンプトは `-p <arg>` でなく **stdin に user メッセージ(`{"type":"user",...}`)を 1 行流す**。`run_turn()` は次の `type=="result"` イベントまで読み(従来の単発 JSON と同形・`structured_output` 等含む)、セッションは開いたまま次の `send()` を待てる。`close()` で stdin を EOF にして終了。ライブ表示は `runs/<id>/{role}.stream.jsonl`。
- `--max-budget-usd` の支出は 2026/6/15 以降、対話枠ではなく Agent SDK クレジットから引かれる。サブスク型の枯渇は budget では守れないので turn+wall-clock 併用に意味がある。
- **生成(`runner gen`)**は「実行せず変換せよ」を明示し turn 上限を小さく(8)している。これを緩めると遅くなる。
- **Next は `output: standalone`**。`next start` は警告を出す(静的が欠ける恐れ)。本番起動は `node .next/standalone/server.js` で、`just web-build` が `.next/static` を standalone へコピーする。
- **webapp は Python 3.12 ピン**(元は jinja が 3.14 で壊れるため。jinja/legacy 撤去済みだが保守的に据置。上げるなら fastapi/uvicorn の 3.14 動作確認が要る)。runner 等は 3.14 で可。
- **Copilot レビュー要求は REST で行う**: `gh pr edit --add-reviewer "@copilot"` は**無言失敗**する。`gh api -X POST repos/{slug}/pulls/{n}/requested_reviewers -f "reviewers[]=copilot-pull-request-reviewer[bot]"` を使う。検知は `gh pr view --json reviewRequests` が **bot を出さない**ので REST `requested_reviewers`(login=`Copilot`)を見る。Copilot は要求後 ~30s でレビュー投稿(reviewThreads 化)、CI は `gh pr checks --json bucket`(pending/pass/fail)。promote はこれらを実 PR で確認済み(personal repo でも Copilot 動作)。
- macOS には `setsid` が無い。`just app` の `trap 'kill 0'` は**同一プロセスグループの呼び出しシェルまで巻き込む**ので、検証時は `run_in_background` で別ツリーに起動する。

---

## 5. サーバ起動・検証フロー

```
just app  # 唯一の公式起動口。フロント build → backend(:8765)+ frontend(:3000)+ tailscaled 前段
                  # 手元(http://127.0.0.1:3000)/ Tailnet(http://<host>.ts.net:3000)どちらからでも届く
                  # Ctrl-C で serve も自動 off + 子プロセス kill(中途半端な状態を残さない)
just web          # backend(/api + SSE)のみ
just web-build    # フロント本番ビルド(standalone に static 同梱)
```

**起動の不変条件(`app` 内で機械的に守る)**:
1. 起動前に `:3000 / :8765` の残存プロセスを kill(EADDRINUSE 予防)。
2. `tailscale serve --bg` 後に **`tailscale serve status` で設定反映を検証** し、無音失敗を許さない。
3. EXIT/INT/TERM の trap で `tailscale serve --http=3000 off` も実行 → 永続設定の中途半端を残さない。
これらを満たさない起動方法(直接 `node` を叩く・`zsh -i -c` でラップする等)は再現しにくい failure mode を踏むので **常に `just app` を使う**。

- **ネットワーク外(スマホ等)からのアクセス = Tailscale(VPN)**。`just app` が `tailscale serve --bg --http=3000 3000` で **tailscaled を前段プロキシ**にし、`http://<host>.<tailnet>.ts.net:3000` で Tailnet 内デバイスから届く。frontend / backend とも **127.0.0.1 のまま**(serve が前段で受ける)。経路の暗号化・デバイス認証は Tailscale(WireGuard)に委ね、§7 の Bearer は未設定でよい。JSON も SSE も同一オリジン(next rewrite / `SSE_BASE` 空)なので追加設定なしで届く。**この2点を踏まないと「スマホから見えない」になる(実地で踏んだ)**:
  - **macOS Application Firewall が未署名 node への外部着信を block する**。`node` を直接 Tailscale IP にバインドしても iPhone から届かない(自分からは loopback で通るので気づきにくい)。**着信を署名済みの tailscaled に受けさせる**(`tailscale serve`)ことで回避する。`socketfilterfw --getglobalstate` が `State = 1` なら有効。
  - **`uvicorn` の `proxy_headers` は既定で有効**で、Next rewrite/tailscaled が付けた `X-Forwarded-For`(元クライアント=Tailscale IP)を信用し `request.client.host` を上書きする → `auth.py` が「非 localhost」と誤判定し read も **403**。**`webapp/main.py` は `proxy_headers=False` を明示**(auth.py 自身「X-Forwarded-For は信用しない」前提と一致)。serve 経由で `/knowledge` は 200 だが `/api/*` だけ 403 ならこれ。
- ポートなし HTTPS(`https://<host>.ts.net`)にしたい場合は admin コンソールで **HTTPS Certificates を有効化**(`tailscale cert` がハングするのは未有効が原因)してから `tailscale serve --bg 3000`(HTTPS は既定)。frontend は localhost バインドのままでよい。

- **`just app` を再起動するときは先にポート解放**: `lsof -ti tcp:3000 tcp:8765 | xargs kill -9`。残った `next-server` ゾンビが :3000 を握ると `EADDRINUSE` で起動失敗する。
- **`web/` を変えたら必ず `pnpm typecheck` と `pnpm build` を通す** → `just app` 再起動で配信に反映(standalone はメモリに旧コードを保持するので再起動必須)。
- **API エンドポイントを足したら型再生成**: backend 起動中に `cd web && pnpm gen:types`(`/openapi.json` から `lib/types.ts`)。
- `web/node_modules` `web/.next` は gitignore 済み。`pnpm` は nix-darwin(homebrew.nix)で導入済み。

---

## 6. コミット / push の約束

- **作業が一段落したら、明示の指示が無くても自動で commit / push する。**(「push して」を待たない。)毎回 push 可否を尋ねない。グローバル規約のコミット/ブランチ skill に従う。
- ただし push 前に必ず `git status` を確認し、**下記の 2 repo 分離を厳守**。混入の疑いがあれば push せず手を止めて報告する(自動化より安全が優先)。
- **2 repo を取り違えない。** 契約データの変更は `git -C data ...`、コードは engine。**data を含む履歴を public(engine)に push しない。** 過去に engine へ data/設計メモを誤って含めた事故あり(force-push で除去済み)。`backup/*` ブランチはローカル限定。
- engine に紛れ込みやすいもの: ルート直下に置かれた `*.md`(設計メモは `data/plans/` へ)、生成物(`hello.txt` 等)、`data/`。コミット前に `git status` を確認。
- コミットメッセージは日本語、末尾に `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

---

## 7. コスト感(ライブ実行)

- 1 run = 3 モデル呼び出し(Explorer haiku + Implementer sonnet + **Verifier opus**)。hello-loop 規模で **~$0.5**。生成は **~$0.05–0.1**。
- **大きめのライブ実行・実 repo への run は、必要性とコストを一言添えて確認**してから。検証目的の最小 run は妥当。
- **長尺タスクは background 実行**(Web の実行ボタン / `runner run <id>` を Popen)。フォアグラウンドで回すとツールのタイムアウト(例: 600s)で SIGKILL される(過去に発生)。`just app` 等は `run_in_background` で。
- run が SIGKILL されても設計上はデータ損失ゼロ・バックアップ健在・決定論ゲートで安全側に倒れる(organize-downloads の中断時に確認済み)。

---

## 8. この人との進め方

- ユーザーは専門家。指摘は正しい前提で受ける(グローバル規約)。`?`/`？` 終わりは**質問**なので副作用を出さず回答だけ、`!`/`！` は急ぎで正確に実行。
- **実装方針が分岐し、ユーザーの判断が要る所は AskUserQuestion で確認**してから作る(例: 公開/非公開の分け方、複数 repo 方式)。逆に既定が明らかなら決めて進め、何を選んだか述べる。
- **やり切る。** バックエンド→API→UI まで通す。検証は実際に動かして証拠で示す(curl の HTTP コード、build 成功、ライブ run の verdict)。「たぶん動く」で終えない。
- **既存の不変条件を毎回守る**: 削除を作らない / GUI に判断を生成させない / read-only 役の `--disallowedTools` / 種類B は人間 / file-based contract。
- UI 改善は `ui-ux-pro-max` skill の指針 + 既存基調(`.surface` / `PageHeader` / `th-label` / lucide アイコン / dark トークン)に合わせる。アーカイブはアイコンのみ・hover で赤。
- これまでの主要な拡張順: 計測配管 → SQLite/DuckDB/TUI → Web 編集面 → 公開/非公開分離 → 3役 Sub-agents → retry → 多ファイルタスク → プロンプト生成 → 複数 repo → 監視/ライブ transcript → アーカイブ → JSON API + Next 全面刷新 → UI 統一。次の改善もこの一貫性の上に積む。
