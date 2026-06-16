-- テストは通った(or 無い)が Verifier が落とした = gaming / 部分未達の疑い。
-- 最重要の R&D シグナル(種類B が読むべき run の優先候補)。
SELECT run_id, task, test_verdict, verifier_verdict, verifier_confidence, started_at
FROM runs
WHERE test_verdict IN ('pass', 'none') AND verifier_verdict = 'fail'
ORDER BY started_at DESC;
