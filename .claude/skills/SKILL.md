# SKILL — このループの記憶チップ

headless 実行時、worktree 内の Claude Code がネイティブに読む(`--bare` は使わない方針なので自動探索される)。
過去の罠・プロジェクト固有の手順・ドメイン知識をここに蓄積する。runner はこのファイルの git SHA を
各 run の front-matter(`skill_sha`)に刻むので、「どの版の記憶で走ったか」が後から突き合わせられる。

## このリポジトリについて
- 目的は計測配管。実行系は自作しない(詳細は loop-engineering-plan.md §0, §2)。
- worktree 内で作業する。runner.py / loop.toml / TODO.md は基本いじらない。

## 既知の罠
（運用しながら人間が追記する。例: 「テスト X は環境変数 Y が無いと間欠失敗する」など）
