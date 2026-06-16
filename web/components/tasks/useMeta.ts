"use client";

import { useEffect, useState } from "react";

import { ApiError, api, type MetaResponse } from "@/lib/api";

// /api/meta(repos / statuses / judgment_fields)を読む。設定の単一ソースは loop.toml→API。
export function useMeta() {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .meta()
      .then((m) => {
        if (alive) setMeta(m);
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : "meta の取得に失敗しました");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  return { meta, error, loading };
}
