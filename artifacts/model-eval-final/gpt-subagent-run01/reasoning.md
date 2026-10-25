身份：GPT/Codex sub-agent；不声明未知的精确模型名称。

仅读取指定 input.json，并通过白名单桥接进行了 5 次业务 API 调用：list_alerts、get_incident_services、get_service_profiles、get_maintenance_windows、get_request_metrics。业务结果均由模型自身推理计算，未调用计算器或编程计算业务结果。未读取其他仓库文件、标准答案、verifier、数据库、memory，未搜索，未创建子 agent。

纳入当前 firing 的 P0/P1 告警，得到 INC-AUTH、INC-BASE、INC-DB、INC-LOG、INC-PAY。INC-DB 多条告警合并且等级取 P0，其余各按对应等级。

计算口径：只取 production，5 分钟桶完整落在报告窗口及登记影响区间内。每桶常态量向下取整，超额最低为零。approved 且完整覆盖的维护桶豁免，cancelled 或部分覆盖不豁免。

INC-AUTH：svc-auth 基线 100 bps。08:05—08:10 被 approved 维护完全覆盖，剔除。其余五桶常态量为 10、11、11、11、10；实际失败为 19、22、21、21、18；异常量为 9、11、10、10、8，合计 48。取消维护和部分维护均不豁免。

INC-BASE：svc-baseline 基线 1000 bps。六桶常态量为 116、106、101、112、113、111；实际失败为 115、105、98、111、110、110；每桶异常量均为零，不输出此事件。

INC-DB：svc-cart 基线 200 bps，六桶常态量为 22、20、22、20、21、22；实际失败为 22、18、19、17、21、22；异常量为零，不输出此服务。svc-checkout 登记影响时段为 08:05—08:25，因此只取四桶；基线 100 bps，对应常态量为 10、11、10、11，实际失败为 46、50、41、48，异常量 36、39、31、37，合计 143；08:11—08:14 维护不完整覆盖桶，不能豁免。svc-search 登记影响时段为 08:07—08:23，因此只取 08:10—08:15 和 08:15—08:20；基线 300 bps，常态量分别为 34、31，实际失败为 49、47，异常量分别为 15、16，合计 31。事件总量 143 + 31 = 174。

INC-LOG：svc-log 整个报告窗口被 approved 维护完全覆盖，无有效桶，不输出此事件，无须查询其指标。

INC-PAY：svc-pay-stage 是 staging，排除。svc-pay 维护已取消，全部六桶均计入。基线 50 bps，六桶常态量均为 5；实际失败为 23、23、24、28、27、25；异常量为 18、18、19、23、22、20，合计 120。

事件按异常量降序为 INC-DB 174、INC-PAY 120、INC-AUTH 48，优先级前二为 INC-DB、INC-PAY。final_answer.json 仅写入一次。