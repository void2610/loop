-- verdict ごとの件数・平均コスト・平均ターン・未レビュー件数
SELECT verdict,
       COUNT(*) AS n,
       SUM(CASE WHEN reviewed = 0 THEN 1 ELSE 0 END) AS unreviewed,
       AVG(cost_usd) AS avg_cost,
       AVG(turns) AS avg_turns
FROM runs
GROUP BY verdict
ORDER BY n DESC;
