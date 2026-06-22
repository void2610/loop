---
okf_version: "0.1"
---

# Knowledge Bundle(loop engine / 公開)

loop engine の設計知識・環境の罠・不変条件を OKF v0.1 形式で管理する公開バンドル。
run 横断の学び・判断(種類B)は **非公開バンドル** `private/`(data repo へのシンボリックリンク)にある。

運用規約は [conventions](/conventions/CONVENTIONS.md)(submodule・読み取り専用)と
loop 固有オーバーレイ [conventions-loop](/conventions-loop.md) を参照。

> **「同一の場所」= anchor 解決規則**。このバンドルは cwd 相対ではなく loop engine checkout(`$LOOP_HOME`)を
> 錨にした絶対パスで解決する。詳細は [conventions-loop](/conventions-loop.md)。

# 目次

## 環境の罠(Traps)
* [Traps](/traps/index.md) - 再学習を防ぐ環境の事実(`--max-turns` / `lsof -i` / `tailscale serve` / `proxy_headers` 等)

## 設計・不変条件(Design)
* [Design](/design/index.md) - 絶対原則・不変条件・設計判断(公開可のもの)

## システム(Systems)
* [Systems](/systems/index.md) - 実装と紐づく概念(`resource:` で `runner.py` / `loopdb.py` / `webapp/` 等を指す)

## 非公開バンドル(private / data repo)
* [private](/private/index.md) - run 横断の学び(`learnings/`)・人間の判断(`decisions/`・種類B)。data private repo にあり public には出ない。
