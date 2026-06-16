-- skill 版ごとの pass 率と平均コスト(再現性を統計的に見る)
SELECT skill_sha,
       AVG(CASE WHEN verdict = 'pass' THEN 1.0 ELSE 0 END) AS pass_rate,
       AVG(cost_usd) AS avg_cost,
       COUNT(*) AS n
FROM runs
GROUP BY skill_sha
ORDER BY n DESC;
