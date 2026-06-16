"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  clearToken,
  fetchMe,
  getToken,
  setToken,
  type MeResponse,
} from "@/lib/auth";

/**
 * トークン入力(フェーズ1: 名前付き Bearer トークン。§7.3 ①拡張版)。
 *
 * リバースプロキシ + OAuth/SSO(フェーズ2。§7.3 ③)を前段に置く構成では、ここは
 * machine token(モバイル/CLI 用)の入力口として併存する。判断生成は一切しない。
 * ローカル(auth_required=false)では認証不要のため、その旨だけ表示する。
 */
export default function LoginPage() {
  const [value, setValue] = useState("");
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      setMe(await fetchMe());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setValue(getToken() ?? "");
    void refresh();
  }, []);

  async function onSave() {
    setToken(value.trim() || null);
    await refresh();
  }

  async function onClear() {
    clearToken();
    setValue("");
    await refresh();
  }

  return (
    <div className="mx-auto max-w-md space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">サインイン</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          リモート公開時の Bearer トークンを設定します。ローカル(127.0.0.1)では不要です。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>現在の状態</CardTitle>
          <CardDescription>
            {loading
              ? "確認中…"
              : me === null
                ? "未取得"
                : me.auth_required
                  ? me.authenticated
                    ? `認証済み: ${me.actor ?? "?"}(scope: ${me.scope.join(", ") || "なし"})`
                    : "未認証(トークンが必要です)"
                  : "ローカル(認証不要 / 全操作可)"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="token">Bearer トークン</Label>
            <Input
              id="token"
              type="password"
              autoComplete="off"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="auth.toml に登録したトークンの平文"
            />
            <p className="text-xs text-muted-foreground">
              トークンはこのブラウザの localStorage にのみ保存され、サーバへは
              Authorization ヘッダで送られます(Cookie は使いません = CSRF 緩和)。
            </p>
          </div>
          <div className="flex gap-2">
            <Button onClick={onSave} disabled={loading}>
              保存
            </Button>
            <Button variant="outline" onClick={onClear} disabled={loading}>
              消去
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
