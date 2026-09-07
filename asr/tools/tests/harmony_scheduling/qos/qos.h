#pragma once
enum QoS_Level { QOS_BACKGROUND, QOS_UTILITY, QOS_DEFAULT,
                 QOS_USER_INITIATED, QOS_DEADLINE_REQUEST, QOS_USER_INTERACTIVE };
int OH_QoS_GetThreadQoS(QoS_Level *);
int OH_QoS_SetThreadQoS(QoS_Level);
int OH_QoS_ResetThreadQoS();
