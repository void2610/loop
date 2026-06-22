# Systems

実装と紐づく概念。各概念の frontmatter `resource:` にコードのリポジトリ相対パスを書き、
設計と実装を双方向に辿れるようにする。

* [runner](/systems/runner.md) - 一本道ランナー(Implementer/Verifier / revise / 生成 / promote / archive)。`runner.py`
* [loopdb](/systems/loopdb.md) - SQLite インデックス層(MD 派生・再生成可能)。`loopdb.py`
* [webapp + web](/systems/webapp.md) - FastAPI `/api`(JSON+SSE)+ Next.js フロント(唯一の UI)。`webapp/` `web/`
