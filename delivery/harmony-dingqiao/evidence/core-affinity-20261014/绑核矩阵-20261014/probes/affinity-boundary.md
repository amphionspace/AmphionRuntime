# 绑核边界探针（60 s 短程，只读 affinity-exact）

| 请求 cpuIds | affinity 结果 |
|---|---|
| `0,1,2,3,4,5` | affinity-exact result=1 affinity-set result=0  |
| `10,11` | affinity-exact result=0 affinity-set result=0  |
| `10` | affinity-exact result=0 affinity-set result=0  |
| `11` | affinity-exact result=0 affinity-set result=0  |
| `4,5,6,7,8,9,10,11` | affinity-exact result=0 affinity-set result=0  |
| `4,5,6,7` | affinity-exact result=1 affinity-set result=0  |
| `8,9,10,11` | affinity-exact result=0 affinity-set result=0  |
| `8,9` | affinity-exact result=0 affinity-set result=0  |
