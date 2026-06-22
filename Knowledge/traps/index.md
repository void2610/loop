# Traps

再学習を防ぐ環境の罠・`--help` や直感に反する事実(種類A)。CLAUDE.md §4「環境の罠」を概念化したもの。

* [--max-turns は --help に出ないが実在](/traps/max-turns-hidden.md) - 停止条件は turn + budget + wall-clock の 3 段。
* [global settings の allow が --allowedTools を勝つ](/traps/global-settings-allow-wins.md) - read-only 役は --disallowedTools で強制。
* [--json-schema は result.structured_output に入る](/traps/json-schema-structured-output.md) - result 本文は散文。
* [lsof の複数ポートは各ポートに -i が要る](/traps/lsof-multi-port.md) - 裸の 2 つ目は file 扱いで PID を返さない。
* [just app の tailscale 経路と亡霊 bash](/traps/just-app-tailscale-path.md) - detach・trap 解除・PATH・ポート解放の罠。
* [proxy_headers と /api 403](/traps/proxy-headers-auth-403.md) - serve 経由で auth が非 localhost 誤判定。
